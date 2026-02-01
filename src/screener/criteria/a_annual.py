from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.core.config import CANSLIMConfig


@dataclass
class AAnnualResult:
    passed: bool
    avg_eps_growth: Decimal | None
    yearly_growths: list[Decimal]
    roe: Decimal | None
    years_of_data: int
    reason: str


class AAnnual:
    def __init__(self, config: CANSLIMConfig):
        self.min_eps_growth = Decimal(str(config.a_eps_growth_min))
        self.min_years = config.a_min_years

    def evaluate(
        self,
        annual_eps_list: list[Decimal | None],
        roe: Decimal | None = None,
    ) -> AAnnualResult:
        valid_eps = [eps for eps in annual_eps_list if eps is not None]

        if len(valid_eps) < self.min_years + 1:
            return AAnnualResult(
                passed=False,
                avg_eps_growth=None,
                yearly_growths=[],
                roe=roe,
                years_of_data=len(valid_eps),
                reason=f"Insufficient data: {len(valid_eps)} years, need {self.min_years + 1}",
            )

        yearly_growths: list[Decimal] = []
        for i in range(1, len(valid_eps)):
            if valid_eps[i - 1] <= 0:
                continue
            growth = (valid_eps[i] - valid_eps[i - 1]) / valid_eps[i - 1]
            yearly_growths.append(growth)

        if len(yearly_growths) < self.min_years:
            return AAnnualResult(
                passed=False,
                avg_eps_growth=None,
                yearly_growths=yearly_growths,
                roe=roe,
                years_of_data=len(valid_eps),
                reason=f"Insufficient growth data: {len(yearly_growths)} periods",
            )

        avg_growth = sum(yearly_growths) / len(yearly_growths)

        recent_growths = yearly_growths[-self.min_years:]
        positive_years = sum(1 for g in recent_growths if g > 0)
        mostly_positive = positive_years >= max(1, len(recent_growths) - 1)

        passed = avg_growth >= self.min_eps_growth and mostly_positive

        if not passed:
            reasons = []
            if avg_growth < self.min_eps_growth:
                reasons.append(f"Avg EPS growth {avg_growth:.1%} < {self.min_eps_growth:.0%}")
            if not mostly_positive:
                reasons.append(f"EPS positive only {positive_years}/{len(recent_growths)} years")
            reason = "; ".join(reasons)
        else:
            reason = f"Avg EPS growth +{avg_growth:.1%} over {len(yearly_growths)} years"

        return AAnnualResult(
            passed=passed,
            avg_eps_growth=avg_growth,
            yearly_growths=yearly_growths,
            roe=roe,
            years_of_data=len(valid_eps),
            reason=reason,
        )
