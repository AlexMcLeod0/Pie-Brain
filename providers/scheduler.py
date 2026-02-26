"""Async heartbeat / cron provider."""
import asyncio
import logging
from datetime import datetime, timezone

from config.settings import get_settings
from core.db import enqueue_task

logger = logging.getLogger(__name__)


class Scheduler:
    """Enqueues periodic tasks via asyncio."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._jobs: list[tuple[float, str, dict]] = []
        self._running = False

        # Default job: daily ArXiv discover at midnight UTC
        self.add_daily("00:00", "Daily ArXiv discover", {"tool": "arxiv", "mode": "discover"})

    def add_daily(self, utc_time: str, description: str, metadata: dict) -> None:
        """Register a job that fires once a day at *utc_time* (HH:MM)."""
        hour, minute = (int(x) for x in utc_time.split(":"))
        interval = 24 * 3600  # simplification: fire every 24 h
        self._jobs.append((interval, description, metadata))
        logger.debug("Scheduled daily job at %s UTC: %s", utc_time, description)

    async def run(self) -> None:
        self._running = True
        logger.info("Scheduler started with %d job(s).", len(self._jobs))
        tasks = [asyncio.create_task(self._job_loop(interval, desc, meta))
                 for interval, desc, meta in self._jobs]
        await asyncio.gather(*tasks)

    async def _job_loop(self, interval: float, description: str, metadata: dict) -> None:
        while self._running:
            logger.info("Scheduler firing: %s", description)
            await enqueue_task(self.settings.db_path, description, metadata)
            await asyncio.sleep(interval)

    async def stop(self) -> None:
        self._running = False
