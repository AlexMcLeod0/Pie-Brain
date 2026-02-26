"""Memory tool — LanceDB vector store with sentence-transformers dedup."""
import logging
from pathlib import Path

from tools.base import BaseTool

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.8


class MemoryTool(BaseTool):
    tool_name = "memory"

    async def run_local(self, params: dict) -> None:
        action = params.get("action", "store")
        if action == "query":
            await self._query(params)
        else:
            await self._store(params)

    def get_spawn_cmd(self, params: dict) -> str:
        import json
        return f"python -m tools.memory_runner '{json.dumps(params)}'"

    # ------------------------------------------------------------------
    async def _store(self, params: dict) -> None:
        """Embed content and store in LanceDB, deduplicating on similarity > 0.8. (stub)"""
        content = params.get("content", "")
        source_path = params.get("source_path", "unknown")
        logger.info("Memory store: source=%s len=%d", source_path, len(content))

        # TODO: embed with sentence-transformers, check similarity in LanceDB
        # If similarity > SIMILARITY_THRESHOLD: log and return link to existing entry
        # Otherwise: insert new record
        logger.debug("Memory store stub — LanceDB not yet connected.")

    async def _query(self, params: dict) -> None:
        """Query LanceDB for the nearest neighbours to a text query. (stub)"""
        query_text = params.get("query", "")
        top_k = params.get("top_k", 5)
        logger.info("Memory query: %r (top_k=%d)", query_text, top_k)

        # TODO: embed query, run LanceDB nearest-neighbour search
        logger.debug("Memory query stub — LanceDB not yet connected.")
