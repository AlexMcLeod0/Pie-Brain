"""Memory tool — LanceDB vector store with sentence-transformers dedup."""
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import lancedb
import pyarrow as pa

from config.settings import get_settings
from core.db import atomic_write
from tools.base import BaseTool

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.8
TABLE_NAME = "memories"
CONTENT_TRUNCATE = 600

# Module-level encoder singleton — loading is expensive on Pi 4.
_encoder = None
_encoder_model: str = ""


def _get_encoder(model_name: str):
    global _encoder, _encoder_model
    if _encoder is None or _encoder_model != model_name:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model: %s", model_name)
        _encoder = SentenceTransformer(model_name)
        _encoder_model = model_name
    return _encoder


def _embed(text: str, model_name: str) -> list[float]:
    """Return a normalised embedding vector for *text*."""
    enc = _get_encoder(model_name)
    return enc.encode(text, normalize_embeddings=True).tolist()


def _get_or_create_table(db, dim: int):
    if TABLE_NAME in db.list_tables():
        return db.open_table(TABLE_NAME)
    schema = pa.schema([
        pa.field("vector", pa.list_(pa.float32(), dim)),
        pa.field("content", pa.large_utf8()),
        pa.field("source_path", pa.utf8()),
        pa.field("created_at", pa.utf8()),
    ])
    return db.create_table(TABLE_NAME, schema=schema)


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
        """Embed content and store in LanceDB, deduplicating on similarity > 0.8."""
        content = params.get("content", "")
        source_path = params.get("source_path", "unknown")

        if not content:
            raise ValueError("Memory store requires 'content' in params")

        logger.info("Memory store: source=%s len=%d", source_path, len(content))
        settings = get_settings()

        result = await asyncio.to_thread(
            self._store_sync,
            content, source_path,
            settings.memory_db_path, settings.memory_embedding_model,
        )

        if result["duplicate"]:
            logger.info(
                "Duplicate detected (similarity=%.3f) — skipping. "
                "Existing: source=%s stored=%s",
                result["similarity"],
                result["existing_source"],
                result["existing_created_at"],
            )
        else:
            logger.info("Memory stored (source=%s).", source_path)

    async def _query(self, params: dict) -> None:
        """Query LanceDB for the nearest neighbours to a text query."""
        query_text = params.get("query", "")
        top_k = params.get("top_k", 5)

        if not query_text:
            raise ValueError("Memory query requires 'query' in params")

        logger.info("Memory query: %r (top_k=%d)", query_text, top_k)
        settings = get_settings()

        results = await asyncio.to_thread(
            self._query_sync,
            query_text, top_k,
            settings.memory_db_path, settings.memory_embedding_model,
        )

        content = self._format_results(query_text, results)
        task_id = params.get("_task_id")
        prefix = f"{task_id}_" if task_id is not None else ""
        out_path = Path(settings.brain_inbox) / f"{prefix}memory_query.md"
        atomic_write(out_path, content)
        logger.info("Memory query results written to %s", out_path)

    # ------------------------------------------------------------------
    # Synchronous workers — run in thread pool via asyncio.to_thread
    # ------------------------------------------------------------------

    def _store_sync(
        self,
        content: str,
        source_path: str,
        db_path: str,
        model_name: str,
    ) -> dict:
        vec = _embed(content, model_name)
        db = lancedb.connect(db_path)
        table = _get_or_create_table(db, len(vec))

        if table.count_rows() > 0:
            hits = (
                table.search(vec)
                .metric("cosine")
                .limit(1)
                .to_list()
            )
            if hits:
                similarity = 1.0 - hits[0]["_distance"]
                if similarity >= SIMILARITY_THRESHOLD:
                    return {
                        "duplicate": True,
                        "similarity": similarity,
                        "existing_source": hits[0].get("source_path", "unknown"),
                        "existing_created_at": hits[0].get("created_at", "unknown"),
                    }

        table.add([{
            "vector": vec,
            "content": content,
            "source_path": source_path,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        }])
        return {"duplicate": False}

    def _query_sync(
        self,
        query_text: str,
        top_k: int,
        db_path: str,
        model_name: str,
    ) -> list[dict]:
        db = lancedb.connect(db_path)

        if TABLE_NAME not in db.list_tables():
            logger.warning("Memory table does not exist yet — no results.")
            return []

        table = db.open_table(TABLE_NAME)
        if table.count_rows() == 0:
            return []

        vec = _embed(query_text, model_name)
        hits = (
            table.search(vec)
            .metric("cosine")
            .limit(top_k)
            .to_list()
        )

        return [
            {
                "content": h["content"],
                "source_path": h["source_path"],
                "created_at": h["created_at"],
                "similarity": 1.0 - h["_distance"],
            }
            for h in hits
        ]

    # ------------------------------------------------------------------

    def _format_results(self, query_text: str, results: list[dict]) -> str:
        lines: list[str] = [f"# Memory Query: {query_text!r}", ""]

        if not results:
            lines.append("_No memories found._")
            return "\n".join(lines)

        lines += [f"_{len(results)} result(s)_", ""]

        for i, r in enumerate(results, 1):
            snippet = r["content"]
            if len(snippet) > CONTENT_TRUNCATE:
                snippet = snippet[:CONTENT_TRUNCATE] + "…"
            lines += [
                f"## {i}. {r['source_path']}",
                f"**Similarity:** {r['similarity']:.3f}  ",
                f"**Stored:** {r['created_at']}  ",
                "",
                snippet,
                "",
                "---",
                "",
            ]

        return "\n".join(lines)
