from __future__ import annotations

from decimal import Decimal

import pytest

from src.core.config import TurtleConfig, RiskConfig
from src.signals.atr import ATRCalculator
from src.signals.breakout import BreakoutDetector, BreakoutType
from src.signals.pyramid import PyramidManager


class TestATRCalculator:
    def setup_method(self) -> None:
        self.calc = ATRCalculator(period=20)

    def test_calculate_true_range(self) -> None:
        tr = self.calc.calculate_true_range(
            high=Decimal("52000"),
            low=Decimal("50000"),
            previous_close=Decimal("51000"),
        )

        assert tr == Decimal("2000")

    def test_calculate_true_range_gap_up(self) -> None:
        tr = self.calc.calculate_true_range(
            high=Decimal("55000"),
            low=Decimal("53000"),
            previous_close=Decimal("50000"),
        )

        assert tr == Decimal("5000")

    def test_calculate_true_range_gap_down(self) -> None:
        tr = self.calc.calculate_true_range(
            high=Decimal("48000"),
            low=Decimal("46000"),
            previous_close=Decimal("50000"),
        )

        assert tr == Decimal("4000")

    def test_calculate_atr(self) -> None:
        highs = [Decimal(str(50000 + i * 100)) for i in range(25)]
        lows = [Decimal(str(49000 + i * 100)) for i in range(25)]
        closes = [Decimal(str(49500 + i * 100)) for i in range(25)]

        result = self.calc.calculate(highs, lows, closes)

        assert result is not None
        assert result.atr > 0
        assert result.period == 20

    def test_insufficient_data(self) -> None:
        highs = [Decimal("50000")] * 10
        lows = [Decimal("49000")] * 10
        closes = [Decimal("49500")] * 10

        result = self.calc.calculate(highs, lows, closes)

        assert result is None


class TestBreakoutDetector:
    def setup_method(self) -> None:
        self.config = TurtleConfig()
        self.detector = BreakoutDetector(self.config)

    def test_system1_entry_breakout(self) -> None:
        highs = [Decimal(str(50000 + i * 50)) for i in range(25)]
        current_price = Decimal("60000")

        result = self.detector.check_entry(current_price, highs, previous_s1_winner=False)

        assert result.is_entry is True
        assert result.system == 1 or result.system == 2

    def test_system2_entry_breakout(self) -> None:
        highs = [Decimal(str(50000 + i * 30)) for i in range(60)]
        current_price = Decimal("60000")

        result = self.detector.check_entry(current_price, highs)

        assert result.is_entry is True
        assert result.system == 2

    def test_no_breakout(self) -> None:
        highs = [Decimal("50000")] * 25
        current_price = Decimal("48000")

        result = self.detector.check_entry(current_price, highs)

        assert result.is_entry is False
        assert result.breakout_type == BreakoutType.NONE

    def test_system1_exit(self) -> None:
        lows = [Decimal(str(50000 - i * 50)) for i in range(15)]
        current_price = Decimal("48000")

        result = self.detector.check_exit(current_price, lows, entry_system=1)

        assert result.is_exit is True
        assert result.system == 1

    def test_system2_exit(self) -> None:
        lows = [Decimal(str(50000 - i * 30)) for i in range(25)]
        current_price = Decimal("48000")

        result = self.detector.check_exit(current_price, lows, entry_system=2)

        assert result.is_exit is True
        assert result.system == 2

    def test_no_exit(self) -> None:
        lows = [Decimal("48000")] * 15
        current_price = Decimal("50000")

        result = self.detector.check_exit(current_price, lows, entry_system=1)

        assert result.is_exit is False

    def test_get_entry_levels(self) -> None:
        highs = [Decimal(str(50000 + i * 100)) for i in range(60)]

        levels = self.detector.get_entry_levels(highs)

        assert "s1_entry" in levels
        assert "s2_entry" in levels
        assert levels["s2_entry"] >= levels["s1_entry"]


