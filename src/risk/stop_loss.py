from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from src.core.config import RiskConfig


class StopLossReason(str, Enum):
    ATR_2N = "2N"
    PERCENT_8 = "8%"
    TRAILING = "TRAILING"
    BREAKEVEN = "BREAKEVEN"


@dataclass
class StopLossResult:
    price: Decimal
    reason: StopLossReason
    distance: Decimal
    distance_percent: Decimal


class StopLossCalculator:
    def __init__(self, config: RiskConfig):
        self.atr_multiplier = Decimal(str(config.stop_loss_atr_multiplier))
        self.max_percent = Decimal(str(config.stop_loss_max_percent))

    def calculate_initial_stop(
        self,
        entry_price: Decimal,
        atr_n: Decimal,
    ) -> StopLossResult:
        stop_2n = entry_price - (self.atr_multiplier * atr_n)
        stop_percent = entry_price * (1 - self.max_percent)

        if stop_2n >= stop_percent:
            stop_price = stop_2n
            reason = StopLossReason.ATR_2N
        else:
            stop_price = stop_percent
            reason = StopLossReason.PERCENT_8

        distance = entry_price - stop_price
        distance_percent = distance / entry_price

        return StopLossResult(
            price=stop_price,
            reason=reason,
            distance=distance,
            distance_percent=distance_percent,
        )

    def calculate_trailing_stop(
        self,
        highest_price: Decimal,
        atr_n: Decimal,
        current_stop: Decimal,
    ) -> StopLossResult:
        trailing_stop = highest_price - (self.atr_multiplier * atr_n)

        if trailing_stop > current_stop:
            stop_price = trailing_stop
            reason = StopLossReason.TRAILING
        else:
            stop_price = current_stop
            reason = StopLossReason.ATR_2N

        distance = highest_price - stop_price
        distance_percent = distance / highest_price if highest_price > 0 else Decimal(0)

        return StopLossResult(
            price=stop_price,
            reason=reason,
            distance=distance,
            distance_percent=distance_percent,
        )

    def calculate_breakeven_stop(
        self,
        entry_price: Decimal,
        current_price: Decimal,
        atr_n: Decimal,
        breakeven_threshold: Decimal = Decimal("1.0"),
    ) -> StopLossResult | None:
        profit_in_atr = (current_price - entry_price) / atr_n if atr_n > 0 else Decimal(0)

        if profit_in_atr < breakeven_threshold:
            return None

        stop_price = entry_price
        distance = current_price - stop_price
        distance_percent = distance / current_price if current_price > 0 else Decimal(0)

        return StopLossResult(
            price=stop_price,
            reason=StopLossReason.BREAKEVEN,
            distance=distance,
            distance_percent=distance_percent,
        )

    def should_trigger_stop(
        self,
        current_price: Decimal,
        stop_price: Decimal,
    ) -> bool:
        return current_price <= stop_price

    def update_pyramid_stop(
        self,
        new_entry_price: Decimal,
        atr_n: Decimal,
    ) -> StopLossResult:
        return self.calculate_initial_stop(new_entry_price, atr_n)
