"""CANSLIM screener for US stocks using SEC EDGAR data."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.core.config import Settings, get_settings
from src.core.logger import get_logger
from src.data.sec_edgar_client import SECEdgarClient, USFinancialStatement
from src.screener.criteria.c_earnings import CEarnings
from src.screener.criteria.a_annual import AAnnual
from src.screener.criteria.n_new import NNew
from src.screener.criteria.s_supply import SSupply
from src.screener.criteria.l_leader import LLeader
from src.screener.criteria.i_institution import IInstitution
from src.screener.criteria.m_market import MMarket
from src.screener.scorer import CANSLIMScorer, CANSLIMScoreResult

if TYPE_CHECKING:
    from src.data.repositories import (
        StockRepository,
        DailyPriceRepository,
        CANSLIMScoreRepository,
    )

logger = get_logger(__name__)


class USCANSLIMScreener:
    """CANSLIM screener for US stocks.

    Uses SEC EDGAR API for financial data instead of DART.
    Price data comes from KIS US Market API.
    """

    def __init__(
        self,
        stock_repo: StockRepository,
        price_repo: DailyPriceRepository,
        score_repo: CANSLIMScoreRepository,
        sec_client: SECEdgarClient | None = None,
        settings: Settings | None = None,
    ):
        self._settings = settings or get_settings()
        self._stock_repo = stock_repo
        self._price_repo = price_repo
        self._score_repo = score_repo
        self._sec_client = sec_client or SECEdgarClient()

        config = self._settings.canslim
        self._c_criteria = CEarnings(config)
        self._a_criteria = AAnnual(config)
        self._n_criteria = NNew()
        self._s_criteria = SSupply()
        self._l_criteria = LLeader(config.l_rs_min)
        self._i_criteria = IInstitution(config)
        self._m_criteria = MMarket()
        self._scorer = CANSLIMScorer(min_roe=config.min_roe)

        self._market_result = None
        self._company_facts_cache: dict[str, dict] = {}

    async def _evaluate_market_condition(self) -> None:
        index_stock = await self._stock_repo.get_by_symbol("^GSPC")
        if not index_stock:
            logger.warning("market_index_not_found", symbol="^GSPC")
            self._market_result = None
            return

        prices = await self._price_repo.get_period(index_stock.id, 252)
        if len(prices) < 50:
            logger.warning("market_index_insufficient_data", symbol="^GSPC", count=len(prices))
            self._market_result = None
            return

        current_price = prices[-1].close
        ma_prices = prices[-50:]
        index_ma = Decimal(str(sum(p.close for p in ma_prices))) / Decimal(str(len(ma_prices)))

        daily_changes: list[Decimal] = []
        daily_volumes: list[int] = []
        for i in range(1, len(prices)):
            if prices[i - 1].close != 0:
                change = (prices[i].close - prices[i - 1].close) / prices[i - 1].close
                daily_changes.append(change)
                daily_volumes.append(prices[i].volume)

        distribution_days = self._m_criteria.count_distribution_days(daily_changes, daily_volumes)
        follow_through = self._m_criteria.detect_follow_through(daily_changes, daily_volumes)

        recent_trend_up = len(prices) >= 20 and prices[-1].close > prices[-20].close

        self._market_result = self._m_criteria.evaluate(
            index_price=current_price,
            index_ma=index_ma,
            distribution_days=distribution_days,
            recent_follow_through=follow_through,
            index_trend_up=recent_trend_up,
        )

        logger.info(
            "market_condition_evaluated",
            symbol="^GSPC",
            direction=self._market_result.direction.value,
            passed=self._market_result.passed,
        )

    async def screen(self, symbols: list[str] | None = None) -> list[CANSLIMScoreResult]:
        logger.info("us_canslim_screen_start", symbol_count=len(symbols) if symbols else "all")

        await self._evaluate_market_condition()

        if symbols is None:
            stocks = await self._stock_repo.get_all_active("us")
            symbols = [s.symbol for s in stocks]

        logger.info("us_canslim_stocks_loaded", count=len(symbols))

        results: list[CANSLIMScoreResult] = []

        for symbol in symbols:
            try:
                result = await self.evaluate_stock(symbol)
                if result:
                    results.append(result)

                    if result.is_candidate:
                        stock = await self._stock_repo.get_by_symbol(symbol)
                        if stock:
                            await self._save_score(stock.id, result)

            except Exception as e:
                logger.error("us_canslim_evaluate_error", symbol=symbol, error=str(e))
                continue

        candidates = [r for r in results if r.is_candidate]
        ranked = self._scorer.rank_candidates(results)

        logger.info(
            "us_canslim_screen_complete",
            total=len(results),
            candidates=len(candidates),
        )

        return ranked

    async def evaluate_stock(self, symbol: str) -> CANSLIMScoreResult | None:
        """Evaluate a single US stock against CANSLIM criteria.

        Args:
            symbol: Stock ticker symbol (e.g., "AAPL")

        Returns:
            CANSLIMScoreResult or None if evaluation fails
        """
        try:
            facts = await self._get_company_facts(symbol)
            if not facts:
                return None

            c_result = await self._evaluate_c(symbol, facts)
            a_result = await self._evaluate_a(symbol, facts)
            n_result = await self._evaluate_n(symbol)
            s_result = await self._evaluate_s(symbol, facts)
            l_result = await self._evaluate_l(symbol)
            i_result = await self._evaluate_i(symbol)
            m_result = self._market_result

            company_name = facts.get("entityName", symbol)

            return self._scorer.calculate_score(
                symbol=symbol,
                name=company_name,
                c_result=c_result,
                a_result=a_result,
                n_result=n_result,
                s_result=s_result,
                l_result=l_result,
                i_result=i_result,
                m_result=m_result,
            )

        except Exception as e:
            logger.error("us_canslim_stock_error", symbol=symbol, error=str(e))
            return None

    async def _get_company_facts(self, symbol: str) -> dict | None:
        """Get and cache company facts from SEC."""
        if symbol in self._company_facts_cache:
            return self._company_facts_cache[symbol]

        try:
            facts = await self._sec_client.get_company_facts(symbol)
            self._company_facts_cache[symbol] = facts
            return facts
        except Exception as e:
            logger.warning("us_canslim_facts_error", symbol=symbol, error=str(e))
            return None

    async def _evaluate_c(self, symbol: str, facts: dict):
        """Evaluate C indicator using SEC quarterly data."""
        current_year = datetime.now().year
        current_quarter = (datetime.now().month - 1) // 3 + 1

        try:
            current, year_ago = await self._sec_client.get_yoy_comparison(
                symbol, current_year, current_quarter
            )

            if not current or not year_ago:
                prev_quarter = current_quarter - 1 if current_quarter > 1 else 4
                prev_year = current_year if current_quarter > 1 else current_year - 1
                current, year_ago = await self._sec_client.get_yoy_comparison(
                    symbol, prev_year, prev_quarter
                )

            if not current or not year_ago:
                return self._c_criteria.evaluate(None, None, None, None)

            return self._c_criteria.evaluate(
                current_eps=current.eps,
                previous_eps=year_ago.eps,
                current_revenue=current.revenue,
                previous_revenue=year_ago.revenue,
            )

        except Exception as e:
            logger.warning("us_canslim_c_error", symbol=symbol, error=str(e))
            return self._c_criteria.evaluate(None, None, None, None)

    async def _evaluate_a(self, symbol: str, facts: dict):
        """Evaluate A indicator using SEC annual data."""
        try:
            financials = await self._sec_client.get_financial_statements(symbol, years=5)

            if not financials:
                return self._a_criteria.evaluate([], None)

            eps_list = [f.eps for f in financials if f.eps is not None]
            roe = financials[-1].roe if financials and financials[-1].roe else None

            return self._a_criteria.evaluate(eps_list, roe)

        except Exception as e:
            logger.warning("us_canslim_a_error", symbol=symbol, error=str(e))
            return self._a_criteria.evaluate([], None)

    async def _evaluate_n(self, symbol: str):
        """Evaluate N indicator using price data."""
        try:
            stock = await self._stock_repo.get_by_symbol(symbol)
            if not stock:
                return self._n_criteria.evaluate(Decimal(0), Decimal(1), False, False)

            prices = await self._price_repo.get_period(stock.id, 252)

            if len(prices) < 20:
                return self._n_criteria.evaluate(Decimal(0), Decimal(1), False, False)

            current_price = prices[-1].close
            week_52_high = max(p.high for p in prices)

            return self._n_criteria.evaluate(
                current_price=current_price,
                week_52_high=week_52_high,
                has_new_product=False,
                has_new_management=False,
            )

        except Exception as e:
            logger.warning("us_canslim_n_error", symbol=symbol, error=str(e))
            return self._n_criteria.evaluate(Decimal(0), Decimal(1), False, False)

    async def _evaluate_s(self, symbol: str, facts: dict):
        try:
            stock = await self._stock_repo.get_by_symbol(symbol)
            if not stock:
                return self._s_criteria.evaluate(None, 0, 1)

            prices = await self._price_repo.get_period(stock.id, 50)

            if len(prices) < 20:
                return self._s_criteria.evaluate(None, 0, 1)

            current_volume = prices[-1].volume
            avg_volume = sum(p.volume for p in prices) // len(prices)

            recent_20 = prices[-20:]
            high_20 = max(p.high for p in recent_20)
            low_20 = min(p.low for p in recent_20)
            price_range = high_20 - low_20
            avg_price = Decimal(str(sum(p.close for p in recent_20) / 20))

            return self._s_criteria.evaluate(
                shares_outstanding=stock.shares_outstanding,
                current_volume=current_volume,
                avg_volume_50d=avg_volume,
                price_range_20d=price_range,
                avg_price_20d=avg_price,
            )

        except Exception as e:
            logger.warning("us_canslim_s_error", symbol=symbol, error=str(e))
            return self._s_criteria.evaluate(None, 0, 1)

    @staticmethod
    def _calc_monthly_returns(prices: list) -> list[Decimal]:
        monthly_returns: list[Decimal] = []
        for i in range(0, min(12, len(prices) // 20)):
            start_idx = -(i + 1) * 20
            end_idx = -i * 20 if i > 0 else None

            if end_idx:
                month_prices = prices[start_idx:end_idx]
            else:
                month_prices = prices[start_idx:]

            if len(month_prices) >= 2:
                ret = (month_prices[-1].close - month_prices[0].close) / month_prices[0].close
                monthly_returns.insert(0, ret)
        return monthly_returns

    async def _evaluate_l(self, symbol: str):
        try:
            stock = await self._stock_repo.get_by_symbol(symbol)
            if not stock:
                return self._l_criteria.evaluate(rs_rating=None)

            prices = await self._price_repo.get_period(stock.id, 252)

            if len(prices) < 60:
                return self._l_criteria.evaluate(rs_rating=None)

            monthly_returns = self._calc_monthly_returns(list(prices))

            index_stock = await self._stock_repo.get_by_symbol("^GSPC")
            market_returns: list[Decimal] = []
            if index_stock:
                index_prices = await self._price_repo.get_period(index_stock.id, 252)
                if len(index_prices) >= 60:
                    market_returns = self._calc_monthly_returns(list(index_prices))

            if not market_returns:
                market_returns = [Decimal("0.01")] * len(monthly_returns)

            return self._l_criteria.evaluate(
                stock_returns=monthly_returns,
                market_returns=market_returns,
            )

        except Exception as e:
            logger.warning("us_canslim_l_error", symbol=symbol, error=str(e))
            return self._l_criteria.evaluate(rs_rating=None)

    async def _evaluate_i(self, symbol: str):
        stock = await self._stock_repo.get_by_symbol(symbol)
        if not stock:
            return self._i_criteria.evaluate(institution_ownership=None)

        return self._i_criteria.evaluate(
            institution_ownership=stock.institutional_ownership,
            institution_count=stock.institutional_count,
            quarterly_change=None,
        )

    def set_market_condition(self, market_result):
        """Set market direction result (M indicator)."""
        self._market_result = market_result

    async def _save_score(self, stock_id: int, result: CANSLIMScoreResult) -> None:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        score_data = {
            "c_score": result.c_result.passed if result.c_result else None,
            "a_score": result.a_result.passed if result.a_result else None,
            "n_score": result.n_result.passed if result.n_result else None,
            "s_score": result.s_result.passed if result.s_result else None,
            "l_score": result.l_result.passed if result.l_result else None,
            "i_score": result.i_result.passed if result.i_result else None,
            "m_score": result.m_result.passed if result.m_result else None,
            "total_score": result.total_score,
            "rs_rating": result.rs_rating,
            "c_eps_growth": result.c_eps_growth,
            "c_revenue_growth": result.c_revenue_growth,
            "a_eps_growth": result.a_eps_growth,
            "is_candidate": result.is_candidate,
        }
        existing = await self._score_repo.get_by_stock_date(stock_id, today)
        if existing:
            await self._score_repo.update(existing.id, **score_data)
        else:
            await self._score_repo.create(stock_id=stock_id, date=today, **score_data)

    async def close(self):
        """Clean up resources."""
        await self._sec_client.close()


def get_screener(
    market: str,
    stock_repo: StockRepository,
    price_repo: DailyPriceRepository,
    score_repo: CANSLIMScoreRepository,
    fundamental_repo=None,
    settings: Settings | None = None,
):
    """Factory function to get the appropriate screener for a market.

    Args:
        market: "krx" or "us"
        stock_repo: Stock repository
        price_repo: Price repository
        score_repo: CANSLIM score repository
        fundamental_repo: Fundamental repository (required for KRX)
        settings: Optional settings

    Returns:
        CANSLIMScreener or USCANSLIMScreener
    """
    if market.lower() == "us":
        return USCANSLIMScreener(
            stock_repo=stock_repo,
            price_repo=price_repo,
            score_repo=score_repo,
            settings=settings,
        )
    else:
        from src.screener.canslim import CANSLIMScreener

        if fundamental_repo is None:
            raise ValueError("fundamental_repo is required for KRX market")

        return CANSLIMScreener(
            stock_repo=stock_repo,
            fundamental_repo=fundamental_repo,
            price_repo=price_repo,
            score_repo=score_repo,
            settings=settings,
        )
