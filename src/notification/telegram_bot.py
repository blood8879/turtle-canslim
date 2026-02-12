from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from src.core.config import Settings, get_settings
from src.core.exceptions import NotificationError
from src.core.logger import get_logger

if TYPE_CHECKING:
    from telegram import Bot

logger = get_logger(__name__)


@dataclass
class SignalNotification:
    symbol: str
    signal_type: str
    price: Decimal
    atr_n: Decimal | None
    stop_loss: Decimal | None
    system: int | None


@dataclass
class OrderNotification:
    symbol: str
    side: str
    quantity: int
    price: Decimal
    order_id: str | None
    success: bool
    message: str


@dataclass
class ExitNotification:
    symbol: str
    name: str
    exit_reason: str
    entry_price: Decimal
    exit_price: Decimal
    quantity: int
    pnl: Decimal
    pnl_percent: Decimal
    holding_days: int
    win_rate: Decimal | None = None
    total_trades: int | None = None


@dataclass
class DailyReport:
    date: str
    total_value: Decimal
    daily_pnl: Decimal
    daily_pnl_pct: Decimal
    open_positions: int
    total_units: int
    signals_generated: int
    orders_executed: int
    win_rate: Decimal | None = None
    total_closed_trades: int | None = None
    win_count: int | None = None
    loss_count: int | None = None
    avg_holding_days: float | None = None
    profit_factor: Decimal | None = None


