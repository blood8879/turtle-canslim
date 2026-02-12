#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.core.config import get_settings, TradingMode
from src.core.database import get_db_manager
from src.core.logger import configure_logging, get_logger, get_trading_logger
from src.core.scheduler import TradingScheduler
from src.data.repositories import (
    StockRepository,
    DailyPriceRepository,
    PositionRepository,
    SignalRepository,
    OrderRepository,
    CANSLIMScoreRepository,
    FundamentalRepository,
    TradingStateRepository,
)
from src.data.auto_fetcher import AutoDataFetcher
from src.screener.canslim import CANSLIMScreener
from src.signals.turtle import TurtleSignalEngine, TurtleSignal
from src.signals.breakout import BreakoutProximityWatcher, WatchedStock
from src.signals.atr import ATRCalculator
from src.risk.position_sizing import PositionSizer
from src.risk.unit_limits import UnitLimitManager
from src.execution.paper_broker import PaperBroker
from src.execution.live_broker import LiveBroker
from src.execution.order_manager import OrderManager
from src.execution.portfolio import PortfolioManager
from src.core.trade_journal import TradeJournal
from src.execution.performance import PerformanceTracker
from src.notification.telegram_bot import TelegramNotifier, SignalNotification, OrderNotification, ExitNotification

logger = get_logger(__name__)
tlog = get_trading_logger()

shutdown_event = asyncio.Event()


