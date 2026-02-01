from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.core.logger import get_logger

if TYPE_CHECKING:
    from src.data.repositories import PositionRepository
    from src.execution.broker_interface import BrokerInterface

logger = get_logger(__name__)


@dataclass
class PortfolioPosition:
    symbol: str
    stock_id: int
    quantity: int
    units: int
    entry_price: Decimal
    entry_date: datetime
    entry_system: int | None
    current_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: Decimal
    stop_loss_price: Decimal | None
    distance_to_stop: Decimal | None


@dataclass
class PortfolioSummary:
    total_value: Decimal
    cash_balance: Decimal
    securities_value: Decimal
    total_unrealized_pnl: Decimal
    total_unrealized_pnl_pct: Decimal
    total_units: int
    available_units: int
    max_units: int
    position_count: int
    positions: list[PortfolioPosition]


@dataclass
class PortfolioRisk:
    total_risk_amount: Decimal
    total_risk_pct: Decimal
    max_drawdown_potential: Decimal
    positions_at_risk: int


class PortfolioManager:
    def __init__(
        self,
        broker: BrokerInterface,
        position_repo: PositionRepository,
        max_units: int = 20,
    ):
        self._broker = broker
        self._position_repo = position_repo
        self._max_units = max_units

    async def get_summary(self) -> PortfolioSummary:
        balance = await self._broker.get_balance()
        db_positions = await self._position_repo.get_open_positions()

        positions: list[PortfolioPosition] = []
        total_unrealized_pnl = Decimal("0")
        securities_value = Decimal("0")
        total_units = 0

        for db_pos in db_positions:
            try:
                current_price = await self._broker.get_current_price(str(db_pos.stock_id))
            except Exception:
                current_price = db_pos.entry_price

            market_value = current_price * db_pos.quantity
            cost_basis = db_pos.entry_price * db_pos.quantity
            unrealized_pnl = market_value - cost_basis
            unrealized_pnl_pct = (
                (unrealized_pnl / cost_basis) if cost_basis > 0 else Decimal("0")
            )

            distance_to_stop = None
            if db_pos.stop_loss_price:
                distance_to_stop = (current_price - db_pos.stop_loss_price) / current_price

            positions.append(
                PortfolioPosition(
                    symbol=str(db_pos.stock_id),
                    stock_id=db_pos.stock_id,
                    quantity=db_pos.quantity,
                    units=db_pos.units,
                    entry_price=db_pos.entry_price,
                    entry_date=db_pos.entry_date,
                    entry_system=db_pos.entry_system,
                    current_price=current_price,
                    market_value=market_value,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_pct=unrealized_pnl_pct,
                    stop_loss_price=db_pos.stop_loss_price,
                    distance_to_stop=distance_to_stop,
                )
            )

            total_unrealized_pnl += unrealized_pnl
            securities_value += market_value
            total_units += db_pos.units

        total_value = balance.cash_balance + securities_value
        total_unrealized_pnl_pct = (
            (total_unrealized_pnl / (total_value - total_unrealized_pnl))
            if (total_value - total_unrealized_pnl) > 0
            else Decimal("0")
        )

        return PortfolioSummary(
            total_value=total_value,
            cash_balance=balance.cash_balance,
            securities_value=securities_value,
            total_unrealized_pnl=total_unrealized_pnl,
            total_unrealized_pnl_pct=total_unrealized_pnl_pct,
            total_units=total_units,
            available_units=self._max_units - total_units,
            max_units=self._max_units,
            position_count=len(positions),
            positions=positions,
        )

    async def get_risk_analysis(self) -> PortfolioRisk:
        summary = await self.get_summary()

        total_risk_amount = Decimal("0")
        positions_at_risk = 0

        for pos in summary.positions:
            if pos.stop_loss_price:
                risk = (pos.current_price - pos.stop_loss_price) * pos.quantity
                total_risk_amount += risk

                if pos.distance_to_stop and pos.distance_to_stop < Decimal("0.05"):
                    positions_at_risk += 1

        total_risk_pct = (
            (total_risk_amount / summary.total_value)
            if summary.total_value > 0
            else Decimal("0")
        )

        max_drawdown = total_risk_amount + abs(
            min(Decimal("0"), summary.total_unrealized_pnl)
        )

        return PortfolioRisk(
            total_risk_amount=total_risk_amount,
            total_risk_pct=total_risk_pct,
            max_drawdown_potential=max_drawdown,
            positions_at_risk=positions_at_risk,
        )

    async def get_position_by_symbol(self, symbol: str) -> PortfolioPosition | None:
        summary = await self.get_summary()
        for pos in summary.positions:
            if pos.symbol == symbol:
                return pos
        return None

    async def check_stop_losses(self) -> list[PortfolioPosition]:
        summary = await self.get_summary()
        triggered: list[PortfolioPosition] = []

        for pos in summary.positions:
            if pos.stop_loss_price and pos.current_price <= pos.stop_loss_price:
                triggered.append(pos)
                logger.warning(
                    "stop_loss_triggered",
                    symbol=pos.symbol,
                    current_price=float(pos.current_price),
                    stop_loss=float(pos.stop_loss_price),
                )

        return triggered

    def format_summary(self, summary: PortfolioSummary) -> str:
        lines = [
            "=" * 60,
            "PORTFOLIO SUMMARY",
            "=" * 60,
            f"Total Value:      {summary.total_value:>15,.0f}",
            f"Cash Balance:     {summary.cash_balance:>15,.0f}",
            f"Securities:       {summary.securities_value:>15,.0f}",
            f"Unrealized P&L:   {summary.total_unrealized_pnl:>+15,.0f} ({summary.total_unrealized_pnl_pct:+.2%})",
            f"Units:            {summary.total_units:>15d} / {summary.max_units}",
            f"Positions:        {summary.position_count:>15d}",
            "-" * 60,
        ]

        if summary.positions:
            lines.append(f"{'Symbol':<10} {'Qty':>8} {'Entry':>10} {'Current':>10} {'P&L%':>8}")
            lines.append("-" * 60)

            for pos in summary.positions:
                lines.append(
                    f"{pos.symbol:<10} {pos.quantity:>8} {pos.entry_price:>10,.0f} "
                    f"{pos.current_price:>10,.0f} {pos.unrealized_pnl_pct:>+7.2%}"
                )

        lines.append("=" * 60)
        return "\n".join(lines)
