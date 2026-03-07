"""Async heartbeat / cron provider."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _seconds_until_utc(hour: int, minute: int) -> float:
    """Return seconds from now until the next HH:MM UTC wall-clock occurrence."""
    now = datetime.now(tz=timezone.utc)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


class Scheduler:
    """Enqueues periodic tasks via asyncio.

    Jobs are registered dynamically via add_daily(); the engine starts the
    scheduler and adds jobs in response to provider-submitted 'schedule' tasks.
    No jobs are hardcoded at construction time.
    """

    def __init__(self) -> None:
        self._engine = None  # set by register_engine() before run()
        self._jobs: list[tuple[int, int, str, dict]] = []  # (hour, min, desc, meta)
        self._job_tasks: list[asyncio.Task] = []
        self._running = False

    def register_engine(self, engine) -> None:  # noqa: ANN001
        """Bind the engine; must be called before run()."""
        self._engine = engine

    def add_daily(self, utc_time: str, description: str, metadata: dict) -> None:
        """Register a job that fires once a day at *utc_time* (HH:MM UTC).

        Safe to call before or after run() — if already running the job loop
        is spawned immediately as an asyncio task.
        """
        hour, minute = (int(x) for x in utc_time.split(":"))
        entry = (hour, minute, description, metadata)
        self._jobs.append(entry)
        logger.info("Registered daily job at %s UTC: %s", utc_time, description)
        if self._running:
            t = asyncio.create_task(self._job_loop(*entry))
            self._job_tasks.append(t)

    async def run(self) -> None:
        """Start the scheduler. Stays alive indefinitely to accept new jobs."""
        self._running = True
        for entry in self._jobs:
            t = asyncio.create_task(self._job_loop(*entry))
            self._job_tasks.append(t)
        logger.info("Scheduler started with %d pre-registered job(s).", len(self._job_tasks))
        # Keep-alive loop: engine may add jobs at any time via add_daily()
        while self._running:
            await asyncio.sleep(60)

    async def stop(self) -> None:
        self._running = False
        for t in self._job_tasks:
            t.cancel()
        logger.info("Scheduler stopped.")

    async def _job_loop(
        self, hour: int, minute: int, description: str, metadata: dict
    ) -> None:
        initial_delay = _seconds_until_utc(hour, minute)
        logger.debug(
            "Scheduler: %r fires in %.0fs (next at %02d:%02d UTC)",
            description, initial_delay, hour, minute,
        )
        await asyncio.sleep(initial_delay)
        while self._running:
            logger.info("Scheduler firing: %s", description)
            if self._engine is not None:
                await self._engine.submit_task(description, metadata=metadata)
            else:
                logger.error("Scheduler fired but engine is not registered; dropping job: %s", description)
            await asyncio.sleep(24 * 3600)