class TradingBot:
    def __init__(self, market: str = "krx"):
        self._settings = get_settings()
        self._market = market
        self._db = get_db_manager()
        self._notifier = TelegramNotifier()
        self._scheduler = TradingScheduler()

        self._brokers: dict[str, LiveBroker | PaperBroker] = {}
        if market == "both":
            self._brokers["krx"] = self._create_broker("krx")
            self._brokers["us"] = self._create_broker("us")
            self._broker = self._brokers["krx"]
        else:
            self._broker = self._create_broker(market)
            self._brokers[market] = self._broker

        self._proximity_watcher = BreakoutProximityWatcher(self._settings.turtle)
        self._journal = TradeJournal()

    def _create_broker(self, market: str) -> LiveBroker | PaperBroker:
        from src.execution.live_broker import MarketType
        broker_market: MarketType = "us" if market == "us" else "krx"
        if self._settings.trading_mode == TradingMode.LIVE:
            return LiveBroker(market=broker_market)
        elif self._settings.has_kis_credentials:
            return LiveBroker(market=broker_market)
        else:
            return PaperBroker(initial_cash=Decimal("100000000"))

    def _get_broker(self, market: str | None = None) -> LiveBroker | PaperBroker:
        target = market or self._market
        return self._brokers.get(target, self._broker)

    async def initialize(self) -> None:
        logger.info(
            "trading_bot_init",
            mode=self._settings.trading_mode.value,
            market=self._market,
        )

        for broker in self._brokers.values():
            await broker.connect()
        await self._db.create_tables()

        balance = await self._broker.get_balance()
        tlog.info(
            "session_start",
            mode=self._settings.trading_mode.value,
            market=self._market,
            total_value=float(balance.total_value),
            cash_balance=float(balance.cash_balance),
            securities_value=float(balance.securities_value),
            buying_power=float(balance.buying_power),
            max_entry_slippage=self._settings.risk.max_entry_slippage_pct,
            signal_interval=self._settings.turtle.signal_check_interval_minutes,
        )

        if self._notifier.is_enabled:
            await self._notifier.notify_system_start(
                mode=self._settings.trading_mode.value,
                market=self._market,
            )

    async def shutdown(self) -> None:
        try:
            balance = await self._broker.get_balance()
            tlog.info(
                "session_end",
                total_value=float(balance.total_value),
                cash_balance=float(balance.cash_balance),
            )
        except Exception:
            tlog.info("session_end", balance="unavailable")
        logger.info("trading_bot_shutdown")

        self._scheduler.stop()
        for broker in self._brokers.values():
            await broker.disconnect()
        await self._db.close()

        if self._notifier.is_enabled:
            await self._notifier.notify_system_stop()

    async def run_data_update(self, market: str | None = None) -> None:
        target = market or self._market
        logger.info("running_data_update", market=target)

        async with self._db.session() as session:
            fetcher = AutoDataFetcher(session)
            await fetcher.ensure_data(target)

        logger.info("data_update_complete", market=target)

    async def run_financial_update(self, market: str | None = None) -> None:
        target = market or self._market
        logger.info("running_financial_update", market=target)

        async with self._db.session() as session:
            fetcher = AutoDataFetcher(session)
            updated = await fetcher.ensure_financials(target)

        logger.info("financial_update_complete", market=target, updated=updated)

    async def run_screening(self) -> list[str]:
        logger.info("running_screening", market=self._market)

        async with self._db.session() as session:
            stock_repo = StockRepository(session)
            fundamental_repo = FundamentalRepository(session)
            price_repo = DailyPriceRepository(session)
            score_repo = CANSLIMScoreRepository(session)

            screener = CANSLIMScreener(
                stock_repo=stock_repo,
                fundamental_repo=fundamental_repo,
                price_repo=price_repo,
                score_repo=score_repo,
            )

            results = await screener.screen(self._market)
            candidates = [r for r in results if r.is_candidate]

            logger.info("screening_complete", candidates=len(candidates))

            return [r.symbol for r in candidates]

    async def run_premarket(self, market: str | None = None) -> None:
        target = market or self._market
        start = datetime.now()
        logger.info("premarket_start", market=target)
        tlog.info("premarket_data_update_start", market=target)

        try:
            await self.run_financial_update(market=target)
            tlog.info("premarket_financial_update_done", market=target)
        except Exception as e:
            logger.error("premarket_financial_update_failed", market=target, error=str(e))

        try:
            saved_market = self._market
            self._market = target
            candidates = await self.run_screening()
            self._market = saved_market
            tlog.info(
                "premarket_screening_done",
                market=target,
                candidates=len(candidates),
            )
        except Exception as e:
            logger.error("premarket_screening_failed", market=target, error=str(e))
            candidates = []

        elapsed = (datetime.now() - start).total_seconds()
        tlog.info(
            "premarket_complete",
            market=target,
            candidates=len(candidates),
            elapsed_seconds=round(elapsed, 1),
        )

        if self._notifier.is_enabled:
            market_label = "KRX" if target == "krx" else "US"
            msg = (
                f"📋 <b>{market_label} 장전 준비 완료</b>\n\n"
                f"<b>재무 데이터:</b> 최신 업데이트 완료\n"
                f"<b>CANSLIM 후보:</b> {len(candidates)}종목\n"
                f"<b>소요 시간:</b> {elapsed:.0f}초"
            )
            if candidates:
                symbols = ", ".join(candidates[:10])
                msg += f"\n\n<b>후보 종목:</b> {symbols}"
                if len(candidates) > 10:
                    msg += f" 외 {len(candidates) - 10}개"
            await self._notifier.send_message(msg)

    _US_MARKETS = {"NYSE", "NASDAQ", "US", "us"}

    def _broker_for_stock(self, stock_market: str) -> LiveBroker | PaperBroker:
        if stock_market in self._US_MARKETS:
            return self._brokers.get("us", self._broker)
        return self._brokers.get("krx", self._broker)

    async def _fetch_realtime_prices(
        self,
        stock_ids: list[int],
        session,
    ) -> dict[int, Decimal]:
        stock_repo = StockRepository(session)
        prices: dict[int, Decimal] = {}
        failed: list[int] = []

        for stock_id in stock_ids:
            try:
                stock = await stock_repo.get_by_id(stock_id)
                if not stock:
                    continue
                broker = self._broker_for_stock(stock.market)
                price = await broker.get_current_price(stock.symbol)
                if price and price > 0:
                    prices[stock_id] = price
            except Exception as e:
                failed.append(stock_id)
                logger.debug("realtime_price_fetch_failed", stock_id=stock_id, error=str(e))

        if failed:
            tlog.warning(
                "realtime_price_fetch_failures",
                failed_count=len(failed),
                total_requested=len(stock_ids),
                failed_ids=failed[:10],
            )

        return prices

    async def run_realtime_signal_check(self) -> None:
        cycle_start = datetime.now()
        logger.info("checking_realtime_signals")
        tlog.info("signal_cycle_start", timestamp=cycle_start.isoformat())

        async with self._db.session() as session:
            price_repo = DailyPriceRepository(session)
            position_repo = PositionRepository(session)
            signal_repo = SignalRepository(session)
            order_repo = OrderRepository(session)
            stock_repo = StockRepository(session)

            signal_engine = TurtleSignalEngine(
                price_repo=price_repo,
                position_repo=position_repo,
                signal_repo=signal_repo,
                stock_repo=stock_repo,
            )

            position_sizer = PositionSizer(self._settings.risk)
            unit_manager = UnitLimitManager(self._settings.risk, position_repo)

            async def _make_order_manager(stock_id: int) -> OrderManager:
                stock = await stock_repo.get_by_id(stock_id)
                broker = self._broker_for_stock(stock.market) if stock else self._broker
                return OrderManager(
                    broker=broker,
                    position_sizer=position_sizer,
                    unit_manager=unit_manager,
                    order_repo=order_repo,
                    position_repo=position_repo,
                    trade_journal=self._journal,
                    stock_name=stock.name if stock else "",
                    stock_market=stock.market if stock else "",
                )

            open_positions = await position_repo.get_open_positions()
            position_stock_ids = [p.stock_id for p in open_positions]

            scores = await CANSLIMScoreRepository(session).get_candidates(
                min_score=5, market=self._market
            )
            candidate_ids = [s.stock_id for s in scores]

            all_stock_ids = list(set(position_stock_ids + candidate_ids))
            if not all_stock_ids:
                logger.debug("no_stocks_to_monitor")
                return

            realtime_prices = await self._fetch_realtime_prices(all_stock_ids, session)
            if not realtime_prices:
                logger.warning("no_realtime_prices_available")
                return

            logger.info("realtime_prices_fetched", count=len(realtime_prices))

            exit_signals = await signal_engine.check_exit_signals(realtime_prices=realtime_prices)
            for sig in exit_signals:
                tlog.info(
                    "exit_signal_detected",
                    symbol=sig.symbol,
                    signal_type=sig.signal_type,
                    price=float(sig.price),
                    stop_loss=float(sig.stop_loss) if sig.stop_loss else None,
                    system=sig.system,
                )
                order_manager = await _make_order_manager(sig.stock_id)
                result = await order_manager.execute_exit(sig)
                tlog.info(
                    "exit_order_result",
                    symbol=sig.symbol,
                    success=result.success,
                    quantity=result.quantity,
                    filled_price=float(result.filled_price) if result.filled_price else None,
                    order_id=result.order_id,
                    message=result.message,
                )

                if self._notifier.is_enabled:
                    await self._notifier.notify_signal(
                        SignalNotification(
                            symbol=sig.symbol,
                            signal_type=sig.signal_type,
                            price=sig.price,
                            atr_n=sig.atr_n,
                            stop_loss=sig.stop_loss,
                            system=sig.system,
                        )
                    )

                    if result.success:
                        await self._notifier.notify_order(
                            OrderNotification(
                                symbol=sig.symbol,
                                side="SELL",
                                quantity=result.quantity,
                                price=result.filled_price or sig.price,
                                order_id=result.order_id,
                                success=result.success,
                                message=result.message,
                            )
                        )
                        if result.entry_price is not None:
                            await self._notifier.notify_exit(
                                ExitNotification(
                                    symbol=sig.symbol,
                                    name=result.stock_name or sig.symbol,
                                    exit_reason=sig.signal_type,
                                    entry_price=result.entry_price,
                                    exit_price=result.filled_price or sig.price,
                                    quantity=result.quantity,
                                    pnl=result.pnl or Decimal("0"),
                                    pnl_percent=result.pnl_percent or Decimal("0"),
                                    holding_days=result.holding_days or 0,
                                    win_rate=result.win_rate,
                                    total_trades=result.total_trades,
                                )
                            )

            pyramid_signals = await signal_engine.check_pyramid_signals(
                realtime_prices=realtime_prices,
            )
            for sig in pyramid_signals:
                tlog.info(
                    "pyramid_signal_detected",
                    symbol=sig.symbol,
                    price=float(sig.price),
                    breakout_level=float(sig.breakout_level) if sig.breakout_level else None,
                    atr_n=float(sig.atr_n),
                )
                order_manager = await _make_order_manager(sig.stock_id)
                result = await order_manager.execute_pyramid(sig)
                tlog.info(
                    "pyramid_order_result",
                    symbol=sig.symbol,
                    success=result.success,
                    quantity=result.quantity,
                    filled_price=float(result.filled_price) if result.filled_price else None,
                    message=result.message,
                )

                if self._notifier.is_enabled and result.success:
                    await self._notifier.notify_order(
                        OrderNotification(
                            symbol=sig.symbol,
                            side="BUY",
                            quantity=result.quantity,
                            price=result.filled_price or sig.price,
                            order_id=result.order_id,
                            success=result.success,
                            message="Pyramid " + result.message,
                        )
                    )

            entry_signals = await signal_engine.check_entry_signals_realtime(
                candidate_ids,
                realtime_prices,
            )
            for sig in entry_signals:
                tlog.info(
                    "entry_signal_detected",
                    symbol=sig.symbol,
                    signal_type=sig.signal_type,
                    price=float(sig.price),
                    breakout_level=float(sig.breakout_level) if sig.breakout_level else None,
                    atr_n=float(sig.atr_n),
                    system=sig.system,
                )
                order_manager = await _make_order_manager(sig.stock_id)
                result = await order_manager.execute_entry(sig)
                tlog.info(
                    "entry_order_result",
                    symbol=sig.symbol,
                    success=result.success,
                    quantity=result.quantity,
                    filled_price=float(result.filled_price) if result.filled_price else None,
                    order_id=result.order_id,
                    message=result.message,
                )

                if self._notifier.is_enabled:
                    await self._notifier.notify_signal(
                        SignalNotification(
                            symbol=sig.symbol,
                            signal_type=sig.signal_type,
                            price=sig.price,
                            atr_n=sig.atr_n,
                            stop_loss=sig.stop_loss,
                            system=sig.system,
                        )
                    )

                    if result.success:
                        await self._notifier.notify_order(
                            OrderNotification(
                                symbol=sig.symbol,
                                side="BUY",
                                quantity=result.quantity,
                                price=result.filled_price or sig.price,
                                order_id=result.order_id,
                                success=result.success,
                                message=result.message,
                            )
                        )

            current_watched_ids = {w.stock_id for w in self._proximity_watcher.get_watched_list()}
            new_watched_ids: set[int] = set()
            atr_calc = ATRCalculator(self._settings.turtle)
            for cid in candidate_ids:
                existing_pos = await position_repo.get_by_stock(cid, open_only=True)
                if existing_pos:
                    continue
                prices = await price_repo.get_period(cid, 60)
                if len(prices) < 56:
                    continue
                highs = [p.high for p in prices]
                lows = [p.low for p in prices]
                closes = [p.close for p in prices]
                current_close = realtime_prices.get(cid, closes[-1])
                rt_highs = highs + [current_close]
                rt_lows = lows + [current_close]
                rt_closes = closes + [current_close]
                atr_result = atr_calc.calculate(rt_highs, rt_lows, rt_closes)
                if not atr_result:
                    continue
                previous_s1_winner = await signal_engine._load_previous_s1_winner(cid)
                targets = signal_engine._breakout.check_proximity(
                    current_close,
                    rt_highs,
                    Decimal(str(self._settings.turtle.breakout_proximity_pct)),
                    previous_s1_winner,
                )
                if targets:
                    stock_info = await signal_engine._get_stock_info(cid)
                    symbol = stock_info["symbol"] if stock_info else str(cid)
                    name = stock_info["name"] if stock_info else ""
                    new_watched_ids.add(cid)
                    self._proximity_watcher.register(
                        WatchedStock(
                            stock_id=cid,
                            symbol=symbol,
                            name=name,
                            targets=targets,
                            highs=rt_highs,
                            lows=rt_lows,
                            closes=rt_closes,
                            atr_n=atr_result.atr,
                            previous_s1_winner=previous_s1_winner,
                            last_price=current_close,
                        )
                    )

            stale_ids = current_watched_ids - new_watched_ids
            for stale_id in stale_ids:
                self._proximity_watcher.unregister(stale_id)

            if self._proximity_watcher.has_targets:
                tlog.info(
                    "proximity_watch_started",
                    count=self._proximity_watcher.watched_count,
                    symbols=self._proximity_watcher.watched_symbols,
                )

            cycle_elapsed = (datetime.now() - cycle_start).total_seconds()
            tlog.info(
                "signal_cycle_complete",
                exits=len(exit_signals),
                pyramids=len(pyramid_signals),
                entries=len(entry_signals),
                prices_fetched=len(realtime_prices),
                candidates=len(candidate_ids),
                open_positions=len(position_stock_ids),
                proximity_watched=self._proximity_watcher.watched_count,
                elapsed_seconds=round(cycle_elapsed, 2),
            )
            logger.info(
                "realtime_signal_check_complete",
                exits=len(exit_signals),
                pyramids=len(pyramid_signals),
                entries=len(entry_signals),
                prices_fetched=len(realtime_prices),
                proximity_watched=self._proximity_watcher.watched_count,
            )

        if self._proximity_watcher.has_targets:
            await self.run_proximity_fast_poll()

    async def run_signal_check(self) -> None:
        logger.info("checking_signals_fallback_daily")

        async with self._db.session() as session:
            price_repo = DailyPriceRepository(session)
            position_repo = PositionRepository(session)
            signal_repo = SignalRepository(session)
            order_repo = OrderRepository(session)
            stock_repo = StockRepository(session)

            signal_engine = TurtleSignalEngine(
                price_repo=price_repo,
                position_repo=position_repo,
                signal_repo=signal_repo,
                stock_repo=stock_repo,
            )

            position_sizer = PositionSizer(self._settings.risk)
            unit_manager = UnitLimitManager(self._settings.risk, position_repo)

            async def _make_order_manager(stock_id: int) -> OrderManager:
                stock = await stock_repo.get_by_id(stock_id)
                broker = self._broker_for_stock(stock.market) if stock else self._broker
                return OrderManager(
                    broker=broker,
                    position_sizer=position_sizer,
                    unit_manager=unit_manager,
                    order_repo=order_repo,
                    position_repo=position_repo,
                    trade_journal=self._journal,
                    stock_name=stock.name if stock else "",
                    stock_market=stock.market if stock else "",
                )

            exit_signals = await signal_engine.check_exit_signals()
            for sig in exit_signals:
                order_manager = await _make_order_manager(sig.stock_id)
                result = await order_manager.execute_exit(sig)

                if self._notifier.is_enabled:
                    await self._notifier.notify_signal(
                        SignalNotification(
                            symbol=sig.symbol,
                            signal_type=sig.signal_type,
                            price=sig.price,
                            atr_n=sig.atr_n,
                            stop_loss=sig.stop_loss,
                            system=sig.system,
                        )
                    )

                    if result.success:
                        await self._notifier.notify_order(
                            OrderNotification(
                                symbol=sig.symbol,
                                side="SELL",
                                quantity=result.quantity,
                                price=result.filled_price or sig.price,
                                order_id=result.order_id,
                                success=result.success,
                                message=result.message,
                            )
                        )
                        if result.entry_price is not None:
                            await self._notifier.notify_exit(
                                ExitNotification(
                                    symbol=sig.symbol,
                                    name=result.stock_name or sig.symbol,
                                    exit_reason=sig.signal_type,
                                    entry_price=result.entry_price,
                                    exit_price=result.filled_price or sig.price,
                                    quantity=result.quantity,
                                    pnl=result.pnl or Decimal("0"),
                                    pnl_percent=result.pnl_percent or Decimal("0"),
                                    holding_days=result.holding_days or 0,
                                    win_rate=result.win_rate,
                                    total_trades=result.total_trades,
                                )
                            )

            pyramid_signals = await signal_engine.check_pyramid_signals()
            for sig in pyramid_signals:
                order_manager = await _make_order_manager(sig.stock_id)
                result = await order_manager.execute_pyramid(sig)

                if self._notifier.is_enabled and result.success:
                    await self._notifier.notify_order(
                        OrderNotification(
                            symbol=sig.symbol,
                            side="BUY",
                            quantity=result.quantity,
                            price=result.filled_price or sig.price,
                            order_id=result.order_id,
                            success=result.success,
                            message="Pyramid " + result.message,
                        )
                    )

            scores = await CANSLIMScoreRepository(session).get_candidates(
                min_score=5, market=self._market
            )
            candidate_ids = [s.stock_id for s in scores]

            entry_signals = await signal_engine.check_entry_signals(candidate_ids)
            for sig in entry_signals:
                order_manager = await _make_order_manager(sig.stock_id)
                result = await order_manager.execute_entry(sig)

                if self._notifier.is_enabled:
                    await self._notifier.notify_signal(
                        SignalNotification(
                            symbol=sig.symbol,
                            signal_type=sig.signal_type,
                            price=sig.price,
                            atr_n=sig.atr_n,
                            stop_loss=sig.stop_loss,
                            system=sig.system,
                        )
                    )

                    if result.success:
                        await self._notifier.notify_order(
                            OrderNotification(
                                symbol=sig.symbol,
                                side="BUY",
                                quantity=result.quantity,
                                price=result.filled_price or sig.price,
                                order_id=result.order_id,
                                success=result.success,
                                message=result.message,
                            )
                        )

            logger.info(
                "signal_check_complete",
                exits=len(exit_signals),
                pyramids=len(pyramid_signals),
                entries=len(entry_signals),
            )

    async def run_proximity_fast_poll(self) -> None:
        if not self._proximity_watcher.has_targets:
            return

        poll_interval = self._settings.turtle.fast_poll_interval_seconds
        cycle_interval = self._settings.turtle.signal_check_interval_minutes * 60
        elapsed = 0

        tlog.info(
            "fast_poll_start",
            watched=self._proximity_watcher.watched_count,
            symbols=self._proximity_watcher.watched_symbols,
            poll_interval=poll_interval,
        )

        while elapsed < cycle_interval and self._proximity_watcher.has_targets:
            if shutdown_event.is_set():
                break

            async with self._db.session() as session:
                order_repo = OrderRepository(session)
                position_repo = PositionRepository(session)
                signal_repo = SignalRepository(session)
                stock_repo = StockRepository(session)
                position_sizer = PositionSizer(self._settings.risk)
                unit_manager = UnitLimitManager(self._settings.risk, position_repo)

                for watched in self._proximity_watcher.get_watched_list():
                    try:
                        stock = await stock_repo.get_by_id(watched.stock_id)
                        broker = self._broker_for_stock(stock.market) if stock else self._broker
                        order_manager = OrderManager(
                            broker=broker,
                            position_sizer=position_sizer,
                            unit_manager=unit_manager,
                            order_repo=order_repo,
                            position_repo=position_repo,
                            trade_journal=self._journal,
                            stock_name=stock.name if stock else watched.name,
                            stock_market=stock.market if stock else "",
                        )
                        price = await broker.get_current_price(watched.symbol)
                        if price <= 0:
                            continue

                        self._proximity_watcher.update_price(watched.stock_id, price)
                        breakout = self._proximity_watcher.check_breakout(watched.stock_id, price)
                        if breakout and breakout.is_entry:
                            signal = TurtleSignal(
                                symbol=watched.symbol,
                                stock_id=watched.stock_id,
                                signal_type=breakout.breakout_type.value,
                                system=breakout.system,
                                price=price,
                                atr_n=watched.atr_n,
                                stop_loss=price - (watched.atr_n * Decimal("2")),
                                position_size=None,
                                timestamp=datetime.now(),
                                breakout_level=breakout.breakout_level,
                                name=watched.name,
                            )

                            await signal_repo.create(
                                stock_id=signal.stock_id,
                                timestamp=signal.timestamp,
                                signal_type=signal.signal_type,
                                price=signal.price,
                                system=signal.system,
                                atr_n=signal.atr_n,
                            )

                            tlog.info(
                                "fast_poll_breakout_detected",
                                symbol=watched.symbol,
                                name=watched.name,
                                price=float(price),
                                breakout_level=float(breakout.breakout_level)
                                if breakout.breakout_level
                                else None,
                                system=breakout.system,
                            )

                            result = await order_manager.execute_entry(signal)
                            tlog.info(
                                "fast_poll_entry_result",
                                symbol=watched.symbol,
                                success=result.success,
                                quantity=result.quantity,
                                filled_price=float(result.filled_price)
                                if result.filled_price
                                else None,
                                message=result.message,
                            )

                            if self._notifier.is_enabled:
                                await self._notifier.notify_signal(
                                    SignalNotification(
                                        symbol=signal.symbol,
                                        signal_type=f"⚡{signal.signal_type}",
                                        price=signal.price,
                                        atr_n=signal.atr_n,
                                        stop_loss=signal.stop_loss,
                                        system=signal.system,
                                    )
                                )
                                if result.success:
                                    await self._notifier.notify_order(
                                        OrderNotification(
                                            symbol=signal.symbol,
                                            side="BUY",
                                            quantity=result.quantity,
                                            price=result.filled_price or signal.price,
                                            order_id=result.order_id,
                                            success=result.success,
                                            message=f"FastPoll {result.message}",
                                        )
                                    )

                    except Exception as e:
                        logger.warning("fast_poll_error", symbol=watched.symbol, error=str(e))

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        tlog.info("fast_poll_complete", elapsed=elapsed)

    async def run_monitoring(self) -> None:
        logger.debug("running_monitoring")

        async with self._db.session() as session:
            position_repo = PositionRepository(session)

            for broker in self._brokers.values():
                portfolio_mgr = PortfolioManager(
                    broker=broker,
                    position_repo=position_repo,
                )

                triggered = await portfolio_mgr.check_stop_losses()

                for pos in triggered:
                    logger.warning(
                        "stop_loss_alert",
                        symbol=pos.symbol,
                        current_price=float(pos.current_price),
                        stop_loss=float(pos.stop_loss_price) if pos.stop_loss_price else 0,
                    )

    async def generate_daily_report(self) -> None:
        logger.info("generating_daily_report")

        async with self._db.session() as session:
            position_repo = PositionRepository(session)

            total_value = Decimal("0")
            total_pnl = Decimal("0")
            total_positions = 0
            total_units = 0

            for market_key, broker in self._brokers.items():
                portfolio_mgr = PortfolioManager(
                    broker=broker,
                    position_repo=position_repo,
                )

                summary = await portfolio_mgr.get_summary()

                label = market_key.upper()
                print(f"\n[{label}]")
                print(portfolio_mgr.format_summary(summary))

                total_value += summary.total_value
                total_pnl += summary.total_unrealized_pnl
                total_positions += summary.position_count
                total_units += summary.total_units

            total_pnl_pct = (
                (total_pnl / (total_value - total_pnl))
                if (total_value - total_pnl) > 0
                else Decimal("0")
            )

            closed_positions = await position_repo.get_closed_positions()
            open_pos = await position_repo.get_open_positions()
            perf_stats = PerformanceTracker.calculate(closed_positions, open_pos)

            self._journal.log_daily_summary(perf_stats)

            if self._notifier.is_enabled:
                from src.notification.telegram_bot import DailyReport

                await self._notifier.send_daily_report(
                    DailyReport(
                        date=datetime.now().strftime("%Y-%m-%d"),
                        total_value=total_value,
                        daily_pnl=total_pnl,
                        daily_pnl_pct=total_pnl_pct,
                        open_positions=total_positions,
                        total_units=total_units,
                        signals_generated=0,
                        orders_executed=0,
                        win_rate=perf_stats.win_rate,
                        total_closed_trades=perf_stats.total_trades,
                        win_count=perf_stats.win_count,
                        loss_count=perf_stats.loss_count,
                        avg_holding_days=perf_stats.avg_holding_days,
                        profit_factor=perf_stats.profit_factor,
                    )
                )

    async def run_once(self) -> None:
        await self.initialize()

        try:
            await self.run_premarket()
            await self.run_realtime_signal_check()
            await self.generate_daily_report()
        finally:
            await self.shutdown()

    async def _set_trading_state(self, active: bool) -> None:
        async with self._db.session() as session:
            repo = TradingStateRepository(session)
            if self._market in ["krx", "both"]:
                await repo.set_trading_active("krx", active)
            if self._market in ["us", "both"]:
                await repo.set_trading_active("us", active)

    async def _update_heartbeat(self) -> None:
        async with self._db.session() as session:
            repo = TradingStateRepository(session)
            if self._market in ["krx", "both"]:
                await repo.update_heartbeat("krx")
            if self._market in ["us", "both"]:
                await repo.update_heartbeat("us")

    async def run_scheduled(self) -> None:
        await self.initialize()

        try:
            await self._set_trading_state(active=True)

            self._scheduler.setup_premarket_schedule(
                premarket_func=self.run_premarket,
                market=self._market,
            )

            if self._market in ["krx", "both"]:
                self._scheduler.setup_krx_schedule(
                    trading_func=self.run_signal_check,
                    monitoring_func=self.run_monitoring,
                    daily_report_func=self.generate_daily_report,
                    realtime_trading_func=self.run_realtime_signal_check,
                )

            if self._market in ["us", "both"]:
                self._scheduler.setup_us_schedule(
                    trading_func=self.run_signal_check,
                    monitoring_func=self.run_monitoring,
                    daily_report_func=self.generate_daily_report,
                    realtime_trading_func=self.run_realtime_signal_check,
                )

            self._scheduler.start()

            logger.info("trading_bot_running")
            print("\nTrading bot is running. Press Ctrl+C to stop.\n")

            while not shutdown_event.is_set():
                await self._update_heartbeat()
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=30)
                except asyncio.TimeoutError:
                    pass

        finally:
            await self._set_trading_state(active=False)
            await self.shutdown()


