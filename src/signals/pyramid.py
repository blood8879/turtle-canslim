from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.core.config import TurtleConfig, RiskConfig


@dataclass
class PyramidLevel:
    level: int
    entry_price: Decimal
    stop_loss: Decimal
    quantity: int


@dataclass
class PyramidSignal:
    should_pyramid: bool
    next_entry_price: Decimal
    current_units: int
    max_units: int
    new_stop_loss: Decimal | None
    reason: str


class PyramidManager:
    def __init__(self, turtle_config: TurtleConfig, risk_config: RiskConfig):
        self.unit_interval = Decimal(str(turtle_config.pyramid_unit_interval))
        self.max_units_per_stock = risk_config.max_units_per_stock
        self.stop_loss_multiplier = Decimal(str(risk_config.stop_loss_atr_multiplier))

    def calculate_pyramid_levels(
        self,
        initial_entry: Decimal,
        atr_n: Decimal,
        max_units: int | None = None,
    ) -> list[PyramidLevel]:
        max_u = max_units or self.max_units_per_stock
        levels: list[PyramidLevel] = []

        for i in range(max_u):
            entry_price = initial_entry + (atr_n * self.unit_interval * i)
            stop_loss = entry_price - (atr_n * self.stop_loss_multiplier)

            levels.append(
                PyramidLevel(
                    level=i + 1,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    quantity=0,
                )
            )

        return levels

    def check_pyramid_signal(
        self,
        current_price: Decimal,
        initial_entry: Decimal,
        atr_n: Decimal,
        current_units: int,
        max_units: int | None = None,
    ) -> PyramidSignal:
        max_u = max_units or self.max_units_per_stock

        if current_units >= max_u:
            return PyramidSignal(
                should_pyramid=False,
                next_entry_price=Decimal(0),
                current_units=current_units,
                max_units=max_u,
                new_stop_loss=None,
                reason=f"Maximum units reached ({current_units}/{max_u})",
            )

        next_entry = initial_entry + (atr_n * self.unit_interval * current_units)

        should_pyramid = current_price >= next_entry

        new_stop_loss = None
        if should_pyramid:
            new_stop_loss = current_price - (atr_n * self.stop_loss_multiplier)

        if should_pyramid:
            reason = f"Price {current_price} >= pyramid level {next_entry}"
        else:
            reason = f"Price {current_price} < next pyramid level {next_entry}"

        return PyramidSignal(
            should_pyramid=should_pyramid,
            next_entry_price=next_entry,
            current_units=current_units,
            max_units=max_u,
            new_stop_loss=new_stop_loss,
            reason=reason,
        )

    def calculate_unified_stop_loss(
        self,
        pyramid_levels: list[PyramidLevel],
        atr_n: Decimal,
    ) -> Decimal:
        if not pyramid_levels:
            raise ValueError("No pyramid levels provided")

        last_entry = pyramid_levels[-1].entry_price
        return last_entry - (atr_n * self.stop_loss_multiplier)

    def get_average_entry_price(
        self,
        entries: list[tuple[Decimal, int]],
    ) -> Decimal:
        if not entries:
            raise ValueError("No entries provided")

        total_cost = sum(price * qty for price, qty in entries)
        total_qty = sum(qty for _, qty in entries)

        if total_qty == 0:
            raise ValueError("Total quantity is zero")

        return total_cost / total_qty