class TestPyramidManager:
    def setup_method(self) -> None:
        self.turtle_config = TurtleConfig()
        self.risk_config = RiskConfig()
        self.pyramid = PyramidManager(self.turtle_config, self.risk_config)

    def test_calculate_pyramid_levels(self) -> None:
        levels = self.pyramid.calculate_pyramid_levels(
            initial_entry=Decimal("50000"),
            atr_n=Decimal("1000"),
        )

        assert len(levels) == 4
        assert levels[0].entry_price == Decimal("50000")
        assert levels[1].entry_price == Decimal("50500")
        assert levels[2].entry_price == Decimal("51000")
        assert levels[3].entry_price == Decimal("51500")

    def test_pyramid_signal_should_add(self) -> None:
        signal = self.pyramid.check_pyramid_signal(
            current_price=Decimal("50600"),
            initial_entry=Decimal("50000"),
            atr_n=Decimal("1000"),
            current_units=1,
        )

        assert signal.should_pyramid is True
        assert signal.new_stop_loss is not None

    def test_pyramid_signal_max_units(self) -> None:
        signal = self.pyramid.check_pyramid_signal(
            current_price=Decimal("52000"),
            initial_entry=Decimal("50000"),
            atr_n=Decimal("1000"),
            current_units=4,
        )

        assert signal.should_pyramid is False
        assert "Maximum units" in signal.reason

    def test_pyramid_signal_price_not_reached(self) -> None:
        signal = self.pyramid.check_pyramid_signal(
            current_price=Decimal("50200"),
            initial_entry=Decimal("50000"),
            atr_n=Decimal("1000"),
            current_units=1,
        )

        assert signal.should_pyramid is False

    def test_unified_stop_loss(self) -> None:
        levels = self.pyramid.calculate_pyramid_levels(
            initial_entry=Decimal("50000"),
            atr_n=Decimal("1000"),
        )

        stop_loss = self.pyramid.calculate_unified_stop_loss(levels, Decimal("1000"))

        assert stop_loss == Decimal("49500")

    def test_average_entry_price(self) -> None:
        entries = [
            (Decimal("50000"), 100),
            (Decimal("50500"), 100),
            (Decimal("51000"), 100),
        ]

        avg = self.pyramid.get_average_entry_price(entries)

        assert avg == Decimal("50500")


class TestBreakoutRealtimeSlice:
    def setup_method(self) -> None:
        self.config = TurtleConfig()
        self.detector = BreakoutDetector(self.config)

    def test_entry_with_realtime_appended(self) -> None:
        highs = [Decimal(str(50000 + i * 50)) for i in range(25)]
        realtime_price = Decimal("60000")
        highs_with_rt = highs + [realtime_price]

        result = self.detector.check_entry(realtime_price, highs_with_rt, previous_s1_winner=False)

        assert result.is_entry is True

    def test_entry_correct_window_with_appended_price(self) -> None:
        highs = [Decimal(str(50000 + i * 50)) for i in range(25)]
        s1_high_correct = max(highs[-20:])
        current_price = s1_high_correct + Decimal("1")

        result = self.detector.check_entry(
            current_price, highs + [current_price], previous_s1_winner=False,
        )
        assert result.is_entry is True

    def test_proximity_with_realtime_appended(self) -> None:
        highs = [Decimal("50000")] * 25
        realtime_price = Decimal("49800")
        highs_with_rt = highs + [realtime_price]

        targets = self.detector.check_proximity(
            realtime_price,
            highs_with_rt,
            Decimal("0.05"),
            previous_s1_winner=False,
        )

        assert len(targets) > 0
        assert targets[0].system in (1, 2)


class TestPreviousS1WinnerDefault:
    def setup_method(self) -> None:
        self.config = TurtleConfig()
        self.detector = BreakoutDetector(self.config)

    def test_s1_allowed_when_previous_was_loss(self) -> None:
        highs = [Decimal(str(50000 + i * 50)) for i in range(25)]
        current_price = Decimal("60000")

        result = self.detector.check_entry(current_price, highs, previous_s1_winner=False)
        assert result.is_entry is True

    def test_s1_blocked_when_previous_was_winner(self) -> None:
        highs = [Decimal(str(50000 + i * 50)) for i in range(25)]
        current_price = Decimal("51300")

        result = self.detector.check_entry(current_price, highs, previous_s1_winner=True)
        assert result.is_entry is False or result.system == 2

    def test_s2_always_allowed_regardless_of_s1_winner(self) -> None:
        highs = [Decimal(str(50000 + i * 30)) for i in range(60)]
        current_price = Decimal("60000")

        result = self.detector.check_entry(current_price, highs, previous_s1_winner=True)
        assert result.is_entry is True
        assert result.system == 2
