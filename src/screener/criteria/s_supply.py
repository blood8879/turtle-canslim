from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class SSupplyResult:
    passed: bool
    shares_outstanding: int | None
    avg_volume: int | None
    volume_surge: bool
    tight_price_action: bool
    reason: str


class SSupply:
    def __init__(
        self,
        max_shares_outstanding: int = 50_000_000,
        volume_surge_threshold: float = 1.5,
    ):
        self.max_shares = max_shares_outstanding
        self.volume_surge_threshold = Decimal(str(volume_surge_threshold))

    def evaluate(
        self,
        shares_outstanding: int | None,
        current_volume: int,
        avg_volume_50d: int,
        price_range_20d: Decimal | None = None,
        avg_price_20d: Decimal | None = None,
    ) -> SSupplyResult:
        small_supply = shares_outstanding is not None and shares_outstanding < self.max_shares

        volume_surge = False
        if avg_volume_50d > 0:
            volume_ratio = Decimal(str(current_volume)) / Decimal(str(avg_volume_50d))
            volume_surge = volume_ratio >= self.volume_surge_threshold

        tight_price_action = False
        if price_range_20d is not None and avg_price_20d is not None and avg_price_20d > 0:
            price_tightness = price_range_20d / avg_price_20d
            tight_price_action = price_tightness < Decimal("0.10")

        passed = small_supply or volume_surge or tight_price_action

        reasons = []
        if small_supply:
            reasons.append(f"Small float: {shares_outstanding:,} shares")
        if volume_surge:
            reasons.append(f"Volume surge: {volume_ratio:.1f}x avg")
        if tight_price_action:
            reasons.append("Tight price action")

        if not passed:
            reason = "No supply/demand signals"
        else:
            reason = "; ".join(reasons)

        return SSupplyResult(
            passed=passed,
            shares_outstanding=shares_outstanding,
            avg_volume=avg_volume_50d,
            volume_surge=volume_surge,
            tight_price_action=tight_price_action,
            reason=reason,
        )