class TelegramNotifier:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._bot: Bot | None = None
        self._enabled = self._settings.notification.telegram_enabled

    @property
    def is_enabled(self) -> bool:
        return self._enabled and bool(self._settings.telegram_bot_token)

    @property
    def bot(self) -> Bot:
        if self._bot is None:
            self._bot = self._create_bot()
        return self._bot

    def _create_bot(self) -> Bot:
        from telegram import Bot

        if not self._settings.telegram_bot_token:
            raise NotificationError("Telegram bot token not configured")

        return Bot(token=self._settings.telegram_bot_token)

    @property
    def chat_id(self) -> str:
        if not self._settings.telegram_chat_id:
            raise NotificationError("Telegram chat ID not configured")
        return self._settings.telegram_chat_id

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self.is_enabled:
            logger.debug("telegram_disabled", message=text[:50])
            return False

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
            )
            logger.info("telegram_message_sent", length=len(text))
            return True
        except Exception as e:
            logger.error("telegram_send_error", error=str(e))
            return False

    async def notify_signal(self, signal: SignalNotification) -> bool:
        if not self._settings.notification.notify_on_signal:
            return False

        emoji = self._get_signal_emoji(signal.signal_type)
        system_str = f"S{signal.system}" if signal.system else ""

        message = f"""
{emoji} <b>Signal: {signal.signal_type}</b> {system_str}

<b>Symbol:</b> {signal.symbol}
<b>Price:</b> {signal.price:,.2f}
"""
        if signal.atr_n:
            message += f"<b>ATR(N):</b> {signal.atr_n:,.2f}\n"
        if signal.stop_loss:
            message += f"<b>Stop Loss:</b> {signal.stop_loss:,.2f}\n"

        return await self.send_message(message.strip())

    async def notify_order(self, order: OrderNotification) -> bool:
        if not self._settings.notification.notify_on_order:
            return False

        emoji = "✅" if order.success else "❌"
        side_emoji = "🟢" if order.side == "BUY" else "🔴"

        message = f"""
{emoji} <b>Order {order.side}</b> {side_emoji}

<b>Symbol:</b> {order.symbol}
<b>Quantity:</b> {order.quantity:,}
<b>Price:</b> {order.price:,.2f}
<b>Status:</b> {"Filled" if order.success else "Failed"}
"""
        if order.order_id:
            message += f"<b>Order ID:</b> {order.order_id}\n"
        if not order.success:
            message += f"<b>Error:</b> {order.message}\n"

        return await self.send_message(message.strip())

    async def notify_fill(self, order: OrderNotification) -> bool:
        if not self._settings.notification.notify_on_fill:
            return False

        return await self.notify_order(order)

    async def notify_exit(self, exit_info: ExitNotification) -> bool:
        if not self._settings.notification.notify_on_order:
            return False

        pnl_emoji = "💰" if exit_info.pnl >= 0 else "💸"
        sign = "+" if exit_info.pnl >= 0 else ""

        message = (
            f"{pnl_emoji} <b>포지션 청산</b>\n\n"
            f"<b>종목:</b> {exit_info.symbol} ({exit_info.name})\n"
            f"<b>사유:</b> {exit_info.exit_reason}\n"
            f"<b>진입:</b> {exit_info.entry_price:,.2f} → <b>청산:</b> {exit_info.exit_price:,.2f}\n"
            f"<b>수량:</b> {exit_info.quantity:,}\n"
            f"<b>손익:</b> {sign}{exit_info.pnl:,.0f} ({exit_info.pnl_percent:+.2%})\n"
            f"<b>보유기간:</b> {exit_info.holding_days}일"
        )

        if exit_info.win_rate is not None and exit_info.total_trades is not None:
            message += f"\n\n📊 <b>누적 승률:</b> {exit_info.win_rate:.1%} ({exit_info.total_trades}건)"

        return await self.send_message(message.strip())

    async def send_daily_report(self, report: DailyReport) -> bool:
        if not self._settings.notification.daily_report:
            return False

        pnl_emoji = "📈" if report.daily_pnl >= 0 else "📉"

        message = (
            f"📊 <b>Daily Report - {report.date}</b>\n\n"
            f"{pnl_emoji} <b>Daily P&L:</b> {report.daily_pnl:+,.0f} ({report.daily_pnl_pct:+.2%})\n\n"
            f"<b>Portfolio Value:</b> {report.total_value:,.0f}\n"
            f"<b>Open Positions:</b> {report.open_positions}\n"
            f"<b>Total Units:</b> {report.total_units}/20\n\n"
            f"<b>Today's Activity:</b>\n"
            f"- Signals: {report.signals_generated}\n"
            f"- Orders: {report.orders_executed}"
        )

        if report.win_rate is not None and report.total_closed_trades:
            win = report.win_count or 0
            loss = report.loss_count or 0
            message += (
                f"\n\n📈 <b>전체 성과</b>\n"
                f"- 총 거래: {report.total_closed_trades}건\n"
                f"- 승률: {report.win_rate:.1%} ({win}승 {loss}패)"
            )
            if report.avg_holding_days is not None:
                message += f"\n- 평균 보유: {report.avg_holding_days:.1f}일"
            if report.profit_factor is not None and report.profit_factor > 0:
                message += f"\n- 손익비: {report.profit_factor:.2f}"

        return await self.send_message(message.strip())

    async def notify_stop_loss_triggered(
        self,
        symbol: str,
        entry_price: Decimal,
        exit_price: Decimal,
        quantity: int,
    ) -> bool:
        pnl = (exit_price - entry_price) * quantity
        pnl_pct = (exit_price - entry_price) / entry_price

        message = f"""
🛑 <b>STOP LOSS TRIGGERED</b>

<b>Symbol:</b> {symbol}
<b>Entry:</b> {entry_price:,.2f}
<b>Exit:</b> {exit_price:,.2f}
<b>Quantity:</b> {quantity:,}
<b>Loss:</b> {pnl:,.0f} ({pnl_pct:.2%})
"""
        return await self.send_message(message.strip())

    async def notify_error(self, error_type: str, error_message: str) -> bool:
        message = f"""
⚠️ <b>Error: {error_type}</b>

{error_message}
"""
        return await self.send_message(message.strip())

    async def notify_system_start(self, mode: str, market: str) -> bool:
        message = f"""
🚀 <b>Turtle-CANSLIM Started</b>

<b>Mode:</b> {mode.upper()}
<b>Market:</b> {market.upper()}
<b>Time:</b> {asyncio.get_event_loop().time():.0f}
"""
        return await self.send_message(message.strip())

    async def notify_system_stop(self, reason: str = "Normal shutdown") -> bool:
        message = f"""
🔴 <b>Turtle-CANSLIM Stopped</b>

<b>Reason:</b> {reason}
"""
        return await self.send_message(message.strip())

    def _get_signal_emoji(self, signal_type: str) -> str:
        emojis = {
            "ENTRY_S1": "🟢",
            "ENTRY_S2": "🟢",
            "EXIT_S1": "🔴",
            "EXIT_S2": "🔴",
            "STOP_LOSS": "🛑",
            "PYRAMID": "📊",
        }
        return emojis.get(signal_type, "📌")
