from __future__ import annotations

from decimal import Decimal

import pytest

from src.core.config import RiskConfig
from src.risk.position_sizing import PositionSizer
from src.risk.stop_loss import StopLossCalculator, StopLossReason


class TestPositionSizer:
    def setup_method(self) -> None:
        self.config = RiskConfig()
        self.sizer = PositionSizer(self.config)

    def test_stop_loss_2n_tighter(self) -> None:
        stop, stop_type = self.sizer.calculate_stop_loss(
            entry_price=Decimal("50000"),
            atr_n=Decimal("1500"),
        )

        assert stop == Decimal("47000")
        assert stop_type == "2N"

    def test_stop_loss_8pct_tighter(self) -> None:
        stop, stop_type = self.sizer.calculate_stop_loss(
            entry_price=Decimal("50000"),
            atr_n=Decimal("3000"),
        )

        assert stop == Decimal("46000")
        assert stop_type == "8%"

    def test_position_size_calculation(self) -> None:
        size = self.sizer.calculate_position_size(
            account_value=Decimal("100000000"),
            entry_price=Decimal("50000"),
            stop_loss_price=Decimal("46000"),
        )

        assert size == 500

    def test_full_position_calculation(self) -> None:
        result = self.sizer.calculate_full_position(
            account_value=Decimal("100000000"),
            entry_price=Decimal("50000"),
            atr_n=Decimal("1500"),
        )

        assert result.quantity > 0
        assert result.stop_loss_price == Decimal("47000")
        assert result.stop_loss_type == "2N"
        assert result.risk_amount <= Decimal("2000000")

    def test_invalid_stop_loss_raises(self) -> None:
        with pytest.raises(ValueError):
            self.sizer.calculate_position_size(
                account_value=Decimal("100000000"),
                entry_price=Decimal("50000"),
                stop_loss_price=Decimal("55000"),
            )


class TestStopLossCalculator:
    def setup_method(self) -> None:
        self.config = RiskConfig()
        self.calc = StopLossCalculator(self.config)

    def test_initial_stop_2n(self) -> None:
        result = self.calc.calculate_initial_stop(
            entry_price=Decimal("50000"),
            atr_n=Decimal("1500"),
        )

        assert result.price == Decimal("47000")
        assert result.reason == StopLossReason.ATR_2N

    def test_initial_stop_8pct(self) -> None:
        result = self.calc.calculate_initial_stop(
            entry_price=Decimal("50000"),
            atr_n=Decimal("3000"),
        )

        assert result.price == Decimal("46000")
        assert result.reason == StopLossReason.PERCENT_8

    def test_trailing_stop_raised(self) -> None:
        result = self.calc.calculate_trailing_stop(
            highest_price=Decimal("55000"),
            atr_n=Decimal("1500"),
            current_stop=Decimal("47000"),
        )

        assert result.price == Decimal("52000")
        assert result.reason == StopLossReason.TRAILING

    def test_trailing_stop_not_lowered(self) -> None:
        result = self.calc.calculate_trailing_stop(
            highest_price=Decimal("51000"),
            atr_n=Decimal("1500"),
            current_stop=Decimal("48500"),
        )

        assert result.price == Decimal("48500")
        assert result.reason == StopLossReason.ATR_2N

    def test_breakeven_stop(self) -> None:
        result = self.calc.calculate_breakeven_stop(
            entry_price=Decimal("50000"),
            current_price=Decimal("52000"),
            atr_n=Decimal("1500"),
        )

        assert result is not None
        assert result.price == Decimal("50000")
        assert result.reason == StopLossReason.BREAKEVEN

    def test_breakeven_stop_not_triggered(self) -> None:
        result = self.calc.calculate_breakeven_stop(
            entry_price=Decimal("50000"),
            current_price=Decimal("50500"),
            atr_n=Decimal("1500"),
        )

        assert result is None

    def test_should_trigger_stop(self) -> None:
        assert self.calc.should_trigger_stop(Decimal("46000"), Decimal("47000")) is True
        assert self.calc.should_trigger_stop(Decimal("48000"), Decimal("47000")) is False
