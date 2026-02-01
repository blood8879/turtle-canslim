from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass
class NNewResult:
    passed: bool
    has_new_high: bool
    has_new_product: bool
    has_new_management: bool
    price_from_high_pct: Decimal | None
    reason: str


class NNew:
    def __init__(self, high_threshold_pct: float = 0.15):
        self.high_threshold = Decimal(str(high_threshold_pct))

    def evaluate(
        self,
        current_price: Decimal,
        week_52_high: Decimal,
        has_new_product: bool = False,
        has_new_management: bool = False,
    ) -> NNewResult:
        if week_52_high <= 0:
            return NNewResult(
                passed=False,
                has_new_high=False,
                has_new_product=has_new_product,
                has_new_management=has_new_management,
                price_from_high_pct=None,
                reason="Invalid 52-week high",
            )

        price_from_high = (week_52_high - current_price) / week_52_high
        has_new_high = price_from_high <= self.high_threshold

        passed = has_new_high or has_new_product or has_new_management

        reasons = []
        if has_new_high:
            reasons.append(f"Within {self.high_threshold:.0%} of 52-week high")
        if has_new_product:
            reasons.append("New product/service")
        if has_new_management:
            reasons.append("New management")

        if not passed:
            reason = f"Price {price_from_high:.1%} below 52-week high, no new catalysts"
        else:
            reason = "; ".join(reasons)

        return NNewResult(
            passed=passed,
            has_new_high=has_new_high,
            has_new_product=has_new_product,
            has_new_management=has_new_management,
            price_from_high_pct=price_from_high,
            reason=reason,
        )
