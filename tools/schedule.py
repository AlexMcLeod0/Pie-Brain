"""Schedule tool — registers new recurring daily jobs at runtime."""
import logging

from tools.base import BaseTool

logger = logging.getLogger(__name__)


class ScheduleTool(BaseTool):
    """Lets a provider (e.g. Telegram) add a new daily job to the running scheduler.

    The engine calls register_engine() before run_local() so the tool can
    delegate to engine.schedule_daily() without touching the DB or scheduler
    directly.
    """

    tool_name = "schedule"
    routing_description = (
        "Register a new recurring daily job (e.g. 'run an arxiv digest every day at 8am'). "
        "Params: time (HH:MM UTC string), description (human-readable label), "
        "plus any keys that describe the recurring task (e.g. tool, mode)."
    )
    routing_examples = [
        (
            "Schedule a daily ArXiv digest at 8am UTC",
            '{"time": "08:00", "description": "Daily ArXiv digest", "tool": "arxiv", "mode": "discover"}',
        ),
        (
            "Run memory cleanup every night at midnight",
            '{"time": "00:00", "description": "Nightly memory cleanup", "tool": "memory", "mode": "cleanup"}',
        ),
    ]

    def __init__(self) -> None:
        self._engine = None

    def register_engine(self, engine) -> None:  # noqa: ANN001
        self._engine = engine

    async def run_local(self, params: dict) -> str:
        utc_time = params.get("time", "00:00")
        description = params.get("description", "Unnamed job")
        # Pass through any extra keys as the metadata the scheduler will forward
        metadata = {
            k: v for k, v in params.items()
            if k not in ("time", "description", "_task_id")
        }

        if self._engine is None:
            logger.error("ScheduleTool.run_local called without a registered engine.")
            return "Error: scheduler not available."

        self._engine.schedule_daily(utc_time, description, metadata)
        logger.info("Registered daily job via ScheduleTool: %r at %s UTC", description, utc_time)
        return f"Scheduled '{description}' daily at {utc_time} UTC."
