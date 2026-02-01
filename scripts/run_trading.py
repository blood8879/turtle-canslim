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
)
from src.data.auto_fetcher import AutoDataFetcher
from src.screener.canslim import CANSLIMScreener
from src.signals.turtle import TurtleSignalEngine
from src.risk.position_sizing import PositionSizer
from src.risk.unit_limits import UnitLimitManager
from src.execution.paper_broker import PaperBroker
from src.execution.live_broker import LiveBroker
from src.execution.order_manager import OrderManager
from src.execution.portfolio import PortfolioManager
from src.notification.telegram_bot import TelegramNotifier, SignalNotification, OrderNotification

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

        if self._settings.trading_mode == TradingMode.LIVE:
            self._broker = LiveBroker()
        elif self._settings.has_kis_credentials:
            self._broker = LiveBroker()
        else:
            self._broker = PaperBroker(initial_cash=Decimal("100000000"))

    async def initialize(self) -> None:
        logger.info(
            "trading_bot_init",
            mode=self._settings.trading_mode.value,
            market=self._market,
        )

        await self._broker.connect()
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
        await self._broker.disconnect()
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

    async def run_screening(self) -> list[int]:
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
                price = await self._broker.get_current_price(stock.symbol)
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

            order_manager = OrderManager(
                broker=self._broker,
                position_sizer=position_sizer,
                unit_manager=unit_manager,
                order_repo=order_repo,
                position_repo=position_repo,
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

            cycle_elapsed = (datetime.now() - cycle_start).total_seconds()
            tlog.info(
                "signal_cycle_complete",
                exits=len(exit_signals),
                pyramids=len(pyramid_signals),
                entries=len(entry_signals),
                prices_fetched=len(realtime_prices),
                candidates=len(candidate_ids),
                open_positions=len(position_stock_ids),
                elapsed_seconds=round(cycle_elapsed, 2),
            )
            logger.info(
                "realtime_signal_check_complete",
                exits=len(exit_signals),
                pyramids=len(pyramid_signals),
                entries=len(entry_signals),
                prices_fetched=len(realtime_prices),
            )

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

            order_manager = OrderManager(
                broker=self._broker,
                position_sizer=position_sizer,
                unit_manager=unit_manager,
                order_repo=order_repo,
                position_repo=position_repo,
            )

            exit_signals = await signal_engine.check_exit_signals()
            for sig in exit_signals:
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

            pyramid_signals = await signal_engine.check_pyramid_signals()
            for sig in pyramid_signals:
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

    async def run_monitoring(self) -> None:
        logger.debug("running_monitoring")

        async with self._db.session() as session:
            position_repo = PositionRepository(session)
            portfolio_mgr = PortfolioManager(
                broker=self._broker,
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
            portfolio_mgr = PortfolioManager(
                broker=self._broker,
                position_repo=position_repo,
            )

            summary = await portfolio_mgr.get_summary()

            print("\n" + portfolio_mgr.format_summary(summary))

            if self._notifier.is_enabled:
                from src.notification.telegram_bot import DailyReport

                await self._notifier.send_daily_report(
                    DailyReport(
                        date=datetime.now().strftime("%Y-%m-%d"),
                        total_value=summary.total_value,
                        daily_pnl=summary.total_unrealized_pnl,
                        daily_pnl_pct=summary.total_unrealized_pnl_pct,
                        open_positions=summary.position_count,
                        total_units=summary.total_units,
                        signals_generated=0,
                        orders_executed=0,
                    )
                )

    async def run_once(self) -> None:
        await self.initialize()

        try:
            await self.run_data_update()
            await self.run_screening()
            await self.run_realtime_signal_check()
            await self.generate_daily_report()
        finally:
            await self.shutdown()

    async def run_scheduled(self) -> None:
        await self.initialize()

        try:
            self._scheduler.setup_data_update_schedule(
                data_update_func=self.run_data_update,
            )

            if self._market in ["krx", "both"]:
                self._scheduler.setup_krx_schedule(
                    screening_func=self.run_screening,
                    trading_func=self.run_signal_check,
                    monitoring_func=self.run_monitoring,
                    daily_report_func=self.generate_daily_report,
                    realtime_trading_func=self.run_realtime_signal_check,
                )

            if self._market in ["us", "both"]:
                self._scheduler.setup_us_schedule(
                    screening_func=self.run_screening,
                    trading_func=self.run_signal_check,
                    monitoring_func=self.run_monitoring,
                    daily_report_func=self.generate_daily_report,
                    realtime_trading_func=self.run_realtime_signal_check,
                )

            self._scheduler.start()

            logger.info("trading_bot_running")
            print("\nTrading bot is running. Press Ctrl+C to stop.\n")

            await shutdown_event.wait()

        finally:
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
