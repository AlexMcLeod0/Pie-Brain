"""Async heartbeat / cron provider."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from config.settings import get_settings
from core.db import enqueue_task

logger = logging.getLogger(__name__)


def _seconds_until_utc(hour: int, minute: int) -> float:
    """Return seconds from now until the next HH:MM UTC wall-clock occurrence."""
    now = datetime.now(tz=timezone.utc)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


class Scheduler:
    """Enqueues periodic tasks via asyncio."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._jobs: list[tuple[int, int, str, dict]] = []  # (hour, minute, desc, meta)
        self._running = False

        # Default job: daily ArXiv discover at midnight UTC
        self.add_daily("00:00", "Daily ArXiv discover", {"tool": "arxiv", "mode": "discover"})

    def add_daily(self, utc_time: str, description: str, metadata: dict) -> None:
        """Register a job that fires once a day at *utc_time* (HH:MM UTC)."""
        hour, minute = (int(x) for x in utc_time.split(":"))
        self._jobs.append((hour, minute, description, metadata))
        logger.debug("Scheduled daily job at %s UTC: %s", utc_time, description)

    async def run(self) -> None:
        self._running = True
        logger.info("Scheduler started with %d job(s).", len(self._jobs))
        tasks = [
            asyncio.create_task(self._job_loop(hour, minute, desc, meta))
            for hour, minute, desc, meta in self._jobs
        ]
        await asyncio.gather(*tasks)

    async def _job_loop(
        self, hour: int, minute: int, description: str, metadata: dict
    ) -> None:
        initial_delay = _seconds_until_utc(hour, minute)
        logger.debug(
            "Scheduler: %r fires in %.0fs (next occurrence at %02d:%02d UTC)",
            description, initial_delay, hour, minute,
        )
        await asyncio.sleep(initial_delay)
        while self._running:
            logger.info("Scheduler firing: %s", description)
            await enqueue_task(self.settings.db_path, description, metadata)
            await asyncio.sleep(24 * 3600)

    async def stop(self) -> None:
        self._running = False
