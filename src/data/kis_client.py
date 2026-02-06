from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from src.core.config import Settings, TradingMode, get_settings
from src.core.exceptions import KISAPIError
from src.core.logger import get_logger

if TYPE_CHECKING:
    from mojito import KoreaInvestment

logger = get_logger(__name__)


class PriceData:
    def __init__(
        self,
        date: datetime,
        open: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: int,
    ):
        self.date = date
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


class BalanceData:
    def __init__(
        self,
        total_balance: Decimal,
        available_cash: Decimal,
        total_eval_amount: Decimal,
        total_profit_loss: Decimal,
        total_profit_loss_rate: Decimal,
    ):
        self.total_balance = total_balance
        self.available_cash = available_cash
        self.total_eval_amount = total_eval_amount
        self.total_profit_loss = total_profit_loss
        self.total_profit_loss_rate = total_profit_loss_rate


class HoldingData:
    def __init__(
        self,
        symbol: str,
        name: str,
        quantity: int,
        avg_price: Decimal,
        current_price: Decimal,
        eval_amount: Decimal,
        profit_loss: Decimal,
        profit_loss_rate: Decimal,
    ):
        self.symbol = symbol
        self.name = name
        self.quantity = quantity
        self.avg_price = avg_price
        self.current_price = current_price
        self.eval_amount = eval_amount
        self.profit_loss = profit_loss
        self.profit_loss_rate = profit_loss_rate


class OrderResult:
    def __init__(
        self,
        success: bool,
        order_id: str | None,
        message: str,
        raw_response: dict[str, Any] | None = None,
    ):
        self.success = success
        self.order_id = order_id
        self.message = message
        self.raw_response = raw_response


