from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class MarketDirection(str, Enum):
    CONFIRMED_UPTREND = "confirmed_uptrend"
    UPTREND_UNDER_PRESSURE = "uptrend_under_pressure"
    MARKET_IN_CORRECTION = "market_in_correction"
    DOWNTREND = "downtrend"


@dataclass
class MMarketResult:
    passed: bool
    direction: MarketDirection
    index_above_ma: bool
    distribution_days: int
    follow_through_day: bool
    reason: str


class MMarket:
    def __init__(
        self,
        ma_period: int = 50,
        max_distribution_days: int = 5,
    ):
        self.ma_period = ma_period
        self.max_distribution_days = max_distribution_days

    def evaluate(
        self,
        index_price: Decimal,
        index_ma: Decimal,
        distribution_days: int,
        recent_follow_through: bool = False,
        index_trend_up: bool = True,
    ) -> MMarketResult:
        index_above_ma = index_price > index_ma

        if index_above_ma and distribution_days <= 2 and index_trend_up:
            direction = MarketDirection.CONFIRMED_UPTREND
        elif index_above_ma and distribution_days <= self.max_distribution_days:
            direction = MarketDirection.UPTREND_UNDER_PRESSURE
        elif not index_above_ma and distribution_days > self.max_distribution_days:
            direction = MarketDirection.DOWNTREND
        else:
            direction = MarketDirection.MARKET_IN_CORRECTION

        passed = direction in [
            MarketDirection.CONFIRMED_UPTREND,
            MarketDirection.UPTREND_UNDER_PRESSURE,
        ]

        if recent_follow_through and direction == MarketDirection.MARKET_IN_CORRECTION:
            passed = True
            direction = MarketDirection.UPTREND_UNDER_PRESSURE

        reasons = []
        if index_above_ma:
            reasons.append(f"Index above {self.ma_period}MA")
        else:
            reasons.append(f"Index below {self.ma_period}MA")

        reasons.append(f"{distribution_days} distribution days")

        if recent_follow_through:
            reasons.append("Recent follow-through day")

        reason = "; ".join(reasons)

        return MMarketResult(
            passed=passed,
            direction=direction,
            index_above_ma=index_above_ma,
            distribution_days=distribution_days,
            follow_through_day=recent_follow_through,
            reason=reason,
        )

    def count_distribution_days(
        self,
        daily_changes: list[Decimal],
        daily_volumes: list[int],
        lookback: int = 25,
    ) -> int:
        if len(daily_changes) < lookback or len(daily_volumes) < lookback:
            return 0

        distribution_count = 0
        recent_changes = daily_changes[-lookback:]
        recent_volumes = daily_volumes[-lookback:]

        for i in range(1, len(recent_changes)):
            is_down_day = recent_changes[i] < Decimal("-0.002")
            higher_volume = recent_volumes[i] > recent_volumes[i - 1]

            if is_down_day and higher_volume:
                distribution_count += 1

        return distribution_count

    def detect_follow_through(
        self,
        daily_changes: list[Decimal],
        daily_volumes: list[int],
        rally_day: int = 4,
    ) -> bool:
        if len(daily_changes) < rally_day + 3:
            return False

        for i in range(3, len(daily_changes)):
            potential_low_idx = i - rally_day
            if potential_low_idx < 0:
                continue

            is_rally_attempt = all(
                daily_changes[j] > Decimal("-0.01")
                for j in range(potential_low_idx, min(potential_low_idx + 3, len(daily_changes)))
            )

            if not is_rally_attempt:
                continue

            if i < len(daily_changes):
                big_gain = daily_changes[i] >= Decimal("0.017")
                volume_increase = (
                    i > 0
                    and len(daily_volumes) > i
                    and daily_volumes[i] > daily_volumes[i - 1]
                )

                if big_gain and volume_increase:
                    return True

        return False
