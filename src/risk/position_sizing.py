from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.core.config import RiskConfig


@dataclass
class PositionSizeResult:
    quantity: int
    position_value: Decimal
    risk_amount: Decimal
    risk_per_share: Decimal
    stop_loss_price: Decimal
    stop_loss_type: str


class PositionSizer:
    def __init__(self, config: RiskConfig):
        self.risk_per_unit = Decimal(str(config.risk_per_unit))
        self.stop_loss_atr_multiplier = Decimal(str(config.stop_loss_atr_multiplier))
        self.stop_loss_max_percent = Decimal(str(config.stop_loss_max_percent))

    def calculate_stop_loss(
        self,
        entry_price: Decimal,
        atr_n: Decimal,
    ) -> tuple[Decimal, str]:
        stop_2n = entry_price - (self.stop_loss_atr_multiplier * atr_n)
        stop_percent = entry_price * (1 - self.stop_loss_max_percent)

        if stop_2n >= stop_percent:
            return stop_2n, "2N"
        return stop_percent, "8%"

    def calculate_position_size(
        self,
        account_value: Decimal,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        min_quantity: int = 1,
    ) -> int:
        if entry_price <= 0:
            raise ValueError("Entry price must be positive")

        if stop_loss_price >= entry_price:
            raise ValueError("Stop loss must be below entry price")

        max_risk = account_value * self.risk_per_unit
        risk_per_share = entry_price - stop_loss_price

        if risk_per_share <= 0:
            raise ValueError("Risk per share must be positive")

        quantity = int(max_risk / risk_per_share)

        return max(quantity, min_quantity)

    def calculate_full_position(
        self,
        account_value: Decimal,
        entry_price: Decimal,
        atr_n: Decimal,
    ) -> PositionSizeResult:
        stop_loss, stop_type = self.calculate_stop_loss(entry_price, atr_n)
        quantity = self.calculate_position_size(account_value, entry_price, stop_loss)

        position_value = entry_price * quantity
        risk_per_share = entry_price - stop_loss
        risk_amount = risk_per_share * quantity

        return PositionSizeResult(
            quantity=quantity,
            position_value=position_value,
            risk_amount=risk_amount,
            risk_per_share=risk_per_share,
            stop_loss_price=stop_loss,
            stop_loss_type=stop_type,
        )

    def calculate_dollar_cost_position(
        self,
        target_amount: Decimal,
        entry_price: Decimal,
    ) -> int:
        if entry_price <= 0:
            raise ValueError("Entry price must be positive")

        return int(target_amount / entry_price)

    def validate_position(
        self,
        account_value: Decimal,
        position_value: Decimal,
        max_position_pct: Decimal = Decimal("0.20"),
    ) -> bool:
        max_allowed = account_value * max_position_pct
        return position_value <= max_allowed
