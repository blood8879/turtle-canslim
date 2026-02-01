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
class DailyReport:
    date: str
    total_value: Decimal
    daily_pnl: Decimal
    daily_pnl_pct: Decimal
    open_positions: int
    total_units: int
    signals_generated: int
    orders_executed: int


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

    async def send_daily_report(self, report: DailyReport) -> bool:
        if not self._settings.notification.daily_report:
            return False

        pnl_emoji = "📈" if report.daily_pnl >= 0 else "📉"

        message = f"""
📊 <b>Daily Report - {report.date}</b>

{pnl_emoji} <b>Daily P&L:</b> {report.daily_pnl:+,.0f} ({report.daily_pnl_pct:+.2%})

<b>Portfolio Value:</b> {report.total_value:,.0f}
<b>Open Positions:</b> {report.open_positions}
<b>Total Units:</b> {report.total_units}/20

<b>Today's Activity:</b>
- Signals Generated: {report.signals_generated}
- Orders Executed: {report.orders_executed}
"""
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
