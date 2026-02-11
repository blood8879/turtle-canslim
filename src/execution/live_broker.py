from __future__ import annotations

from decimal import Decimal
from typing import Literal

from src.core.config import Settings, TradingMode, get_settings
from src.core.exceptions import KISAPIError, TradingError
from src.core.logger import get_logger, get_trading_logger
from src.data.kis_client import KISClient
from src.data.us_client import USMarketClient
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

MarketType = Literal["krx", "us"]


class LiveBroker(BrokerInterface):
    """KIS API 기반 브로커. PAPER 모드(모의투자)와 LIVE 모드(실거래) 모두 지원.
    
    market 파라미터로 KRX(국내) 또는 US(해외) 시장을 선택합니다.
    - krx: KISClient 사용 (국내 주식 API)
    - us: USMarketClient 사용 (해외 주식 API)
    """

    def __init__(self, settings: Settings | None = None, market: MarketType = "krx"):
        self._settings = settings or get_settings()
        self._market = market
        self._kis_client: KISClient | None = None
        self._us_client: USMarketClient | None = None
        self._connected = False

    @property
    def is_paper_trading(self) -> bool:
        return self._settings.trading_mode == TradingMode.PAPER

    @property
    def market(self) -> str:
        return self._market

    @property
    def is_us_market(self) -> bool:
        return self._market == "us"

    async def connect(self) -> bool:
        try:
            if self.is_us_market:
                self._us_client = USMarketClient(self._settings)
                _ = self._us_client.client
            else:
                self._kis_client = KISClient(self._settings)
                _ = self._kis_client.client
            self._connected = True
            logger.info(
                "kis_broker_connected",
                mode=self._settings.trading_mode.value,
                paper=self.is_paper_trading,
                market=self._market,
            )
            return True
        except Exception as e:
            logger.error("live_broker_connect_error", error=str(e), market=self._market)
            raise TradingError(f"Failed to connect to KIS ({self._market}): {e}") from e

    async def disconnect(self) -> None:
        self._connected = False
        self._kis_client = None
        self._us_client = None
        logger.info("live_broker_disconnected", market=self._market)

    def _ensure_krx_connected(self) -> KISClient:
        if not self._connected or not self._kis_client:
            raise TradingError("LiveBroker (KRX) not connected")
        return self._kis_client

    def _ensure_us_connected(self) -> USMarketClient:
        if not self._connected or not self._us_client:
            raise TradingError("LiveBroker (US) not connected")
        return self._us_client

    async def get_current_price(self, symbol: str, exchange: str = "NASDAQ") -> Decimal:
        try:
            if self.is_us_market:
                client = self._ensure_us_connected()
                data = await client.get_current_price(symbol, exchange)
            else:
                client = self._ensure_krx_connected()
                data = await client.get_current_price(symbol)
            price = data["price"]
            tlog.debug("live_price_fetched", symbol=symbol, price=float(price), market=self._market)
            return price
        except KISAPIError as e:
            tlog.error("live_price_api_error", symbol=symbol, error=str(e), market=self._market)
            raise
        except Exception as e:
            tlog.error("live_price_error", symbol=symbol, error=str(e), market=self._market)
            raise TradingError(f"Failed to get price for {symbol}: {e}") from e

    async def get_balance(self) -> AccountBalance:
        try:
            if self.is_us_market:
                client = self._ensure_us_connected()
                balance = await client.get_balance()
                return AccountBalance(
                    total_value=balance["total_value_usd"],
                    cash_balance=balance["available_cash_usd"],
                    securities_value=balance["securities_value_usd"],
                    buying_power=balance["available_cash_usd"],
                )
            else:
                client = self._ensure_krx_connected()
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
            raise TradingError(f"Failed to get balance ({self._market}): {e}") from e

    async def get_positions(self) -> list[BrokerPosition]:
        try:
            if self.is_us_market:
                client = self._ensure_us_connected()
                holdings = await client.get_holdings()
                return [
                    BrokerPosition(
                        symbol=h["symbol"],
                        quantity=h["quantity"],
                        avg_price=h["avg_price"],
                        current_price=h["current_price"],
                        market_value=h["eval_amount"],
                        unrealized_pnl=h["profit_loss"],
                        unrealized_pnl_pct=h["profit_loss_rate"] / 100,
                    )
                    for h in holdings
                ]
            else:
                client = self._ensure_krx_connected()
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
            raise TradingError(f"Failed to get positions ({self._market}): {e}") from e

    async def get_position(self, symbol: str) -> BrokerPosition | None:
        positions = await self.get_positions()
        for pos in positions:
            if pos.symbol == symbol:
                return pos
        return None

    async def place_order(self, request: OrderRequest, exchange: str = "NASDAQ") -> OrderResponse:
        logger.warning(
            "live_order_attempt",
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            market=self._market,
        )

        try:
            tlog.info(
                "live_order_submitting",
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                order_type=request.order_type,
                market=self._market,
            )

            if request.order_type == "MARKET":
                if self.is_us_market:
                    client = self._ensure_us_connected()
                    if request.side == "BUY":
                        result = await client.buy_market(request.symbol, request.quantity, exchange)
                    else:
                        result = await client.sell_market(request.symbol, request.quantity, exchange)
                else:
                    client = self._ensure_krx_connected()
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
                    market=self._market,
                )
            else:
                tlog.warning(
                    "live_order_failed",
                    symbol=request.symbol,
                    side=request.side,
                    quantity=request.quantity,
                    message=result.message,
                    market=self._market,
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
                market=self._market,
            )
            raise
        except Exception as e:
            tlog.error(
                "live_order_error",
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                error=str(e),
                market=self._market,
            )
            raise TradingError(f"Failed to place order ({self._market}): {e}") from e

    async def cancel_order(self, order_id: str, exchange: str = "NASDAQ") -> OrderResponse:
        try:
            if self.is_us_market:
                client = self._ensure_us_connected()
                result = await client.cancel_order(order_id, exchange)
            else:
                client = self._ensure_krx_connected()
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
            raise TradingError(f"Failed to cancel order ({self._market}): {e}") from e

    async def get_order_status(self, order_id: str) -> BrokerOrder | None:
        if self.is_us_market:
            return None
        client = self._ensure_krx_connected()
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
