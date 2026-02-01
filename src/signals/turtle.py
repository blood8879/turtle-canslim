from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.core.config import Settings, get_settings
from src.core.logger import get_logger, get_trading_logger
from src.signals.atr import ATRCalculator
from src.signals.breakout import BreakoutDetector, BreakoutType
from src.signals.pyramid import PyramidManager

if TYPE_CHECKING:
    from src.data.repositories import DailyPriceRepository, PositionRepository, SignalRepository, StockRepository

logger = get_logger(__name__)
tlog = get_trading_logger()


@dataclass
class TurtleSignal:
    symbol: str
    stock_id: int
    signal_type: str
    system: int | None
    price: Decimal
    atr_n: Decimal
    stop_loss: Decimal | None
    position_size: int | None
    timestamp: datetime
    breakout_level: Decimal | None = None
    name: str = ""


class TurtleSignalEngine:
    def __init__(
        self,
        price_repo: DailyPriceRepository,
        position_repo: PositionRepository,
        signal_repo: SignalRepository,
        stock_repo: StockRepository | None = None,
        settings: Settings | None = None,
    ):
        self._settings = settings or get_settings()
        self._price_repo = price_repo
        self._position_repo = position_repo
        self._signal_repo = signal_repo
        self._stock_repo = stock_repo

        turtle_config = self._settings.turtle
        risk_config = self._settings.risk

        self._atr_calc = ATRCalculator(turtle_config)
        self._breakout = BreakoutDetector(turtle_config)
        self._pyramid = PyramidManager(turtle_config, risk_config)

        self._previous_s1_results: dict[int, bool] = {}
        self._stock_cache: dict[int, dict] = {}

    async def check_entry_signals(
        self,
        candidate_stock_ids: list[int],
    ) -> list[TurtleSignal]:
        signals: list[TurtleSignal] = []

        for stock_id in candidate_stock_ids:
            try:
                signal = await self._check_single_entry(stock_id)
                if signal:
                    signals.append(signal)
                    await self._save_signal(signal)
            except Exception as e:
                logger.error("turtle_entry_check_error", stock_id=stock_id, error=str(e))

        logger.info("turtle_entry_signals", count=len(signals))
        return signals

    async def check_entry_signals_realtime(
        self,
        candidate_stock_ids: list[int],
        realtime_prices: dict[int, Decimal],
    ) -> list[TurtleSignal]:
        """realtime_prices: {stock_id: 실시간 현재가}. DB 종가 대신 실시간 가격으로 돌파 판정."""
        signals: list[TurtleSignal] = []

        for stock_id in candidate_stock_ids:
            rt_price = realtime_prices.get(stock_id)
            if rt_price is None or rt_price <= 0:
                continue

            try:
                signal = await self._check_single_entry(stock_id, realtime_price=rt_price)
                if signal:
                    signals.append(signal)
                    await self._save_signal(signal)
            except Exception as e:
                logger.error("turtle_entry_check_error", stock_id=stock_id, error=str(e))

        logger.info("turtle_entry_signals_realtime", count=len(signals))
        return signals

    async def _check_single_entry(
        self,
        stock_id: int,
        realtime_price: Decimal | None = None,
    ) -> TurtleSignal | None:
        existing_position = await self._position_repo.get_by_stock(stock_id, open_only=True)
        if existing_position:
            return None

        prices = await self._price_repo.get_period(stock_id, 60)
        if len(prices) < 56:
            return None

        highs = [p.high for p in prices]
        lows = [p.low for p in prices]
        closes = [p.close for p in prices]

        current_price = realtime_price if realtime_price is not None else closes[-1]

        atr_result = self._atr_calc.calculate(highs, lows, closes)
        if not atr_result:
            return None

        previous_s1_winner = self._previous_s1_results.get(stock_id, True)

        breakout = self._breakout.check_entry(current_price, highs, previous_s1_winner)

        if not breakout.is_entry:
            return None

        stop_loss = current_price - (atr_result.atr * Decimal("2"))

        stock = await self._get_stock_info(stock_id)
        symbol = stock["symbol"] if stock else str(stock_id)
        stock_name = stock["name"] if stock else ""

        tlog.info(
            "entry_breakout_detected",
            symbol=symbol,
            name=stock_name,
            stock_id=stock_id,
            signal_type=breakout.breakout_type.value,
            system=breakout.system,
            current_price=float(current_price),
            breakout_level=float(breakout.breakout_level) if breakout.breakout_level else None,
            atr=float(atr_result.atr),
            atr_pct=float(atr_result.atr_percent),
            stop_loss=float(stop_loss),
            is_realtime=realtime_price is not None,
            prev_s1_winner=previous_s1_winner,
        )

        return TurtleSignal(
            symbol=symbol,
            stock_id=stock_id,
            signal_type=breakout.breakout_type.value,
            system=breakout.system,
            price=current_price,
            atr_n=atr_result.atr,
            stop_loss=stop_loss,
            position_size=None,
            timestamp=datetime.now(),
            breakout_level=breakout.breakout_level,
            name=stock_name,
        )

    async def check_exit_signals(
        self,
        realtime_prices: dict[int, Decimal] | None = None,
    ) -> list[TurtleSignal]:
        signals: list[TurtleSignal] = []

        positions = await self._position_repo.get_open_positions()

        for position in positions:
            try:
                rt_price = realtime_prices.get(position.stock_id) if realtime_prices else None
                signal = await self._check_single_exit(position, realtime_price=rt_price)
                if signal:
                    signals.append(signal)
                    await self._save_signal(signal)
            except Exception as e:
                logger.error("turtle_exit_check_error", position_id=position.id, error=str(e))

        logger.info("turtle_exit_signals", count=len(signals))
        return signals

    async def _check_single_exit(
        self,
        position,
        realtime_price: Decimal | None = None,
    ) -> TurtleSignal | None:
        stock_id = position.stock_id

        prices = await self._price_repo.get_period(stock_id, 25)
        if len(prices) < 21:
            return None

        lows = [p.low for p in prices]
        closes = [p.close for p in prices]
        highs = [p.high for p in prices]

        current_price = realtime_price if realtime_price is not None else closes[-1]

        if position.stop_loss_price and current_price <= position.stop_loss_price:
            stock = await self._get_stock_info(stock_id)
            symbol = stock["symbol"] if stock else str(stock_id)
            stock_name = stock["name"] if stock else ""

            atr_result = self._atr_calc.calculate(highs, lows, closes)

            tlog.warning(
                "stop_loss_triggered",
                symbol=symbol,
                name=stock_name,
                stock_id=stock_id,
                current_price=float(current_price),
                stop_loss=float(position.stop_loss_price),
                entry_price=float(position.entry_price),
                quantity=position.quantity,
                is_realtime=realtime_price is not None,
            )

            return TurtleSignal(
                symbol=symbol,
                stock_id=stock_id,
                signal_type="STOP_LOSS",
                system=position.entry_system,
                price=current_price,
                atr_n=atr_result.atr if atr_result else Decimal(0),
                stop_loss=position.stop_loss_price,
                position_size=position.quantity,
                timestamp=datetime.now(),
                breakout_level=position.stop_loss_price,
                name=stock_name,
            )

        entry_system = position.entry_system or 1
        breakout = self._breakout.check_exit(current_price, lows, entry_system)

        if not breakout.is_exit:
            return None

        stock = await self._get_stock_info(stock_id)
        symbol = stock["symbol"] if stock else str(stock_id)
        stock_name = stock["name"] if stock else ""
        atr_result = self._atr_calc.calculate(highs, lows, closes)

        tlog.info(
            "channel_exit_detected",
            symbol=symbol,
            name=stock_name,
            stock_id=stock_id,
            signal_type=breakout.breakout_type.value,
            system=breakout.system,
            current_price=float(current_price),
            breakout_level=float(breakout.breakout_level) if breakout.breakout_level is not None else None,
            entry_price=float(position.entry_price),
            quantity=position.quantity,
            is_realtime=realtime_price is not None,
        )

        return TurtleSignal(
            symbol=symbol,
            stock_id=stock_id,
            signal_type=breakout.breakout_type.value,
            system=breakout.system,
            price=current_price,
            atr_n=atr_result.atr if atr_result else Decimal(0),
            stop_loss=None,
            position_size=position.quantity,
            timestamp=datetime.now(),
            breakout_level=breakout.breakout_level,
            name=stock_name,
        )

    async def check_pyramid_signals(
        self,
        realtime_prices: dict[int, Decimal] | None = None,
    ) -> list[TurtleSignal]:
        signals: list[TurtleSignal] = []

        positions = await self._position_repo.get_open_positions()

        for position in positions:
            try:
                rt_price = realtime_prices.get(position.stock_id) if realtime_prices else None
                signal = await self._check_single_pyramid(position, realtime_price=rt_price)
                if signal:
                    signals.append(signal)
                    await self._save_signal(signal)
            except Exception as e:
                logger.error("turtle_pyramid_check_error", position_id=position.id, error=str(e))

        logger.info("turtle_pyramid_signals", count=len(signals))
        return signals

    async def _check_single_pyramid(
        self,
        position,
        realtime_price: Decimal | None = None,
    ) -> TurtleSignal | None:
        stock_id = position.stock_id

        prices = await self._price_repo.get_period(stock_id, 25)
        if len(prices) < 21:
            return None

        highs = [p.high for p in prices]
        lows = [p.low for p in prices]
        closes = [p.close for p in prices]

        current_price = realtime_price if realtime_price is not None else closes[-1]

        atr_result = self._atr_calc.calculate(highs, lows, closes)
        if not atr_result:
            return None

        pyramid_signal = self._pyramid.check_pyramid_signal(
            current_price=current_price,
            initial_entry=position.entry_price,
            atr_n=atr_result.atr,
            current_units=position.units,
        )

        if not pyramid_signal.should_pyramid:
            return None

        stock = await self._get_stock_info(stock_id)
        symbol = stock["symbol"] if stock else str(stock_id)
        stock_name = stock["name"] if stock else ""

        tlog.info(
            "pyramid_signal_detected",
            symbol=symbol,
            name=stock_name,
            stock_id=stock_id,
            current_price=float(current_price),
            initial_entry=float(position.entry_price),
            atr=float(atr_result.atr),
            current_units=position.units,
            next_entry_price=float(pyramid_signal.next_entry_price) if pyramid_signal.next_entry_price is not None else None,
            new_stop_loss=float(pyramid_signal.new_stop_loss) if pyramid_signal.new_stop_loss is not None else None,
            is_realtime=realtime_price is not None,
        )

        return TurtleSignal(
            symbol=symbol,
            stock_id=stock_id,
            signal_type="PYRAMID",
            system=position.entry_system,
            price=current_price,
            atr_n=atr_result.atr,
            stop_loss=pyramid_signal.new_stop_loss,
            position_size=None,
            timestamp=datetime.now(),
            breakout_level=pyramid_signal.next_entry_price,
            name=stock_name,
        )

    async def _save_signal(self, signal: TurtleSignal) -> None:
        await self._signal_repo.create(
            stock_id=signal.stock_id,
            timestamp=signal.timestamp,
            signal_type=signal.signal_type,
            price=signal.price,
            system=signal.system,
            atr_n=signal.atr_n,
        )

    async def _get_stock_info(self, stock_id: int) -> dict | None:
        if stock_id in self._stock_cache:
            return self._stock_cache[stock_id]

        if self._stock_repo:
            try:
                stock = await self._stock_repo.get_by_id(stock_id)
                if stock:
                    info = {"symbol": stock.symbol, "name": stock.name}
                    self._stock_cache[stock_id] = info
                    return info
            except Exception:
                pass

        fallback = {"symbol": str(stock_id), "name": ""}
        self._stock_cache[stock_id] = fallback
        return fallback

    def update_s1_result(self, stock_id: int, was_winner: bool) -> None:
        self._previous_s1_results[stock_id] = was_winner

    async def get_pending_signals(self) -> list[TurtleSignal]:
        signals = await self._signal_repo.get_pending()
        result: list[TurtleSignal] = []

        for sig in signals:
            stock = await self._get_stock_info(sig.stock_id)
            result.append(
                TurtleSignal(
                    symbol=stock["symbol"] if stock else str(sig.stock_id),
                    stock_id=sig.stock_id,
                    signal_type=sig.signal_type,
                    system=sig.system,
                    price=sig.price,
                    atr_n=sig.atr_n or Decimal(0),
                    stop_loss=None,
                    position_size=None,
                    timestamp=sig.timestamp,
                    name=stock["name"] if stock else "",
                )
            )

        return result
