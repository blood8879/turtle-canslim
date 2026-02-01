from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.core.config import RiskConfig
from src.core.exceptions import UnitLimitExceededError

if TYPE_CHECKING:
    from src.data.repositories import PositionRepository


@dataclass
class UnitStatus:
    total_units: int
    available_units: int
    max_units_total: int
    stock_units: dict[int, int]
    sector_units: dict[str, int]


@dataclass
class UnitCheckResult:
    can_add: bool
    reason: str
    current_units: int
    limit: int


class UnitLimitManager:
    def __init__(self, config: RiskConfig, position_repo: PositionRepository):
        self.max_units_per_stock = config.max_units_per_stock
        self.max_units_correlated = config.max_units_correlated
        self.max_units_loosely_correlated = config.max_units_loosely_correlated
        self.max_units_total = config.max_units_total
        self._position_repo = position_repo

    async def get_unit_status(self) -> UnitStatus:
        positions = await self._position_repo.get_open_positions()

        total_units = sum(p.units for p in positions)

        stock_units: dict[int, int] = {}
        sector_units: dict[str, int] = {}

        for position in positions:
            stock_id = position.stock_id
            stock_units[stock_id] = stock_units.get(stock_id, 0) + position.units

        return UnitStatus(
            total_units=total_units,
            available_units=self.max_units_total - total_units,
            max_units_total=self.max_units_total,
            stock_units=stock_units,
            sector_units=sector_units,
        )

    async def get_current_units(self) -> int:
        status = await self.get_unit_status()
        return status.total_units

    async def get_available_units(self) -> int:
        status = await self.get_unit_status()
        return status.available_units

    async def get_stock_units(self, stock_id: int) -> int:
        return await self._position_repo.get_stock_units(stock_id)

    async def can_add_unit(
        self,
        stock_id: int,
        sector: str | None = None,
    ) -> UnitCheckResult:
        status = await self.get_unit_status()

        if status.available_units <= 0:
            return UnitCheckResult(
                can_add=False,
                reason=f"Total unit limit reached ({status.total_units}/{self.max_units_total})",
                current_units=status.total_units,
                limit=self.max_units_total,
            )

        stock_units = status.stock_units.get(stock_id, 0)
        if stock_units >= self.max_units_per_stock:
            return UnitCheckResult(
                can_add=False,
                reason=f"Stock unit limit reached ({stock_units}/{self.max_units_per_stock})",
                current_units=stock_units,
                limit=self.max_units_per_stock,
            )

        if sector:
            sector_units = status.sector_units.get(sector, 0)
            if sector_units >= self.max_units_correlated:
                return UnitCheckResult(
                    can_add=False,
                    reason=f"Sector unit limit reached ({sector_units}/{self.max_units_correlated})",
                    current_units=sector_units,
                    limit=self.max_units_correlated,
                )

        return UnitCheckResult(
            can_add=True,
            reason="Unit can be added",
            current_units=stock_units,
            limit=self.max_units_per_stock,
        )

    async def validate_and_add_unit(
        self,
        stock_id: int,
        sector: str | None = None,
    ) -> None:
        check = await self.can_add_unit(stock_id, sector)

        if not check.can_add:
            raise UnitLimitExceededError(
                limit_type="unit",
                current=check.current_units,
                maximum=check.limit,
            )

    def calculate_max_positions(self) -> int:
        return self.max_units_total // self.max_units_per_stock

    def calculate_sector_capacity(self, current_sector_units: int) -> int:
        return max(0, self.max_units_correlated - current_sector_units)