def handle_signal(signum: int, frame: Any) -> None:
    logger.info("shutdown_signal_received", signal=signum)
    shutdown_event.set()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run trading bot")
    parser.add_argument(
        "--market",
        "-m",
        choices=["krx", "us", "both"],
        default="krx",
        help="Market to trade (default: krx)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once instead of scheduled",
    )
    parser.add_argument(
        "--log-level",
        "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Log level (default: INFO)",
    )

    args = parser.parse_args()

    configure_logging(level=args.log_level)

    settings = get_settings()
    if settings.trading_mode == TradingMode.LIVE:
        broker_desc = "KIS 실거래 API"
    elif settings.has_kis_credentials:
        broker_desc = "KIS 모의투자 API"
    else:
        broker_desc = "인메모리 시뮬레이션"

    print(f"\n{'=' * 60}")
    print(f"Turtle-CANSLIM Trading Bot")
    print(f"{'=' * 60}")
    print(f"Mode:   {settings.trading_mode.value.upper()}")
    print(f"Broker: {broker_desc}")
    print(f"Market: {args.market.upper()}")
    print(f"{'=' * 60}\n")

    if settings.trading_mode == TradingMode.LIVE:
        print("⚠️  WARNING: Running in LIVE mode with real money!")
        confirm = input("Type 'YES' to confirm: ")
        if confirm != "YES":
            print("Aborted.")
            sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    bot = TradingBot(market=args.market)

    try:
        if args.once:
            asyncio.run(bot.run_once())
        else:
            asyncio.run(bot.run_scheduled())
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        logger.error("trading_bot_error", error=str(e))
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
