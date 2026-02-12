from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.screener.criteria.c_earnings import CEarningsResult
from src.screener.criteria.a_annual import AAnnualResult
from src.screener.criteria.n_new import NNewResult
from src.screener.criteria.s_supply import SSupplyResult
from src.screener.criteria.l_leader import LLeaderResult
from src.screener.criteria.i_institution import IInstitutionResult
from src.screener.criteria.m_market import MMarketResult


@dataclass
class CANSLIMScoreResult:
    symbol: str
    name: str
    total_score: int
    is_candidate: bool

    c_result: CEarningsResult | None
    a_result: AAnnualResult | None
    n_result: NNewResult | None
    s_result: SSupplyResult | None
    l_result: LLeaderResult | None
    i_result: IInstitutionResult | None
    m_result: MMarketResult | None

    rs_rating: int | None
    c_eps_growth: Decimal | None
    c_revenue_growth: Decimal | None
    a_eps_growth: Decimal | None

    @property
    def scores(self) -> dict[str, bool]:
        return {
            "C": self.c_result.passed if self.c_result else False,
            "A": self.a_result.passed if self.a_result else False,
            "N": self.n_result.passed if self.n_result else False,
            "S": self.s_result.passed if self.s_result else False,
            "L": self.l_result.passed if self.l_result else False,
            "I": self.i_result.passed if self.i_result else False,
            "M": self.m_result.passed if self.m_result else True,
        }

    @property
    def score_string(self) -> str:
        return "".join(
            letter if passed else "-"
            for letter, passed in self.scores.items()
        )


class CANSLIMScorer:
    def __init__(
        self,
        min_score_for_candidate: int = 4,
        min_roe: float = 0.12,
    ):
        self.min_score = min_score_for_candidate
        self.min_roe = Decimal(str(min_roe))

    def calculate_score(
        self,
        symbol: str,
        name: str,
        c_result: CEarningsResult | None = None,
        a_result: AAnnualResult | None = None,
        n_result: NNewResult | None = None,
        s_result: SSupplyResult | None = None,
        l_result: LLeaderResult | None = None,
        i_result: IInstitutionResult | None = None,
        m_result: MMarketResult | None = None,
    ) -> CANSLIMScoreResult:
        scores = [
            c_result.passed if c_result else False,
            a_result.passed if a_result else False,
            n_result.passed if n_result else False,
            s_result.passed if s_result else False,
            l_result.passed if l_result else False,
            i_result.passed if i_result else False,
            m_result.passed if m_result else True,
        ]

        total_score = sum(scores)

        c_passed = c_result.passed if c_result else False
        l_passed = l_result.passed if l_result else False
        m_passed = m_result.passed if m_result else True

        core_criteria_met = c_passed and l_passed and m_passed

        roe = a_result.roe if a_result else None
        roe_met = roe is not None and roe >= self.min_roe

        current_revenue = c_result.current_revenue if c_result else None
        revenue_positive = current_revenue is not None and current_revenue > 0

        is_candidate = (
            total_score >= self.min_score
            and core_criteria_met
            and roe_met
            and revenue_positive
        )

        return CANSLIMScoreResult(
            symbol=symbol,
            name=name,
            total_score=total_score,
            is_candidate=is_candidate,
            c_result=c_result,
            a_result=a_result,
            n_result=n_result,
            s_result=s_result,
            l_result=l_result,
            i_result=i_result,
            m_result=m_result,
            rs_rating=l_result.rs_rating if l_result else None,
            c_eps_growth=c_result.eps_growth if c_result else None,
            c_revenue_growth=c_result.revenue_growth if c_result else None,
            a_eps_growth=a_result.avg_eps_growth if a_result else None,
        )

    def rank_candidates(
        self,
        results: list[CANSLIMScoreResult],
    ) -> list[CANSLIMScoreResult]:
        candidates = [r for r in results if r.is_candidate]

        def sort_key(r: CANSLIMScoreResult) -> tuple:
            rs = r.rs_rating or 0
            eps = float(r.c_eps_growth or 0)
            score = r.total_score
            return (-score, -rs, -eps)

        return sorted(candidates, key=sort_key)
