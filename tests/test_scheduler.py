"""Tests for providers/scheduler.py."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from providers.scheduler import Scheduler, _seconds_until_utc


# ---------------------------------------------------------------------------
# _seconds_until_utc
# ---------------------------------------------------------------------------

def test_seconds_until_utc_future_time():
    """Target time is 1 hour in the future → delay ≈ 3600s."""
    now = datetime(2026, 2, 26, 10, 0, 0, tzinfo=timezone.utc)
    with patch("providers.scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = now
        delay = _seconds_until_utc(11, 0)
    assert 3590 < delay <= 3600


def test_seconds_until_utc_past_time_wraps_to_next_day():
    """Target time already passed today → wraps to same time tomorrow (~86400s)."""
    now = datetime(2026, 2, 26, 12, 0, 0, tzinfo=timezone.utc)
    with patch("providers.scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = now
        delay = _seconds_until_utc(11, 0)  # 11:00 has passed; next is tomorrow
    assert 82800 <= delay <= 86400


def test_seconds_until_utc_exact_time_wraps():
    """Target time is exactly now → wraps to next day."""
    now = datetime(2026, 2, 26, 0, 0, 0, tzinfo=timezone.utc)
    with patch("providers.scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = now
        delay = _seconds_until_utc(0, 0)
    assert delay > 86390  # ~24h


# ---------------------------------------------------------------------------
# _job_loop — fires after initial delay, then enqueues
# ---------------------------------------------------------------------------

async def test_job_loop_enqueues_after_initial_delay():
    """_job_loop sleeps for the initial delay then calls enqueue_task."""
    settings_mock = AsyncMock()
    settings_mock.db_path = ":memory:"

    enqueued = []

    async def fake_enqueue(db_path, description, metadata):
        enqueued.append(description)

    scheduler = Scheduler.__new__(Scheduler)
    scheduler.settings = settings_mock
    scheduler._running = True

    # Patch initial delay to 0 and the 24h repeat to something large
    # so the loop only fires once before we cancel it
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 2:
            scheduler._running = False

    with patch("providers.scheduler._seconds_until_utc", return_value=0), \
         patch("providers.scheduler.enqueue_task", side_effect=fake_enqueue), \
         patch("providers.scheduler.asyncio.sleep", side_effect=fake_sleep):
        await scheduler._job_loop(0, 0, "test job", {"key": "val"})

    assert "test job" in enqueued
    # First sleep is the initial delay (0), second is the 24h interval
    assert sleep_calls[0] == 0
    assert sleep_calls[1] == 24 * 3600


# ---------------------------------------------------------------------------
# add_daily — stores hour/minute correctly
# ---------------------------------------------------------------------------

def test_add_daily_stores_hour_and_minute():
    with patch("providers.scheduler.get_settings"), \
         patch.object(Scheduler, "add_daily"):  # suppress default job
        s = Scheduler.__new__(Scheduler)
        s._jobs = []
        s._running = False

    s.add_daily("14:30", "Afternoon job", {"x": 1})
    assert s._jobs == [(14, 30, "Afternoon job", {"x": 1})]
