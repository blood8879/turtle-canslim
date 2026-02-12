from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.core.config import Settings, get_settings
from src.core.exceptions import InsufficientFundsError, OrderError, TradingError
from src.core.logger import get_logger, get_trading_logger
from src.data.models import OrderStatus, OrderType, OrderMethod
from src.risk.position_sizing import PositionSizer
from src.risk.unit_limits import UnitLimitManager
from src.signals.turtle import TurtleSignal

if TYPE_CHECKING:
    from src.core.trade_journal import TradeJournal
    from src.data.repositories import OrderRepository, PositionRepository
    from src.execution.broker_interface import BrokerInterface

logger = get_logger(__name__)
tlog = get_trading_logger()


@dataclass
class ExecutionResult:
    success: bool
    order_id: str | None
    symbol: str
    side: str
    quantity: int
    filled_price: Decimal | None
    message: str
    # Exit-specific metadata (populated only on successful exits)
    entry_price: Decimal | None = None
    pnl: Decimal | None = None
    pnl_percent: Decimal | None = None
    holding_days: int | None = None
    win_rate: Decimal | None = None
    total_trades: int | None = None
    stock_name: str | None = None


class OrderManager:
    def __init__(
        self,
        broker: BrokerInterface,
        position_sizer: PositionSizer,
        unit_manager: UnitLimitManager,
        order_repo: OrderRepository,
        position_repo: PositionRepository,
        settings: Settings | None = None,
        trade_journal: TradeJournal | None = None,
        stock_name: str = "",
        stock_market: str = "",
    ):
        self._broker = broker
        self._position_sizer = position_sizer
        self._unit_manager = unit_manager
        self._order_repo = order_repo
        self._position_repo = position_repo
        self._settings = settings or get_settings()
        self._max_entry_slippage = Decimal(str(self._settings.risk.max_entry_slippage_pct))
        self._max_exit_slippage = Decimal(str(self._settings.risk.max_exit_slippage_pct))
        self._journal = trade_journal
        self._stock_name = stock_name
        self._stock_market = stock_market

    def _check_entry_slippage(self, signal: TurtleSignal) -> tuple[bool, str]:
        if signal.breakout_level is None or signal.breakout_level <= 0:
            return True, ""

        slippage = (signal.price - signal.breakout_level) / signal.breakout_level
        if slippage > self._max_entry_slippage:
            return False, (
                f"Entry slippage {slippage:.1%} exceeds max {self._max_entry_slippage:.1%} "
                f"(price={signal.price}, breakout={signal.breakout_level})"
            )
        return True, ""

    async def _get_actual_fill_price(self, order_id: str | None, fallback: Decimal) -> Decimal:
        if not order_id:
            return fallback
        try:
            order_status = await self._broker.get_order_status(order_id)
            if order_status and order_status.filled_price and order_status.filled_price > 0:
                return order_status.filled_price
        except Exception as e:
            logger.warning("fill_price_lookup_failed", order_id=order_id, error=str(e))
        return fallback

    async def execute_entry(self, signal: TurtleSignal) -> ExecutionResult:
        logger.info(
            "execute_entry_start",
            symbol=signal.symbol,
            signal_type=signal.signal_type,
            price=float(signal.price),
            breakout_level=float(signal.breakout_level) if signal.breakout_level else None,
        )

        try:
            slippage_ok, slippage_msg = self._check_entry_slippage(signal)
            if not slippage_ok:
                logger.warning("entry_slippage_rejected", symbol=signal.symbol, reason=slippage_msg)
                return ExecutionResult(
                    success=False,
                    order_id=None,
                    symbol=signal.symbol,
                    side="BUY",
                    quantity=0,
                    filled_price=None,
                    message=slippage_msg,
                )

            check = await self._unit_manager.can_add_unit(signal.stock_id)
            if not check.can_add:
                logger.warning("unit_limit_blocked", symbol=signal.symbol, reason=check.reason)
                return ExecutionResult(
                    success=False,
                    order_id=None,
                    symbol=signal.symbol,
                    side="BUY",
                    quantity=0,
                    filled_price=None,
                    message=check.reason,
                )

            balance = await self._broker.get_balance()
            account_value = balance.total_value

            position_result = self._position_sizer.calculate_full_position(
                account_value=account_value,
                entry_price=signal.price,
                atr_n=signal.atr_n,
            )

            tlog.info(
                "entry_position_sizing",
                symbol=signal.symbol,
                account_value=float(account_value),
                buying_power=float(balance.buying_power),
                entry_price=float(signal.price),
                atr_n=float(signal.atr_n),
                calculated_qty=position_result.quantity,
                position_value=float(position_result.position_value),
                risk_amount=float(position_result.risk_amount),
                stop_loss=float(position_result.stop_loss_price),
                stop_loss_type=position_result.stop_loss_type,
            )

            required_cash = signal.price * position_result.quantity
            if required_cash > balance.buying_power:
                available_qty = int(balance.buying_power / signal.price)
                if available_qty < 1:
                    tlog.warning(
                        "entry_insufficient_funds",
                        symbol=signal.symbol,
                        required=float(required_cash),
                        available=float(balance.buying_power),
                    )
                    raise InsufficientFundsError(
                        required=float(required_cash),
                        available=float(balance.buying_power),
                    )
                tlog.info(
                    "entry_qty_reduced",
                    symbol=signal.symbol,
                    original_qty=position_result.quantity,
                    reduced_qty=available_qty,
                    reason="insufficient_buying_power",
                )
                position_result.quantity = available_qty

            order = await self._order_repo.create(
                stock_id=signal.stock_id,
                order_type=OrderType.BUY.value,
                order_method=OrderMethod.MARKET.value,
                quantity=position_result.quantity,
            )

            response = await self._broker.buy_market(signal.symbol, position_result.quantity)

            if response.success:
                filled_price = await self._get_actual_fill_price(response.order_id, signal.price)

                actual_slippage = (
                    (filled_price - signal.breakout_level) / signal.breakout_level
                    if signal.breakout_level and signal.breakout_level > 0
                    else Decimal("0")
                )
                tlog.info(
                    "entry_filled",
                    symbol=signal.symbol,
                    order_id=response.order_id,
                    quantity=position_result.quantity,
                    signal_price=float(signal.price),
                    breakout_level=float(signal.breakout_level) if signal.breakout_level else None,
                    filled_price=float(filled_price),
                    actual_slippage_pct=float(actual_slippage),
                    total_cost=float(filled_price * position_result.quantity),
                )

                await self._order_repo.update_status(
                    order_id=order.id,
                    status=OrderStatus.FILLED.value,
                    broker_order_id=response.order_id,
                    filled_quantity=position_result.quantity,
                    filled_price=filled_price,
                    filled_at=datetime.now(),
                )

                stop_loss_price = filled_price - (signal.atr_n * Decimal("2"))
                stop_loss_pct = filled_price * (1 - Decimal(str(self._settings.risk.stop_loss_max_percent)))
                effective_stop = max(stop_loss_price, stop_loss_pct)

                position = await self._position_repo.create(
                    stock_id=signal.stock_id,
                    entry_date=datetime.now(),
                    entry_price=filled_price,
                    quantity=position_result.quantity,
                    entry_system=signal.system,
                    stop_loss_price=effective_stop,
                    stop_loss_type=position_result.stop_loss_type,
                )

                tlog.info(
                    "position_opened",
                    symbol=signal.symbol,
                    position_id=position.id,
                    entry_price=float(filled_price),
                    quantity=position_result.quantity,
                    stop_loss=float(effective_stop),
                    system=signal.system,
                )

                logger.info(
                    "entry_executed",
                    symbol=signal.symbol,
                    quantity=position_result.quantity,
                    signal_price=float(signal.price),
                    filled_price=float(filled_price),
                    position_id=position.id,
                )

                if self._journal:
                    risk_pct = (effective_stop - filled_price) / filled_price if filled_price > 0 else None
                    self._journal.log_entry(
                        timestamp=datetime.now(),
                        symbol=signal.symbol,
                        name=signal.name or self._stock_name,
                        market=self._stock_market,
                        system=signal.system,
                        entry_price=filled_price,
                        breakout_level=signal.breakout_level,
                        quantity=position_result.quantity,
                        position_value=filled_price * position_result.quantity,
                        stop_loss=effective_stop,
                        stop_loss_type=position_result.stop_loss_type,
                        risk_pct=risk_pct,
                    )

                return ExecutionResult(
                    success=True,
                    order_id=response.order_id,
                    symbol=signal.symbol,
                    side="BUY",
                    quantity=position_result.quantity,
                    filled_price=filled_price,
                    message="Entry order executed",
                )
            else:
                await self._order_repo.update_status(
                    order_id=order.id,
                    status=OrderStatus.FAILED.value,
                )

                return ExecutionResult(
                    success=False,
                    order_id=None,
                    symbol=signal.symbol,
                    side="BUY",
                    quantity=position_result.quantity,
                    filled_price=None,
                    message=response.message,
                )

        except InsufficientFundsError:
            raise
        except Exception as e:
            logger.error("execute_entry_error", symbol=signal.symbol, error=str(e))
            raise OrderError(f"Failed to execute entry: {e}") from e

    async def execute_exit(self, signal: TurtleSignal) -> ExecutionResult:
        logger.info(
            "execute_exit_start",
            symbol=signal.symbol,
            signal_type=signal.signal_type,
        )

        try:
            position = await self._position_repo.get_by_stock(signal.stock_id, open_only=True)
            if not position:
                return ExecutionResult(
                    success=False,
                    order_id=None,
                    symbol=signal.symbol,
                    side="SELL",
                    quantity=0,
                    filled_price=None,
                    message="No open position found",
                )

            order = await self._order_repo.create(
                stock_id=signal.stock_id,
                order_type=OrderType.SELL.value,
                order_method=OrderMethod.MARKET.value,
                quantity=position.quantity,
                position_id=position.id,
            )

            response = await self._broker.sell_market(signal.symbol, position.quantity)

            if response.success:
                filled_price = await self._get_actual_fill_price(response.order_id, signal.price)

                pnl = (filled_price - position.entry_price) * position.quantity
                pnl_pct = (
                    (filled_price - position.entry_price) / position.entry_price
                    if position.entry_price > 0
                    else Decimal("0")
                )

                tlog.info(
                    "position_closed",
                    symbol=signal.symbol,
                    position_id=position.id,
                    entry_price=float(position.entry_price),
                    exit_price=float(filled_price),
                    quantity=position.quantity,
                    pnl=float(pnl),
                    pnl_pct=float(pnl_pct),
                    exit_reason=signal.signal_type,
                    order_id=response.order_id,
                )

                await self._order_repo.update_status(
                    order_id=order.id,
                    status=OrderStatus.FILLED.value,
                    broker_order_id=response.order_id,
                    filled_quantity=position.quantity,
                    filled_price=filled_price,
                    filled_at=datetime.now(),
                )

                await self._position_repo.close_position(
                    position_id=position.id,
                    exit_date=datetime.now(),
                    exit_price=filled_price,
                    exit_reason=signal.signal_type,
                )

                logger.info(
                    "exit_executed",
                    symbol=signal.symbol,
                    quantity=position.quantity,
                    signal_price=float(signal.price),
                    filled_price=float(filled_price),
                    reason=signal.signal_type,
                )

                now = datetime.now()
                holding_days = max((now - position.entry_date).days, 1)
                closed = await self._position_repo.get_closed_positions()
                from src.execution.performance import PerformanceTracker
                stats = PerformanceTracker.calculate(closed)

                if self._journal:
                    self._journal.log_exit(
                        timestamp=now,
                        symbol=signal.symbol,
                        name=signal.name or self._stock_name,
                        market=self._stock_market,
                        exit_reason=signal.signal_type,
                        entry_price=position.entry_price,
                        exit_price=filled_price,
                        quantity=position.quantity,
                        pnl=pnl,
                        pnl_percent=pnl_pct,
                        holding_days=holding_days,
                        stats=stats,
                    )

                return ExecutionResult(
                    success=True,
                    order_id=response.order_id,
                    symbol=signal.symbol,
                    side="SELL",
                    quantity=position.quantity,
                    filled_price=filled_price,
                    message=f"Exit order executed ({signal.signal_type})",
                    entry_price=position.entry_price,
                    pnl=pnl,
                    pnl_percent=pnl_pct,
                    holding_days=holding_days,
                    win_rate=stats.win_rate if stats.total_trades > 0 else None,
                    total_trades=stats.total_trades,
                    stock_name=signal.name or self._stock_name,
                )
            else:
                await self._order_repo.update_status(
                    order_id=order.id,
                    status=OrderStatus.FAILED.value,
                )

                return ExecutionResult(
                    success=False,
                    order_id=None,
                    symbol=signal.symbol,
                    side="SELL",
                    quantity=position.quantity,
                    filled_price=None,
                    message=response.message,
                )

        except Exception as e:
            logger.error("execute_exit_error", symbol=signal.symbol, error=str(e))
            raise OrderError(f"Failed to execute exit: {e}") from e

    async def execute_pyramid(self, signal: TurtleSignal) -> ExecutionResult:
        logger.info(
            "execute_pyramid_start",
            symbol=signal.symbol,
            breakout_level=float(signal.breakout_level) if signal.breakout_level else None,
        )

        try:
            slippage_ok, slippage_msg = self._check_entry_slippage(signal)
            if not slippage_ok:
                logger.warning("pyramid_slippage_rejected", symbol=signal.symbol, reason=slippage_msg)
                return ExecutionResult(
                    success=False,
                    order_id=None,
                    symbol=signal.symbol,
                    side="BUY",
                    quantity=0,
                    filled_price=None,
                    message=slippage_msg,
                )

            position = await self._position_repo.get_by_stock(signal.stock_id, open_only=True)
            if not position:
                return ExecutionResult(
                    success=False,
                    order_id=None,
                    symbol=signal.symbol,
                    side="BUY",
                    quantity=0,
                    filled_price=None,
                    message="No open position for pyramiding",
                )

            check = await self._unit_manager.can_add_unit(signal.stock_id)
            if not check.can_add:
                return ExecutionResult(
                    success=False,
                    order_id=None,
                    symbol=signal.symbol,
                    side="BUY",
                    quantity=0,
                    filled_price=None,
                    message=check.reason,
                )

            balance = await self._broker.get_balance()
            position_result = self._position_sizer.calculate_full_position(
                account_value=balance.total_value,
                entry_price=signal.price,
                atr_n=signal.atr_n,
            )

            required_cash = signal.price * position_result.quantity
            if required_cash > balance.buying_power:
                return ExecutionResult(
                    success=False,
                    order_id=None,
                    symbol=signal.symbol,
                    side="BUY",
                    quantity=0,
                    filled_price=None,
                    message="Insufficient funds for pyramiding",
                )

            order = await self._order_repo.create(
                stock_id=signal.stock_id,
                order_type=OrderType.BUY.value,
                order_method=OrderMethod.MARKET.value,
                quantity=position_result.quantity,
                position_id=position.id,
            )

            response = await self._broker.buy_market(signal.symbol, position_result.quantity)

            if response.success:
                filled_price = await self._get_actual_fill_price(response.order_id, signal.price)

                await self._order_repo.update_status(
                    order_id=order.id,
                    status=OrderStatus.FILLED.value,
                    broker_order_id=response.order_id,
                    filled_quantity=position_result.quantity,
                    filled_price=filled_price,
                    filled_at=datetime.now(),
                )

                await self._position_repo.add_pyramid_unit(
                    position_id=position.id,
                    additional_quantity=position_result.quantity,
                    additional_price=filled_price,
                )

                if signal.stop_loss:
                    position.stop_loss_price = signal.stop_loss

                logger.info(
                    "pyramid_executed",
                    symbol=signal.symbol,
                    additional_qty=position_result.quantity,
                    signal_price=float(signal.price),
                    filled_price=float(filled_price),
                    new_units=position.units + 1,
                )

                if self._journal:
                    self._journal.log_pyramid(
                        timestamp=datetime.now(),
                        symbol=signal.symbol,
                        name=signal.name or self._stock_name,
                        market=self._stock_market,
                        price=filled_price,
                        additional_qty=position_result.quantity,
                        new_units=position.units + 1,
                        avg_entry_price=position.entry_price,
                    )

                return ExecutionResult(
                    success=True,
                    order_id=response.order_id,
                    symbol=signal.symbol,
                    side="BUY",
                    quantity=position_result.quantity,
                    filled_price=filled_price,
                    message=f"Pyramid order executed (Unit {position.units + 1})",
                )
            else:
                await self._order_repo.update_status(
                    order_id=order.id,
                    status=OrderStatus.FAILED.value,
                )

                return ExecutionResult(
                    success=False,
                    order_id=None,
                    symbol=signal.symbol,
                    side="BUY",
                    quantity=position_result.quantity,
                    filled_price=None,
                    message=response.message,
                )

        except Exception as e:
            logger.error("execute_pyramid_error", symbol=signal.symbol, error=str(e))
            raise OrderError(f"Failed to execute pyramid: {e}") from e

    async def process_signal(self, signal: TurtleSignal) -> ExecutionResult:
        if signal.signal_type in ["ENTRY_S1", "ENTRY_S2"]:
            return await self.execute_entry(signal)
        elif signal.signal_type in ["EXIT_S1", "EXIT_S2", "STOP_LOSS"]:
            return await self.execute_exit(signal)
        elif signal.signal_type == "PYRAMID":
            return await self.execute_pyramid(signal)
        else:
            return ExecutionResult(
                success=False,
                order_id=None,
                symbol=signal.symbol,
                side="",
                quantity=0,
                filled_price=None,
                message=f"Unknown signal type: {signal.signal_type}",
            )
