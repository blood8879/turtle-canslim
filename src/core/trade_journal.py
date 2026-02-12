from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.execution.performance import PerformanceStats

JOURNAL_LOG_DIR = Path("logs")
JOURNAL_LOG_FILE = JOURNAL_LOG_DIR / "trade_journal.log"
JOURNAL_MAX_BYTES = 10 * 1024 * 1024
JOURNAL_BACKUP_COUNT = 30

_SEP = "\u2501" * 50
_THIN_SEP = "\u2500" * 50

_journal_logger: logging.Logger | None = None


def _get_journal_logger() -> logging.Logger:
    global _journal_logger
    if _journal_logger is not None:
        return _journal_logger

    JOURNAL_LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("trade_journal")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    handler = RotatingFileHandler(
        JOURNAL_LOG_FILE,
        maxBytes=JOURNAL_MAX_BYTES,
        backupCount=JOURNAL_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)

    _journal_logger = logger
    return logger


def _fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y%m%d %H:%M:%S")


def _fmt_price(price: Decimal, market: str = "") -> str:
    is_us = market.upper() in ("NYSE", "NASDAQ", "US")
    if is_us:
        return f"${price:,.2f}"
    return f"{price:,.0f}원"


def _fmt_system(system: int | None) -> str:
    if system == 1:
        return "S1 (20일 돌파)"
    elif system == 2:
        return "S2 (55일 돌파)"
    return f"S{system}" if system else "N/A"


class TradeJournal:

    def __init__(self) -> None:
        self._logger = _get_journal_logger()

    def log_entry(
        self,
        *,
        timestamp: datetime,
        symbol: str,
        name: str,
        market: str,
        system: int | None,
        entry_price: Decimal,
        breakout_level: Decimal | None,
        quantity: int,
        position_value: Decimal | None = None,
        stop_loss: Decimal | None = None,
        stop_loss_type: str | None = None,
        risk_pct: Decimal | None = None,
    ) -> str:
        pos_val = position_value or (entry_price * quantity)
        risk_str = f" | 리스크: {risk_pct:+.2%}" if risk_pct else ""
        sl_str = ""
        if stop_loss:
            sl_type = f" ({stop_loss_type})" if stop_loss_type else ""
            sl_str = f"\n손절가: {_fmt_price(stop_loss, market)}{sl_type}{risk_str}"

        bl_str = ""
        if breakout_level:
            bl_str = f" | 돌파 레벨: {_fmt_price(breakout_level, market)}"

        entry = (
            f"\n{_SEP}\n"
            f"[진입] {_fmt_ts(timestamp)} | {symbol} ({name})\n"
            f"시스템: {_fmt_system(system)} | 시장: {market}\n"
            f"진입가: {_fmt_price(entry_price, market)}{bl_str}\n"
            f"수량: {quantity:,}주 | 포지션: {_fmt_price(pos_val, market)}"
            f"{sl_str}\n"
            f"{_SEP}"
        )
        self._logger.info(entry)
        return entry

    def log_exit(
        self,
        *,
        timestamp: datetime,
        symbol: str,
        name: str,
        market: str,
        exit_reason: str,
        entry_price: Decimal,
        exit_price: Decimal,
        quantity: int,
        pnl: Decimal,
        pnl_percent: Decimal,
        holding_days: int,
        stats: PerformanceStats | None = None,
    ) -> str:
        pnl_str = _fmt_price(abs(pnl), market)
        sign = "+" if pnl >= 0 else "-"

        lines = [
            f"\n{_SEP}",
            f"[청산] {_fmt_ts(timestamp)} | {symbol} ({name})",
            f"청산 사유: {exit_reason} | 보유기간: {holding_days}일",
            f"진입가: {_fmt_price(entry_price, market)} → 청산가: {_fmt_price(exit_price, market)}",
            f"손익: {sign}{pnl_str} ({pnl_percent:+.2%})",
        ]

        if stats and stats.total_trades > 0:
            lines.append(_THIN_SEP)
            lines.append(
                f"전체: {stats.total_trades}건 | "
                f"승률: {stats.win_rate:.1%} ({stats.win_count}승 {stats.loss_count}패)"
            )

        lines.append(_SEP)
        entry = "\n".join(lines)
        self._logger.info(entry)
        return entry

    def log_pyramid(
        self,
        *,
        timestamp: datetime,
        symbol: str,
        name: str,
        market: str,
        price: Decimal,
        additional_qty: int,
        new_units: int,
        avg_entry_price: Decimal | None = None,
    ) -> str:
        avg_str = ""
        if avg_entry_price:
            avg_str = f"\n평균 진입가: {_fmt_price(avg_entry_price, market)}"

        entry = (
            f"\n{_SEP}\n"
            f"[증설] {_fmt_ts(timestamp)} | {symbol} ({name})\n"
            f"추가 매수가: {_fmt_price(price, market)} | 수량: {additional_qty:,}주\n"
            f"현재 유닛: {new_units}"
            f"{avg_str}\n"
            f"{_SEP}"
        )
        self._logger.info(entry)
        return entry

    def log_daily_summary(self, stats: PerformanceStats, date: datetime | None = None) -> str:
        dt = date or datetime.now()
        from src.execution.performance import PerformanceTracker

        lines = [
            f"\n{'=' * 50}",
            f"[일일 성과 리포트] {dt.strftime('%Y-%m-%d')}",
            "=" * 50,
            PerformanceTracker.format_stats_summary(stats),
            "=" * 50,
        ]
        entry = "\n".join(lines)
        self._logger.info(entry)
        return entry
