from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from src.core.config import Settings, TradingMode, get_settings
from src.core.exceptions import KISAPIError
from src.core.logger import get_logger

if TYPE_CHECKING:
    from python_kis import KoreaInvestment

logger = get_logger(__name__)


class USPriceData:
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


class USOrderResult:
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


class USMarketClient:
    EXCHANGES = {
        "NYSE": "NYS",
        "NASDAQ": "NAS",
        "AMEX": "AMS",
    }

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
        from python_kis import KoreaInvestment

        app_key, app_secret, account = self._settings.active_kis_credentials

        if not all([app_key, app_secret, account]):
            raise KISAPIError("KIS API credentials not configured")

        logger.info(
            "creating_us_market_client",
            mode="paper" if self.is_paper_mode else "live",
        )

        return KoreaInvestment(
            api_key=app_key,
            api_secret=app_secret,
            acc_no=account,
            mock=self.is_paper_mode,
        )

    def _get_exchange_code(self, exchange: str) -> str:
        return self.EXCHANGES.get(exchange.upper(), "NAS")

    async def get_current_price(self, symbol: str, exchange: str = "NASDAQ") -> dict[str, Any]:
        try:
            excd = self._get_exchange_code(exchange)
            response = self.client.fetch_overseas_price(
                symbol=symbol,
                exchange=excd,
            )

            return {
                "symbol": symbol,
                "exchange": exchange,
                "price": Decimal(str(response.get("last", 0))),
                "change": Decimal(str(response.get("diff", 0))),
                "change_rate": Decimal(str(response.get("rate", 0))),
                "volume": int(response.get("tvol", 0)),
                "high": Decimal(str(response.get("high", 0))),
                "low": Decimal(str(response.get("low", 0))),
                "open": Decimal(str(response.get("open", 0))),
            }
        except Exception as e:
            logger.error("us_fetch_price_error", symbol=symbol, error=str(e))
            raise KISAPIError(f"Failed to fetch US price for {symbol}: {e}") from e

    async def get_daily_prices(
        self,
        symbol: str,
        exchange: str = "NASDAQ",
        period: int = 100,
    ) -> list[USPriceData]:
        try:
            excd = self._get_exchange_code(exchange)
            response = self.client.fetch_overseas_ohlcv(
                symbol=symbol,
                exchange=excd,
                timeframe="D",
                adj_price=True,
            )

            prices: list[USPriceData] = []
            for row in response[:period]:
                try:
                    date_str = str(row.get("xymd", ""))
                    if len(date_str) == 8:
                        date = datetime.strptime(date_str, "%Y%m%d")
                    else:
                        continue

                    prices.append(
                        USPriceData(
                            date=date,
                            open=Decimal(str(row.get("open", 0))),
                            high=Decimal(str(row.get("high", 0))),
                            low=Decimal(str(row.get("low", 0))),
                            close=Decimal(str(row.get("clos", 0))),
                            volume=int(row.get("tvol", 0)),
                        )
                    )
                except Exception:
                    continue

            return prices
        except Exception as e:
            logger.error("us_fetch_ohlcv_error", symbol=symbol, error=str(e))
            raise KISAPIError(f"Failed to fetch US daily prices for {symbol}: {e}") from e

    async def get_balance(self) -> dict[str, Any]:
        try:
            response = self.client.fetch_overseas_balance()

            return {
                "total_value_usd": Decimal(str(response.get("tot_evlu_pfls_amt", 0))),
                "available_cash_usd": Decimal(str(response.get("frcr_pchs_amt", 0))),
                "securities_value_usd": Decimal(str(response.get("evlu_amt_smtl", 0))),
            }
        except Exception as e:
            logger.error("us_fetch_balance_error", error=str(e))
            raise KISAPIError(f"Failed to fetch US balance: {e}") from e

    async def get_holdings(self) -> list[dict[str, Any]]:
        try:
            response = self.client.fetch_overseas_balance()
            holdings: list[dict[str, Any]] = []

            for item in response.get("output1", []):
                if int(item.get("ccld_qty", 0)) > 0:
                    holdings.append({
                        "symbol": item.get("ovrs_pdno", ""),
                        "name": item.get("ovrs_item_name", ""),
                        "quantity": int(item.get("ccld_qty", 0)),
                        "avg_price": Decimal(str(item.get("pchs_avg_pric", 0))),
                        "current_price": Decimal(str(item.get("now_pric2", 0))),
                        "eval_amount": Decimal(str(item.get("ovrs_stck_evlu_amt", 0))),
                        "profit_loss": Decimal(str(item.get("frcr_evlu_pfls_amt", 0))),
                        "profit_loss_rate": Decimal(str(item.get("evlu_pfls_rt", 0))),
                    })

            return holdings
        except Exception as e:
            logger.error("us_fetch_holdings_error", error=str(e))
            raise KISAPIError(f"Failed to fetch US holdings: {e}") from e

    async def buy_market(
        self,
        symbol: str,
        quantity: int,
        exchange: str = "NASDAQ",
    ) -> USOrderResult:
        if not self.is_paper_mode:
            logger.warning("us_live_buy_attempt", symbol=symbol, quantity=quantity)

        try:
            excd = self._get_exchange_code(exchange)
            response = self.client.create_overseas_market_buy_order(
                symbol=symbol,
                exchange=excd,
                quantity=quantity,
            )

            success = response.get("rt_cd") == "0"
            order_id = response.get("output", {}).get("ODNO")

            logger.info(
                "us_market_buy_order",
                symbol=symbol,
                quantity=quantity,
                success=success,
                order_id=order_id,
            )

            return USOrderResult(
                success=success,
                order_id=order_id,
                message=response.get("msg1", ""),
                raw_response=response,
            )
        except Exception as e:
            logger.error("us_buy_order_error", symbol=symbol, error=str(e))
            raise KISAPIError(f"Failed to place US buy order for {symbol}: {e}") from e

    async def sell_market(
        self,
        symbol: str,
        quantity: int,
        exchange: str = "NASDAQ",
    ) -> USOrderResult:
        if not self.is_paper_mode:
            logger.warning("us_live_sell_attempt", symbol=symbol, quantity=quantity)

        try:
            excd = self._get_exchange_code(exchange)
            response = self.client.create_overseas_market_sell_order(
                symbol=symbol,
                exchange=excd,
                quantity=quantity,
            )

            success = response.get("rt_cd") == "0"
            order_id = response.get("output", {}).get("ODNO")

            logger.info(
                "us_market_sell_order",
                symbol=symbol,
                quantity=quantity,
                success=success,
                order_id=order_id,
            )

            return USOrderResult(
                success=success,
                order_id=order_id,
                message=response.get("msg1", ""),
                raw_response=response,
            )
        except Exception as e:
            logger.error("us_sell_order_error", symbol=symbol, error=str(e))
            raise KISAPIError(f"Failed to place US sell order for {symbol}: {e}") from e

    async def cancel_order(self, order_id: str, exchange: str = "NASDAQ") -> USOrderResult:
        try:
            excd = self._get_exchange_code(exchange)
            response = self.client.cancel_overseas_order(
                order_no=order_id,
                exchange=excd,
                quantity=0,
                total=True,
            )

            success = response.get("rt_cd") == "0"

            return USOrderResult(
                success=success,
                order_id=order_id,
                message=response.get("msg1", ""),
                raw_response=response,
            )
        except Exception as e:
            logger.error("us_cancel_order_error", order_id=order_id, error=str(e))
            raise KISAPIError(f"Failed to cancel US order {order_id}: {e}") from e
