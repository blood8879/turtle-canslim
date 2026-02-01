from __future__ import annotations

from decimal import Decimal

import pytest

from src.core.config import CANSLIMConfig
from src.screener.criteria.c_earnings import CEarnings
from src.screener.criteria.a_annual import AAnnual
from src.screener.criteria.l_leader import LLeader
from src.screener.criteria.n_new import NNew
from src.screener.criteria.s_supply import SSupply
from src.screener.criteria.i_institution import IInstitution
from src.screener.scorer import CANSLIMScorer


class TestCEarnings:
    def setup_method(self) -> None:
        self.config = CANSLIMConfig()
        self.criteria = CEarnings(self.config)

    def test_eps_and_revenue_growth_pass(self) -> None:
        result = self.criteria.evaluate(
            current_eps=Decimal("1200"),
            previous_eps=Decimal("1000"),
            current_revenue=Decimal("125000000"),
            previous_revenue=Decimal("100000000"),
        )

        assert result.passed is True
        assert result.eps_growth == Decimal("0.2")
        assert result.revenue_growth == Decimal("0.25")

    def test_eps_growth_fail(self) -> None:
        result = self.criteria.evaluate(
            current_eps=Decimal("1100"),
            previous_eps=Decimal("1000"),
            current_revenue=Decimal("130000000"),
            previous_revenue=Decimal("100000000"),
        )

        assert result.passed is False
        assert "EPS growth" in result.reason

    def test_revenue_growth_weak_but_eps_strong(self) -> None:
        result = self.criteria.evaluate(
            current_eps=Decimal("1300"),
            previous_eps=Decimal("1000"),
            current_revenue=Decimal("110000000"),
            previous_revenue=Decimal("100000000"),
        )

        assert result.passed is True
        assert "EPS +30.0%" in result.reason
        assert "Revenue" in result.reason

    def test_insufficient_data(self) -> None:
        result = self.criteria.evaluate(
            current_eps=None,
            previous_eps=Decimal("1000"),
            current_revenue=Decimal("100000000"),
            previous_revenue=Decimal("80000000"),
        )

        assert result.passed is False
        assert "Insufficient" in result.reason

    def test_negative_previous_eps(self) -> None:
        result = self.criteria.evaluate(
            current_eps=Decimal("100"),
            previous_eps=Decimal("-50"),
            current_revenue=Decimal("100000000"),
            previous_revenue=Decimal("80000000"),
        )

        assert result.passed is False


class TestAAnnual:
    def setup_method(self) -> None:
        self.config = CANSLIMConfig()
        self.criteria = AAnnual(self.config)

    def test_consistent_growth_pass(self) -> None:
        eps_list = [
            Decimal("1000"),
            Decimal("1200"),
            Decimal("1450"),
            Decimal("1750"),
            Decimal("2100"),
        ]

        result = self.criteria.evaluate(eps_list)

        assert result.passed is True
        assert result.avg_eps_growth is not None
        assert result.avg_eps_growth >= Decimal("0.2")

    def test_insufficient_data_fail(self) -> None:
        eps_list = [Decimal("1000"), Decimal("1200")]

        result = self.criteria.evaluate(eps_list)

        assert result.passed is False
        assert "Insufficient" in result.reason

    def test_inconsistent_growth_fail(self) -> None:
        eps_list = [
            Decimal("1000"),
            Decimal("1200"),
            Decimal("1100"),
            Decimal("1300"),
            Decimal("1200"),
        ]

        result = self.criteria.evaluate(eps_list)

        assert result.passed is False


class TestLLeader:
    def setup_method(self) -> None:
        self.criteria = LLeader(min_rs_rating=80)

    def test_high_rs_rating_pass(self) -> None:
        result = self.criteria.evaluate(rs_rating=85)

        assert result.passed is True
        assert result.rs_rating == 85

    def test_low_rs_rating_fail(self) -> None:
        result = self.criteria.evaluate(rs_rating=70)

        assert result.passed is False
        assert result.rs_rating == 70

    def test_calculate_rs_from_returns(self) -> None:
        stock_returns = [Decimal("0.05")] * 12
        market_returns = [Decimal("0.02")] * 12

        result = self.criteria.evaluate(
            stock_returns=stock_returns,
            market_returns=market_returns,
        )

        assert result.rs_rating is not None
        assert result.rs_rating > 50


