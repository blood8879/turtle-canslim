from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.core.config import CANSLIMConfig


@dataclass
class CEarningsResult:
    passed: bool
    eps_growth: Decimal | None
    revenue_growth: Decimal | None
    current_eps: Decimal | None
    previous_eps: Decimal | None
    current_revenue: Decimal | None
    previous_revenue: Decimal | None
    reason: str


class CEarnings:
    def __init__(self, config: CANSLIMConfig):
        self.min_eps_growth = Decimal(str(config.c_eps_growth_min))
        self.min_revenue_growth = Decimal(str(config.c_revenue_growth_min))

    def evaluate(
        self,
        current_eps: Decimal | None,
        previous_eps: Decimal | None,
        current_revenue: Decimal | None,
        previous_revenue: Decimal | None,
    ) -> CEarningsResult:
        if current_eps is None or previous_eps is None:
            return CEarningsResult(
                passed=False,
                eps_growth=None,
                revenue_growth=None,
                current_eps=current_eps,
                previous_eps=previous_eps,
                current_revenue=current_revenue,
                previous_revenue=previous_revenue,
                reason="Insufficient EPS data",
            )

        if current_revenue is None or previous_revenue is None:
            return CEarningsResult(
                passed=False,
                eps_growth=None,
                revenue_growth=None,
                current_eps=current_eps,
                previous_eps=previous_eps,
                current_revenue=current_revenue,
                previous_revenue=previous_revenue,
                reason="Insufficient revenue data",
            )

        if previous_eps <= 0:
            return CEarningsResult(
                passed=False,
                eps_growth=None,
                revenue_growth=None,
                current_eps=current_eps,
                previous_eps=previous_eps,
                current_revenue=current_revenue,
                previous_revenue=previous_revenue,
                reason="Previous EPS is zero or negative",
            )

        if previous_revenue <= 0:
            return CEarningsResult(
                passed=False,
                eps_growth=None,
                revenue_growth=None,
                current_eps=current_eps,
                previous_eps=previous_eps,
                current_revenue=current_revenue,
                previous_revenue=previous_revenue,
                reason="Previous revenue is zero or negative",
            )

        eps_growth = (current_eps - previous_eps) / previous_eps
        revenue_growth = (current_revenue - previous_revenue) / previous_revenue

        eps_passed = eps_growth >= self.min_eps_growth
        revenue_passed = revenue_growth >= self.min_revenue_growth
        passed = eps_passed

        if not eps_passed:
            reason = f"EPS growth {eps_growth:.1%} < {self.min_eps_growth:.0%}"
        elif revenue_passed:
            reason = f"EPS +{eps_growth:.1%}, Revenue +{revenue_growth:.1%}"
        else:
            reason = f"EPS +{eps_growth:.1%} (Revenue {revenue_growth:.1%} < {self.min_revenue_growth:.0%})"

        return CEarningsResult(
            passed=passed,
            eps_growth=eps_growth,
            revenue_growth=revenue_growth,
            current_eps=current_eps,
            previous_eps=previous_eps,
            current_revenue=current_revenue,
            previous_revenue=previous_revenue,
            reason=reason,
        )
