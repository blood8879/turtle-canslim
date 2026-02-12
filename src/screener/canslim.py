from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.core.config import Settings, get_settings
from src.core.logger import get_logger
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
        FundamentalRepository,
        DailyPriceRepository,
        CANSLIMScoreRepository,
    )

logger = get_logger(__name__)


class CANSLIMScreener:
    def __init__(
        self,
        stock_repo: StockRepository,
        fundamental_repo: FundamentalRepository,
        price_repo: DailyPriceRepository,
        score_repo: CANSLIMScoreRepository,
        settings: Settings | None = None,
    ):
        self._settings = settings or get_settings()
        self._stock_repo = stock_repo
        self._fundamental_repo = fundamental_repo
        self._price_repo = price_repo
        self._score_repo = score_repo

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

    async def screen(self, market: str = "krx") -> list[CANSLIMScoreResult]:
        logger.info("canslim_screen_start", market=market)

        invalidated = await self._score_repo.invalidate_candidates(market)
        if invalidated:
            logger.info("canslim_invalidated_old_candidates", count=invalidated, market=market)

        await self._evaluate_market_condition(market)

        stocks = await self._stock_repo.get_all_active(market)
        logger.info("canslim_stocks_loaded", count=len(stocks))

        results: list[CANSLIMScoreResult] = []

        for stock in stocks:
            try:
                result = await self.evaluate_stock(stock.symbol, stock.name, stock.id, market)
                results.append(result)

                if result.is_candidate:
                    await self._save_score(stock.id, result)

            except Exception as e:
                logger.error("canslim_evaluate_error", symbol=stock.symbol, error=str(e))
                continue

        candidates = [r for r in results if r.is_candidate]

        logger.info(
            "canslim_screen_complete",
            total=len(results),
            candidates=len(candidates),
        )

        ranked_candidates = self._scorer.rank_candidates(results)
        non_candidates = [r for r in results if not r.is_candidate]
        return ranked_candidates + non_candidates

    async def evaluate_stock(
        self,
        symbol: str,
        name: str,
        stock_id: int,
        market: str = "krx",
    ) -> CANSLIMScoreResult:
        c_result = await self._evaluate_c(stock_id)
        a_result = await self._evaluate_a(stock_id)
        n_result = await self._evaluate_n(stock_id)
        s_result = await self._evaluate_s(stock_id)
        l_result = await self._evaluate_l(stock_id, market)
        i_result = await self._evaluate_i(stock_id)
        m_result = self._market_result

        return self._scorer.calculate_score(
            symbol=symbol,
            name=name,
            c_result=c_result,
            a_result=a_result,
            n_result=n_result,
            s_result=s_result,
            l_result=l_result,
            i_result=i_result,
            m_result=m_result,
        )

    async def _evaluate_c(self, stock_id: int):
        latest = await self._fundamental_repo.get_latest_quarterly(stock_id)
        if not latest or not latest.fiscal_quarter:
            return self._c_criteria.evaluate(None, None, None, None)

        current, previous = await self._fundamental_repo.get_yoy_comparison(
            stock_id, latest.fiscal_year, latest.fiscal_quarter
        )

        if not current or not previous:
            return self._c_criteria.evaluate(None, None, None, None)

        return self._c_criteria.evaluate(
            current_eps=current.eps,
            previous_eps=previous.eps,
            current_revenue=current.revenue,
            previous_revenue=previous.revenue,
        )

    async def _evaluate_a(self, stock_id: int):
        annual_data = await self._fundamental_repo.get_latest_annual(stock_id, years=5)

        if not annual_data:
            return self._a_criteria.evaluate([], None)

        eps_list = [f.eps for f in reversed(annual_data)]
        roe = annual_data[0].roe if annual_data else None

        return self._a_criteria.evaluate(eps_list, roe)

    async def _evaluate_n(self, stock_id: int):
        prices = await self._price_repo.get_period(stock_id, 252)

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

    async def _evaluate_s(self, stock_id: int):
        prices = await self._price_repo.get_period(stock_id, 50)

        if len(prices) < 20:
            return self._s_criteria.evaluate(None, 0, 1)

        stock = await self._stock_repo.get_by_id(stock_id)

        current_volume = prices[-1].volume
        avg_volume = sum(p.volume for p in prices) // len(prices)

        recent_20 = prices[-20:]
        high_20 = max(p.high for p in recent_20)
        low_20 = min(p.low for p in recent_20)
        price_range = high_20 - low_20
        avg_price = Decimal(str(sum(p.close for p in recent_20) / 20))

        return self._s_criteria.evaluate(
            shares_outstanding=stock.shares_outstanding if stock else None,
            current_volume=current_volume,
            avg_volume_50d=avg_volume,
            price_range_20d=price_range,
            avg_price_20d=avg_price,
        )

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

    def _index_symbol_for_market(self, market: str) -> str:
        market_lower = market.lower()
        if market_lower in ("krx", "kospi", "kosdaq"):
            return "^KOSPI"
        return "^GSPC"

    async def _evaluate_l(self, stock_id: int, market: str = "krx"):
        prices = await self._price_repo.get_period(stock_id, 252)

        if len(prices) < 60:
            return self._l_criteria.evaluate(rs_rating=None)

        monthly_returns = self._calc_monthly_returns(list(prices))

        index_symbol = self._index_symbol_for_market(market)
        index_stock = await self._stock_repo.get_by_symbol(index_symbol)
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

    async def _evaluate_i(self, stock_id: int):
        stock = await self._stock_repo.get_by_id(stock_id)
        if not stock:
            return self._i_criteria.evaluate(institution_ownership=None)

        return self._i_criteria.evaluate(
            institution_ownership=stock.institutional_ownership,
            institution_count=stock.institutional_count,
            quarterly_change=None,
        )

    async def _evaluate_market_condition(self, market: str) -> None:
        index_symbol = self._index_symbol_for_market(market)
        index_stock = await self._stock_repo.get_by_symbol(index_symbol)
        if not index_stock:
            logger.warning("market_index_not_found", symbol=index_symbol)
            self._market_result = None
            return

        prices = await self._price_repo.get_period(index_stock.id, 252)
        if len(prices) < 50:
            logger.warning("market_index_insufficient_data", symbol=index_symbol, count=len(prices))
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
            symbol=index_symbol,
            direction=self._market_result.direction.value,
            passed=self._market_result.passed,
        )

    def set_market_condition(self, market_result):
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

    async def get_candidates(self, min_score: int = 4) -> list[CANSLIMScoreResult]:
        scores = await self._score_repo.get_candidates(min_score)
        results: list[CANSLIMScoreResult] = []

        for score in scores:
            stock = await self._stock_repo.get_by_id(score.stock_id)
            if stock:
                result = CANSLIMScoreResult(
                    symbol=stock.symbol,
                    name=stock.name,
                    total_score=score.total_score or 0,
                    is_candidate=score.is_candidate,
                    c_result=None,
                    a_result=None,
                    n_result=None,
                    s_result=None,
                    l_result=None,
                    i_result=None,
                    m_result=None,
                    rs_rating=score.rs_rating,
                    c_eps_growth=score.c_eps_growth,
                    c_revenue_growth=score.c_revenue_growth,
                    a_eps_growth=score.a_eps_growth,
                )
                results.append(result)

        return results
