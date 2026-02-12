"""Trading performance statistics calculator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from src.data.models import Position


@dataclass
class PerformanceStats:
    """Aggregated trading performance statistics."""

    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: Decimal = Decimal("0")

    total_pnl: Decimal = Decimal("0")
    avg_win_pct: Decimal = Decimal("0")
    avg_loss_pct: Decimal = Decimal("0")
    max_win_pct: Decimal = Decimal("0")
    max_loss_pct: Decimal = Decimal("0")

    avg_holding_days: float = 0.0
    max_holding_days: int = 0
    min_holding_days: int = 0

    profit_factor: Decimal = Decimal("0")

    open_positions: int = 0
    open_units: int = 0

    @property
    def loss_rate(self) -> Decimal:
        if self.total_trades == 0:
            return Decimal("0")
        return Decimal(str(self.loss_count)) / Decimal(str(self.total_trades))


class PerformanceTracker:
    """Calculate performance statistics from position history."""

    @staticmethod
    def calculate(
        closed_positions: Sequence[Position],
        open_positions: Sequence[Position] | None = None,
    ) -> PerformanceStats:
        stats = PerformanceStats()

        if open_positions:
            stats.open_positions = len(open_positions)
            stats.open_units = sum(p.units for p in open_positions)

        if not closed_positions:
            return stats

        stats.total_trades = len(closed_positions)

        wins: list[Decimal] = []
        losses: list[Decimal] = []
        holding_days: list[int] = []
        gross_profit = Decimal("0")
        gross_loss = Decimal("0")

        for pos in closed_positions:
            pnl_pct = pos.pnl_percent or Decimal("0")
            pnl_abs = pos.pnl or Decimal("0")

            if pnl_pct > 0:
                wins.append(pnl_pct)
                gross_profit += pnl_abs
            else:
                losses.append(pnl_pct)
                gross_loss += abs(pnl_abs)

            stats.total_pnl += pnl_abs

            if pos.entry_date and pos.exit_date:
                days = (pos.exit_date - pos.entry_date).days
                holding_days.append(max(days, 1))

        stats.win_count = len(wins)
        stats.loss_count = len(losses)

        if stats.total_trades > 0:
            stats.win_rate = Decimal(str(stats.win_count)) / Decimal(str(stats.total_trades))

        if wins:
            stats.avg_win_pct = sum(wins) / len(wins)
            stats.max_win_pct = max(wins)

        if losses:
            stats.avg_loss_pct = sum(losses) / len(losses)
            stats.max_loss_pct = min(losses)  # most negative

        if holding_days:
            stats.avg_holding_days = sum(holding_days) / len(holding_days)
            stats.max_holding_days = max(holding_days)
            stats.min_holding_days = min(holding_days)

        if gross_loss > 0:
            stats.profit_factor = gross_profit / gross_loss

        return stats

    @staticmethod
    def format_stats_summary(stats: PerformanceStats) -> str:
        """Format stats as human-readable Korean text."""
        lines = [
            "──── 전체 성과 ────",
            f"총 거래: {stats.total_trades}건 | "
            f"승률: {stats.win_rate:.1%} ({stats.win_count}승 {stats.loss_count}패)",
        ]

        if stats.win_count > 0:
            lines.append(f"평균 수익: {stats.avg_win_pct:+.2%} | 최대 수익: {stats.max_win_pct:+.2%}")
        if stats.loss_count > 0:
            lines.append(f"평균 손실: {stats.avg_loss_pct:+.2%} | 최대 손실: {stats.max_loss_pct:+.2%}")

        if stats.avg_holding_days > 0:
            lines.append(f"평균 보유: {stats.avg_holding_days:.1f}일 | 최장: {stats.max_holding_days}일")

        if stats.profit_factor > 0:
            lines.append(f"손익비: {stats.profit_factor:.2f}")

        if stats.open_positions > 0:
            lines.append(f"보유 중: {stats.open_positions}종목 ({stats.open_units} units)")

        return "\n".join(lines)
