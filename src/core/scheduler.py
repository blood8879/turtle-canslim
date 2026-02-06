from __future__ import annotations

import asyncio
from datetime import datetime, time
from typing import Callable, Coroutine, Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.core.config import Settings, Market, get_settings
from src.core.logger import get_logger

logger = get_logger(__name__)

KST = ZoneInfo("Asia/Seoul")
EST = ZoneInfo("America/New_York")


class TradingScheduler:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._scheduler = AsyncIOScheduler()
        self._jobs: dict[str, str] = {}

    @property
    def is_running(self) -> bool:
        return self._scheduler.running

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("scheduler_started")

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("scheduler_stopped")

    def add_job(
        self,
        job_id: str,
        func: Callable[..., Coroutine[Any, Any, Any]],
        trigger: CronTrigger,
        **kwargs: Any,
    ) -> None:
        if job_id in self._jobs:
            self._scheduler.remove_job(job_id)

        self._scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            **kwargs,
        )
        self._jobs[job_id] = job_id
        logger.info("job_added", job_id=job_id)

    def remove_job(self, job_id: str) -> None:
        if job_id in self._jobs:
            self._scheduler.remove_job(job_id)
            del self._jobs[job_id]
            logger.info("job_removed", job_id=job_id)

    def setup_data_update_schedule(
        self,
        data_update_func: Callable[..., Coroutine[Any, Any, Any]],
    ) -> None:
        self.add_job(
            "krx_data_update",
            data_update_func,
            CronTrigger(
                hour=7,
                minute=30,
                day_of_week="mon-fri",
                timezone=KST,
            ),
            kwargs={"market": "krx"},
        )

        self.add_job(
            "us_data_update",
            data_update_func,
            CronTrigger(
                hour=20,
                minute=0,
                day_of_week="mon-fri",
                timezone=KST,
            ),
            kwargs={"market": "us"},
        )

        logger.info("data_update_schedule_configured")

    def setup_krx_schedule(
        self,
        screening_func: Callable[..., Coroutine[Any, Any, Any]],
        trading_func: Callable[..., Coroutine[Any, Any, Any]],
        monitoring_func: Callable[..., Coroutine[Any, Any, Any]],
        daily_report_func: Callable[..., Coroutine[Any, Any, Any]],
        realtime_trading_func: Callable[..., Coroutine[Any, Any, Any]] | None = None,
    ) -> None:
        schedule = self._settings.schedule.krx
        interval = self._settings.turtle.signal_check_interval_minutes

        screening_hour, screening_min = map(int, schedule.screening_time.split(":"))
        self.add_job(
            "krx_screening",
            screening_func,
            CronTrigger(
                hour=screening_hour,
                minute=screening_min,
                day_of_week="mon-fri",
                timezone=KST,
            ),
        )

        signal_func = realtime_trading_func or trading_func
        self.add_job(
            "krx_realtime_signals",
            signal_func,
            CronTrigger(
                hour="9-15",
                minute=f"*/{interval}",
                day_of_week="mon-fri",
                timezone=KST,
            ),
        )

        self.add_job(
            "krx_monitoring",
            monitoring_func,
            CronTrigger(
                hour="9-15",
                minute="*/5",
                day_of_week="mon-fri",
                timezone=KST,
            ),
        )

        close_hour, close_min = map(int, schedule.market_close.split(":"))
        report_min = (close_min + 30) % 60
        report_hour = close_hour + (close_min + 30) // 60
        self.add_job(
            "krx_daily_report",
            daily_report_func,
            CronTrigger(
                hour=report_hour,
                minute=report_min,
                day_of_week="mon-fri",
                timezone=KST,
            ),
        )

        logger.info(
            "krx_schedule_configured",
            signal_interval_minutes=interval,
        )

    def setup_us_schedule(
        self,
        screening_func: Callable[..., Coroutine[Any, Any, Any]],
        trading_func: Callable[..., Coroutine[Any, Any, Any]],
        monitoring_func: Callable[..., Coroutine[Any, Any, Any]],
        daily_report_func: Callable[..., Coroutine[Any, Any, Any]],
        realtime_trading_func: Callable[..., Coroutine[Any, Any, Any]] | None = None,
    ) -> None:
        schedule = self._settings.schedule.us
        interval = self._settings.turtle.signal_check_interval_minutes

        screening_hour, screening_min = map(int, schedule.screening_time.split(":"))
        self.add_job(
            "us_screening",
            screening_func,
            CronTrigger(
                hour=screening_hour,
                minute=screening_min,
                day_of_week="mon-fri",
                timezone=KST,
            ),
        )

        signal_func = realtime_trading_func or trading_func
        self.add_job(
            "us_realtime_signals",
            signal_func,
            CronTrigger(
                hour="9-15",
                minute=f"*/{interval}",
                day_of_week="mon-fri",
                timezone=EST,
            ),
        )

        self.add_job(
            "us_monitoring",
            monitoring_func,
            CronTrigger(
                hour="9-16",
                minute="*/5",
                day_of_week="mon-fri",
                timezone=EST,
            ),
        )

        self.add_job(
            "us_daily_report",
            daily_report_func,
            CronTrigger(
                hour=16,
                minute=30,
                day_of_week="mon-fri",
                timezone=EST,
            ),
        )

        logger.info(
            "us_schedule_configured",
            signal_interval_minutes=interval,
        )

    def is_krx_market_open(self) -> bool:
        now = datetime.now(KST)

        if now.weekday() >= 5:
            return False

        schedule = self._settings.schedule.krx
        open_hour, open_min = map(int, schedule.market_open.split(":"))
        close_hour, close_min = map(int, schedule.market_close.split(":"))

        market_open = time(open_hour, open_min)
        market_close = time(close_hour, close_min)
        current_time = now.time()

        return market_open <= current_time <= market_close

    def is_us_market_open(self) -> bool:
        now = datetime.now(EST)

        if now.weekday() >= 5:
            return False

        market_open = time(9, 30)
        market_close = time(16, 0)
        current_time = now.time()

        return market_open <= current_time <= market_close

    def get_next_market_open(self, market: str = "krx") -> datetime | None:
        if market == "krx":
            tz = KST
            schedule = self._settings.schedule.krx
        else:
            tz = EST
            schedule = self._settings.schedule.us

        now = datetime.now(tz)
        open_hour, open_min = map(int, schedule.market_open.split(":"))

        next_open = now.replace(hour=open_hour, minute=open_min, second=0, microsecond=0)

        if now.time() >= time(open_hour, open_min) or now.weekday() >= 5:
            days_ahead = 1
            if now.weekday() == 4:
                days_ahead = 3
            elif now.weekday() == 5:
                days_ahead = 2

            from datetime import timedelta
            next_open = next_open + timedelta(days=days_ahead)

        return next_open


async def run_scheduler(scheduler: TradingScheduler) -> None:
    scheduler.start()

    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        scheduler.stop()
