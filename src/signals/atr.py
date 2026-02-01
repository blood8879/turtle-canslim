from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.core.config import TurtleConfig


@dataclass
class ATRResult:
    atr: Decimal
    atr_percent: Decimal
    true_ranges: list[Decimal]
    period: int


class ATRCalculator:
    def __init__(self, config: TurtleConfig | None = None, period: int | None = None):
        if config:
            self.period = config.atr_period
        elif period:
            self.period = period
        else:
            self.period = 20

    def calculate_true_range(
        self,
        high: Decimal,
        low: Decimal,
        previous_close: Decimal,
    ) -> Decimal:
        range1 = high - low
        range2 = abs(high - previous_close)
        range3 = abs(low - previous_close)

        return max(range1, range2, range3)

    def calculate(
        self,
        highs: list[Decimal],
        lows: list[Decimal],
        closes: list[Decimal],
    ) -> ATRResult | None:
        if len(highs) < self.period + 1 or len(lows) < self.period + 1 or len(closes) < self.period + 1:
            return None

        true_ranges: list[Decimal] = []

        for i in range(1, len(highs)):
            tr = self.calculate_true_range(highs[i], lows[i], closes[i - 1])
            true_ranges.append(tr)

        recent_trs = true_ranges[-self.period:]
        atr = sum(recent_trs) / len(recent_trs)

        current_price = closes[-1]
        atr_percent = (atr / current_price) * 100 if current_price > 0 else Decimal(0)

        return ATRResult(
            atr=atr,
            atr_percent=atr_percent,
            true_ranges=true_ranges,
            period=self.period,
        )

    def calculate_from_prices(
        self,
        prices: list[dict],
    ) -> ATRResult | None:
        if len(prices) < self.period + 1:
            return None

        highs = [Decimal(str(p["high"])) for p in prices]
        lows = [Decimal(str(p["low"])) for p in prices]
        closes = [Decimal(str(p["close"])) for p in prices]

        return self.calculate(highs, lows, closes)

    def calculate_n(
        self,
        highs: list[Decimal],
        lows: list[Decimal],
        closes: list[Decimal],
    ) -> Decimal | None:
        result = self.calculate(highs, lows, closes)
        return result.atr if result else None
