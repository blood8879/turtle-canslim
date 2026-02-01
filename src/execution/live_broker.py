from __future__ import annotations

from decimal import Decimal

from src.core.config import Settings, TradingMode, get_settings
from src.core.exceptions import KISAPIError, TradingError
from src.core.logger import get_logger, get_trading_logger
from src.data.kis_client import KISClient
from src.execution.broker_interface import (
    AccountBalance,
    BrokerInterface,
    BrokerOrder,
    BrokerPosition,
    OrderRequest,
    OrderResponse,
)

logger = get_logger(__name__)
tlog = get_trading_logger()


class LiveBroker(BrokerInterface):
    """KIS API 기반 브로커. PAPER 모드(모의투자)와 LIVE 모드(실거래) 모두 지원."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._kis_client: KISClient | None = None
        self._connected = False

    @property
    def is_paper_trading(self) -> bool:
        return self._settings.trading_mode == TradingMode.PAPER

    async def connect(self) -> bool:
        try:
            self._kis_client = KISClient(self._settings)
            _ = self._kis_client.client
            self._connected = True
            logger.info(
                "kis_broker_connected",
                mode=self._settings.trading_mode.value,
                paper=self.is_paper_trading,
            )
            return True
        except Exception as e:
            logger.error("live_broker_connect_error", error=str(e))
            raise TradingError(f"Failed to connect to KIS: {e}") from e

    async def disconnect(self) -> None:
        self._connected = False
        self._kis_client = None
        logger.info("live_broker_disconnected")

    def _ensure_connected(self) -> KISClient:
        if not self._connected or not self._kis_client:
            raise TradingError("LiveBroker not connected")
        return self._kis_client

    async def get_current_price(self, symbol: str) -> Decimal:
        client = self._ensure_connected()
        try:
            data = await client.get_current_price(symbol)
            price = data["price"]
            tlog.debug("live_price_fetched", symbol=symbol, price=float(price))
            return price
        except KISAPIError as e:
            tlog.error("live_price_api_error", symbol=symbol, error=str(e))
            raise
        except Exception as e:
            tlog.error("live_price_error", symbol=symbol, error=str(e))
            raise TradingError(f"Failed to get price for {symbol}: {e}") from e

    async def get_balance(self) -> AccountBalance:
        client = self._ensure_connected()
        try:
            balance = await client.get_balance()
            return AccountBalance(
                total_value=balance.total_balance,
                cash_balance=balance.available_cash,
                securities_value=balance.total_eval_amount,
                buying_power=balance.available_cash,
            )
        except KISAPIError:
            raise
        except Exception as e:
            raise TradingError(f"Failed to get balance: {e}") from e

    async def get_positions(self) -> list[BrokerPosition]:
        client = self._ensure_connected()
        try:
            holdings = await client.get_holdings()
            return [
                BrokerPosition(
                    symbol=h.symbol,
                    quantity=h.quantity,
                    avg_price=h.avg_price,
                    current_price=h.current_price,
                    market_value=h.eval_amount,
                    unrealized_pnl=h.profit_loss,
                    unrealized_pnl_pct=h.profit_loss_rate / 100,
                )
                for h in holdings
            ]
        except KISAPIError:
            raise
        except Exception as e:
            raise TradingError(f"Failed to get positions: {e}") from e

    async def get_position(self, symbol: str) -> BrokerPosition | None:
        positions = await self.get_positions()
        for pos in positions:
            if pos.symbol == symbol:
                return pos
        return None

    async def place_order(self, request: OrderRequest) -> OrderResponse:
        client = self._ensure_connected()

        logger.warning(
            "live_order_attempt",
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
        )

        try:
            tlog.info(
                "live_order_submitting",
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                order_type=request.order_type,
            )

            if request.order_type == "MARKET":
                if request.side == "BUY":
                    result = await client.buy_market(request.symbol, request.quantity)
                else:
                    result = await client.sell_market(request.symbol, request.quantity)
            else:
                raise TradingError(f"Unsupported order type: {request.order_type}")

            if result.success:
                tlog.info(
                    "live_order_filled",
                    order_id=result.order_id,
                    symbol=request.symbol,
                    side=request.side,
                    quantity=request.quantity,
                    message=result.message,
                )
            else:
                tlog.warning(
                    "live_order_failed",
                    symbol=request.symbol,
                    side=request.side,
                    quantity=request.quantity,
                    message=result.message,
                )

            return OrderResponse(
                success=result.success,
                order_id=result.order_id,
                message=result.message,
                raw_response=result.raw_response,
            )

        except KISAPIError as e:
            tlog.error(
                "live_order_api_error",
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                error=str(e),
            )
            raise
        except Exception as e:
            tlog.error(
                "live_order_error",
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                error=str(e),
            )
            raise TradingError(f"Failed to place order: {e}") from e

    async def cancel_order(self, order_id: str) -> OrderResponse:
        client = self._ensure_connected()
        try:
            result = await client.cancel_order(order_id)
            return OrderResponse(
                success=result.success,
                order_id=result.order_id,
                message=result.message,
                raw_response=result.raw_response,
            )
        except KISAPIError:
            raise
        except Exception as e:
            raise TradingError(f"Failed to cancel order: {e}") from e

    async def get_order_status(self, order_id: str) -> BrokerOrder | None:
        client = self._ensure_connected()
        try:
            status = await client.get_order_status(order_id)
            return BrokerOrder(
                order_id=order_id,
                symbol=status["symbol"],
                side=status["order_type"],
                quantity=status["quantity"],
                order_type="MARKET",
                price=status["price"],
                status=status["status"],
                filled_quantity=status["filled_quantity"],
                filled_price=status["price"],
                created_at="",
                updated_at=None,
            )
        except KISAPIError as e:
            if "not found" in str(e).lower():
                return None
            raise
        except Exception as e:
            raise TradingError(f"Failed to get order status: {e}") from e

    async def get_open_orders(self) -> list[BrokerOrder]:
        return []