class KISClient:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._client: KoreaInvestment | None = None

    @property
    def is_paper_mode(self) -> bool:
        return self._settings.trading_mode == TradingMode.PAPER

    @property
    def client(self) -> KoreaInvestment:
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def _create_client(self) -> KoreaInvestment:
        from mojito import KoreaInvestment

        app_key, app_secret, account = self._settings.active_kis_credentials

        if not all([app_key, app_secret, account]):
            raise KISAPIError("KIS API credentials not configured")

        # mojito expects acc_no in "12345678-01" format
        if "-" not in account:
            account = f"{account[:8]}-{account[8:]}" if len(account) > 8 else f"{account}-01"
            logger.warning(
                "kis_account_format_fixed",
                hint="Account should be in '12345678-01' format in .env",
            )

        logger.info(
            "creating_kis_client",
            mode="paper" if self.is_paper_mode else "live",
            account=account[:4] + "****",
        )

        return KoreaInvestment(
            api_key=app_key,
            api_secret=app_secret,
            acc_no=account,
            mock=self.is_paper_mode,
        )

    async def get_current_price(self, symbol: str) -> dict[str, Any]:
        try:
            response = self.client.fetch_price(symbol)
            return {
                "symbol": symbol,
                "price": Decimal(str(response.get("stck_prpr", 0))),
                "change": Decimal(str(response.get("prdy_vrss", 0))),
                "change_rate": Decimal(str(response.get("prdy_ctrt", 0))),
                "volume": int(response.get("acml_vol", 0)),
                "high": Decimal(str(response.get("stck_hgpr", 0))),
                "low": Decimal(str(response.get("stck_lwpr", 0))),
                "open": Decimal(str(response.get("stck_oprc", 0))),
            }
        except Exception as e:
            logger.error("kis_fetch_price_error", symbol=symbol, error=str(e))
            raise KISAPIError(f"Failed to fetch price for {symbol}: {e}") from e

    async def get_daily_prices(
        self,
        symbol: str,
        period: int = 100,
        end_date: datetime | None = None,
    ) -> list[PriceData]:
        try:
            end_dt = end_date or datetime.now()
            response = self.client.fetch_ohlcv(
                symbol=symbol,
                timeframe="D",
                end=end_dt.strftime("%Y%m%d"),
                adj_price=True,
            )

            prices: list[PriceData] = []
            for row in response[:period]:
                prices.append(
                    PriceData(
                        date=datetime.strptime(str(row.get("stck_bsop_date", "")), "%Y%m%d"),
                        open=Decimal(str(row.get("stck_oprc", 0))),
                        high=Decimal(str(row.get("stck_hgpr", 0))),
                        low=Decimal(str(row.get("stck_lwpr", 0))),
                        close=Decimal(str(row.get("stck_clpr", 0))),
                        volume=int(row.get("acml_vol", 0)),
                    )
                )

            return prices
        except Exception as e:
            logger.error("kis_fetch_ohlcv_error", symbol=symbol, error=str(e))
            raise KISAPIError(f"Failed to fetch daily prices for {symbol}: {e}") from e

    async def get_balance(self) -> BalanceData:
        try:
            response = self.client.fetch_balance()

            return BalanceData(
                total_balance=Decimal(str(response.get("tot_evlu_amt", 0))),
                available_cash=Decimal(str(response.get("dnca_tot_amt", 0))),
                total_eval_amount=Decimal(str(response.get("scts_evlu_amt", 0))),
                total_profit_loss=Decimal(str(response.get("evlu_pfls_smtl_amt", 0))),
                total_profit_loss_rate=Decimal(str(response.get("evlu_pfls_rt", 0))),
            )
        except Exception as e:
            logger.error("kis_fetch_balance_error", error=str(e))
            raise KISAPIError(f"Failed to fetch balance: {e}") from e

    async def get_holdings(self) -> list[HoldingData]:
        try:
            response = self.client.fetch_balance()
            holdings: list[HoldingData] = []

            for item in response.get("output1", []):
                if int(item.get("hldg_qty", 0)) > 0:
                    holdings.append(
                        HoldingData(
                            symbol=item.get("pdno", ""),
                            name=item.get("prdt_name", ""),
                            quantity=int(item.get("hldg_qty", 0)),
                            avg_price=Decimal(str(item.get("pchs_avg_pric", 0))),
                            current_price=Decimal(str(item.get("prpr", 0))),
                            eval_amount=Decimal(str(item.get("evlu_amt", 0))),
                            profit_loss=Decimal(str(item.get("evlu_pfls_amt", 0))),
                            profit_loss_rate=Decimal(str(item.get("evlu_pfls_rt", 0))),
                        )
                    )

            return holdings
        except Exception as e:
            logger.error("kis_fetch_holdings_error", error=str(e))
            raise KISAPIError(f"Failed to fetch holdings: {e}") from e

    async def buy_market(self, symbol: str, quantity: int) -> OrderResult:
        if not self.is_paper_mode:
            logger.warning("live_market_buy_attempt", symbol=symbol, quantity=quantity)

        try:
            response = self.client.create_market_buy_order(
                symbol=symbol,
                quantity=quantity,
            )

            success = response.get("rt_cd") == "0"
            order_id = response.get("output", {}).get("ODNO")

            logger.info(
                "market_buy_order",
                symbol=symbol,
                quantity=quantity,
                success=success,
                order_id=order_id,
                mode="paper" if self.is_paper_mode else "live",
            )

            return OrderResult(
                success=success,
                order_id=order_id,
                message=response.get("msg1", ""),
                raw_response=response,
            )
        except Exception as e:
            logger.error("kis_buy_order_error", symbol=symbol, quantity=quantity, error=str(e))
            raise KISAPIError(f"Failed to place buy order for {symbol}: {e}") from e

    async def sell_market(self, symbol: str, quantity: int) -> OrderResult:
        if not self.is_paper_mode:
            logger.warning("live_market_sell_attempt", symbol=symbol, quantity=quantity)

        try:
            response = self.client.create_market_sell_order(
                symbol=symbol,
                quantity=quantity,
            )

            success = response.get("rt_cd") == "0"
            order_id = response.get("output", {}).get("ODNO")

            logger.info(
                "market_sell_order",
                symbol=symbol,
                quantity=quantity,
                success=success,
                order_id=order_id,
                mode="paper" if self.is_paper_mode else "live",
            )

            return OrderResult(
                success=success,
                order_id=order_id,
                message=response.get("msg1", ""),
                raw_response=response,
            )
        except Exception as e:
            logger.error("kis_sell_order_error", symbol=symbol, quantity=quantity, error=str(e))
            raise KISAPIError(f"Failed to place sell order for {symbol}: {e}") from e

    async def cancel_order(self, order_id: str) -> OrderResult:
        try:
            response = self.client.cancel_order(
                order_no=order_id,
                quantity=0,
                total=True,
            )

            success = response.get("rt_cd") == "0"

            logger.info("cancel_order", order_id=order_id, success=success)

            return OrderResult(
                success=success,
                order_id=order_id,
                message=response.get("msg1", ""),
                raw_response=response,
            )
        except Exception as e:
            logger.error("kis_cancel_order_error", order_id=order_id, error=str(e))
            raise KISAPIError(f"Failed to cancel order {order_id}: {e}") from e

    async def get_order_status(self, order_id: str) -> dict[str, Any]:
        try:
            response = self.client.fetch_open_order()

            for order in response.get("output", []):
                if order.get("odno") == order_id:
                    return {
                        "order_id": order_id,
                        "symbol": order.get("pdno"),
                        "order_type": order.get("sll_buy_dvsn_cd"),
                        "quantity": int(order.get("ord_qty", 0)),
                        "filled_quantity": int(order.get("tot_ccld_qty", 0)),
                        "price": Decimal(str(order.get("ord_unpr", 0))),
                        "status": order.get("ord_dvsn_name"),
                    }

            raise KISAPIError(f"Order not found: {order_id}")
        except KISAPIError:
            raise
        except Exception as e:
            logger.error("kis_order_status_error", order_id=order_id, error=str(e))
            raise KISAPIError(f"Failed to get order status for {order_id}: {e}") from e
