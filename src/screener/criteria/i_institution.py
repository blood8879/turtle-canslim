from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.core.config import CANSLIMConfig


@dataclass
class IInstitutionResult:
    passed: bool
    institution_ownership: Decimal | None
    institution_count: int | None
    recent_buying: bool
    reason: str


class IInstitution:
    def __init__(self, config: CANSLIMConfig):
        self.min_ownership = Decimal(str(config.i_institution_min))

    def evaluate(
        self,
        institution_ownership: Decimal | None,
        institution_count: int | None = None,
        quarterly_change: Decimal | None = None,
    ) -> IInstitutionResult:
        if institution_ownership is None:
            return IInstitutionResult(
                passed=False,
                institution_ownership=None,
                institution_count=institution_count,
                recent_buying=False,
                reason="No institutional ownership data",
            )

        ownership_passed = institution_ownership >= self.min_ownership

        recent_buying = quarterly_change is not None and quarterly_change > 0

        quality_institutions = institution_count is not None and institution_count >= 10

        passed = ownership_passed and (recent_buying or quality_institutions)

        reasons = []
        if ownership_passed:
            reasons.append(f"Institutional ownership {institution_ownership:.1%}")
        if recent_buying:
            reasons.append(f"Recent institutional buying +{quarterly_change:.1%}")
        if quality_institutions:
            reasons.append(f"{institution_count} institutional holders")

        if not passed:
            if not ownership_passed:
                reason = f"Institutional ownership {institution_ownership:.1%} < {self.min_ownership:.0%}"
            else:
                reason = "No recent institutional buying activity"
        else:
            reason = "; ".join(reasons)

        return IInstitutionResult(
            passed=passed,
            institution_ownership=institution_ownership,
            institution_count=institution_count,
            recent_buying=recent_buying,
            reason=reason,
        )
