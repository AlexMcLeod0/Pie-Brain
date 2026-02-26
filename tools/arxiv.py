"""ArXiv tool — specific search and daily discover."""
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config.settings import get_settings
from core.db import atomic_write
from tools.base import BaseTool

logger = logging.getLogger(__name__)


class ArxivTool(BaseTool):
    tool_name = "arxiv"

    async def run_local(self, params: dict) -> None:
        mode = params.get("mode", "search")
        if mode == "discover":
            await self._daily_discover(params)
        else:
            await self._specific_search(params)

    def get_spawn_cmd(self, params: dict) -> str:
        import json
        params_json = json.dumps(params)
        return f"python -m tools.arxiv_runner '{params_json}'"

    # ------------------------------------------------------------------
    async def _specific_search(self, params: dict) -> None:
        """Search ArXiv by paper ID or title keywords. (stub)"""
        query = params.get("query", "")
        paper_id = params.get("id", "")
        logger.info("ArXiv specific search: id=%r query=%r", paper_id, query)

        # TODO: call arxiv API / arxiv-python library
        content = f"# ArXiv Search: {query or paper_id}\n\n_Stub — results will appear here._\n"
        self._write_output(f"arxiv_search_{paper_id or 'query'}.md", content)

    async def _daily_discover(self, params: dict) -> None:
        """Fetch papers from the last 24 h matching user interests. (stub)"""
        since = datetime.now(tz=timezone.utc) - timedelta(hours=24)
        logger.info("ArXiv daily discover since %s", since.isoformat())

        # TODO: query arxiv API for recent submissions
        content = (
            f"# ArXiv Daily Discover\n"
            f"_Generated: {datetime.now(tz=timezone.utc).isoformat()}_\n\n"
            "_Stub — discovered papers will appear here._\n"
        )
        self._write_output("arxiv_daily_discover.md", content)

    def _write_output(self, filename: str, content: str) -> None:
        settings = get_settings()
        out_path = Path(settings.brain_inbox) / filename
        atomic_write(out_path, content)
        logger.info("ArXiv output written to %s", out_path)
