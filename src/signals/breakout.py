from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from src.core.config import TurtleConfig


class BreakoutType(str, Enum):
    ENTRY_S1 = "ENTRY_S1"
    ENTRY_S2 = "ENTRY_S2"
    EXIT_S1 = "EXIT_S1"
    EXIT_S2 = "EXIT_S2"
    NONE = "NONE"


@dataclass
class BreakoutResult:
    breakout_type: BreakoutType
    price: Decimal
    breakout_level: Decimal | None
    system: int | None
    is_entry: bool
    is_exit: bool


class BreakoutDetector:
    def __init__(self, config: TurtleConfig):
        self.s1_entry_period = config.system1_entry_period
        self.s1_exit_period = config.system1_exit_period
        self.s2_entry_period = config.system2_entry_period
        self.s2_exit_period = config.system2_exit_period

    def get_high_low(
        self,
        prices: list[Decimal],
        period: int,
    ) -> tuple[Decimal, Decimal]:
        if len(prices) < period:
            period = len(prices)

        recent = prices[-period:]
        return max(recent), min(recent)

    def check_entry(
        self,
        current_price: Decimal,
        highs: list[Decimal],
        previous_s1_winner: bool = True,
    ) -> BreakoutResult:
        s1_high, _ = self.get_high_low(highs[:-1], self.s1_entry_period)
        s2_high, _ = self.get_high_low(highs[:-1], self.s2_entry_period)

        if current_price > s2_high:
            return BreakoutResult(
                breakout_type=BreakoutType.ENTRY_S2,
                price=current_price,
                breakout_level=s2_high,
                system=2,
                is_entry=True,
                is_exit=False,
            )

        if current_price > s1_high:
            if not previous_s1_winner:
                return BreakoutResult(
                    breakout_type=BreakoutType.ENTRY_S1,
                    price=current_price,
                    breakout_level=s1_high,
                    system=1,
                    is_entry=True,
                    is_exit=False,
                )

        return BreakoutResult(
            breakout_type=BreakoutType.NONE,
            price=current_price,
            breakout_level=None,
            system=None,
            is_entry=False,
            is_exit=False,
        )

    def check_exit(
        self,
        current_price: Decimal,
        lows: list[Decimal],
        entry_system: int,
    ) -> BreakoutResult:
        if entry_system == 1:
            exit_period = self.s1_exit_period
            exit_type = BreakoutType.EXIT_S1
        else:
            exit_period = self.s2_exit_period
            exit_type = BreakoutType.EXIT_S2

        _, period_low = self.get_high_low(lows[:-1], exit_period)

        if current_price < period_low:
            return BreakoutResult(
                breakout_type=exit_type,
                price=current_price,
                breakout_level=period_low,
                system=entry_system,
                is_entry=False,
                is_exit=True,
            )

        return BreakoutResult(
            breakout_type=BreakoutType.NONE,
            price=current_price,
            breakout_level=None,
            system=entry_system,
            is_entry=False,
            is_exit=False,
        )

    def get_entry_levels(
        self,
        highs: list[Decimal],
    ) -> dict[str, Decimal]:
        s1_high, _ = self.get_high_low(highs, self.s1_entry_period)
        s2_high, _ = self.get_high_low(highs, self.s2_entry_period)

        return {
            "s1_entry": s1_high,
            "s2_entry": s2_high,
        }

    def get_exit_levels(
        self,
        lows: list[Decimal],
    ) -> dict[str, Decimal]:
        _, s1_low = self.get_high_low(lows, self.s1_exit_period)
        _, s2_low = self.get_high_low(lows, self.s2_exit_period)

        return {
            "s1_exit": s1_low,
            "s2_exit": s2_low,
        }