class TestNNew:
    def setup_method(self) -> None:
        self.criteria = NNew()

    def test_near_52_week_high_pass(self) -> None:
        result = self.criteria.evaluate(
            current_price=Decimal("95000"),
            week_52_high=Decimal("100000"),
        )

        assert result.passed is True
        assert result.has_new_high is True

    def test_far_from_high_fail(self) -> None:
        result = self.criteria.evaluate(
            current_price=Decimal("70000"),
            week_52_high=Decimal("100000"),
        )

        assert result.passed is False
        assert result.has_new_high is False

    def test_new_product_pass(self) -> None:
        result = self.criteria.evaluate(
            current_price=Decimal("70000"),
            week_52_high=Decimal("100000"),
            has_new_product=True,
        )

        assert result.passed is True


class TestCANSLIMScorer:
    def setup_method(self) -> None:
        self.scorer = CANSLIMScorer(min_score_for_candidate=5)

    def test_high_score_candidate(self) -> None:
        from src.screener.criteria.c_earnings import CEarningsResult
        from src.screener.criteria.a_annual import AAnnualResult
        from src.screener.criteria.l_leader import LLeaderResult
        from src.screener.criteria.m_market import MMarketResult, MarketDirection

        c_result = CEarningsResult(
            passed=True, eps_growth=Decimal("0.25"), revenue_growth=Decimal("0.30"),
            current_eps=Decimal("1250"), previous_eps=Decimal("1000"),
            current_revenue=Decimal("130000000"), previous_revenue=Decimal("100000000"),
            reason="Pass"
        )

        a_result = AAnnualResult(
            passed=True, avg_eps_growth=Decimal("0.22"), yearly_growths=[Decimal("0.2")] * 3,
            roe=Decimal("0.15"), years_of_data=4, reason="Pass"
        )

        l_result = LLeaderResult(
            passed=True, rs_rating=85, price_vs_market=Decimal("0.1"),
            is_industry_leader=False, reason="Pass"
        )

        m_result = MMarketResult(
            passed=True, direction=MarketDirection.CONFIRMED_UPTREND,
            index_above_ma=True, distribution_days=2, follow_through_day=False,
            reason="Pass"
        )

        result = self.scorer.calculate_score(
            symbol="005930",
            name="삼성전자",
            c_result=c_result,
            a_result=a_result,
            l_result=l_result,
            m_result=m_result,
        )

        assert result.total_score >= 4
        assert result.is_candidate is False

    def test_all_criteria_pass(self) -> None:
        from src.screener.criteria.c_earnings import CEarningsResult
        from src.screener.criteria.a_annual import AAnnualResult
        from src.screener.criteria.n_new import NNewResult
        from src.screener.criteria.s_supply import SSupplyResult
        from src.screener.criteria.l_leader import LLeaderResult
        from src.screener.criteria.i_institution import IInstitutionResult
        from src.screener.criteria.m_market import MMarketResult, MarketDirection

        result = self.scorer.calculate_score(
            symbol="005930",
            name="삼성전자",
            c_result=CEarningsResult(True, Decimal("0.25"), Decimal("0.30"), Decimal("1250"), Decimal("1000"), Decimal("130000000"), Decimal("100000000"), "Pass"),
            a_result=AAnnualResult(True, Decimal("0.22"), [Decimal("0.2")] * 3, Decimal("0.15"), 4, "Pass"),
            n_result=NNewResult(True, True, False, False, Decimal("0.05"), "Pass"),
            s_result=SSupplyResult(True, 10000000, 1000000, True, False, "Pass"),
            l_result=LLeaderResult(True, 85, Decimal("0.1"), False, "Pass"),
            i_result=IInstitutionResult(True, Decimal("0.15"), 20, True, "Pass"),
            m_result=MMarketResult(True, MarketDirection.CONFIRMED_UPTREND, True, 2, False, "Pass"),
        )

        assert result.total_score == 7
        assert result.is_candidate is True
        assert result.score_string == "CANSLIM"
