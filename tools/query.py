"""Query tool — answers questions using previous task results as context."""
import asyncio
import logging
from pathlib import Path

import ollama

from config.settings import get_settings
from core.utils import atomic_write
from tools.base import BaseTool, CloudBrainFallback

logger = logging.getLogger(__name__)

CONTEXT_CHARS = 6000   # max chars of context fed to the LLM
MAX_INBOX_FILES = 5    # cap on how many inbox files to pull into context
MIN_KEYWORD_LEN = 4    # ignore short words (the, is, a, …) when scoring
MAX_MEMORY_HITS = 3    # cap on LanceDB memory results included in context
MEMORY_MIN_SIMILARITY = 0.4  # below this, memories are too distant to include

SYSTEM_PROMPT = (
    "You are a knowledgeable assistant with access to previous research results. "
    "Answer the user's question concisely and accurately using the provided context. "
    "If the context does not contain relevant information, answer from your own "
    "knowledge and say so briefly."
)


class QueryTool(BaseTool):
    tool_name = "query"
    required = True
    routing_description = (
        "answer a question about previous results or casual conversation; "
        'params must include {"question": "<the user\'s full message>"}'
    )
    routing_examples = [
        (
            "What did you find about transformer architecture?",
            '{"question": "What did you find about transformer architecture?"}',
        ),
        (
            "How's it hanging?",
            '{"question": "How\'s it hanging?"}',
        ),
    ]

    async def run_local(self, params: dict) -> str:
        question = params.get("question", "").strip()
        task_id = params.get("_task_id", 0)
        if not question:
            raise ValueError("query tool requires a non-empty 'question' param")

        settings = get_settings()

        # Gather context from inbox files (keyword) and LanceDB (semantic)
        inbox_context = self._gather_context(question, settings.brain_inbox)
        memory_context = await self._query_memory(question, settings)

        context_parts = [p for p in (inbox_context, memory_context) if p]
        context = "\n\n".join(context_parts)

        answer = await self._ask_ollama(question, context, settings)

        out_path = Path(settings.brain_inbox) / f"{task_id}_query.md"
        atomic_write(out_path, f"# {question}\n\n{answer}\n")
        logger.info("Query #%d answered, output → %s", task_id, out_path)
        return answer

    # ------------------------------------------------------------------
    # Context gathering — inbox files (keyword-scored)
    # ------------------------------------------------------------------

    def _gather_context(self, question: str, inbox_path: str) -> str:
        """Return relevant inbox file content as a context string.

        Files are scored by keyword overlap with *question*; ties preserve
        recency (the initial sort is by mtime descending, and Python's sort
        is stable so equal-score files stay newest-first).
        """
        inbox = Path(inbox_path)
        if not inbox.exists():
            return ""

        keywords = {w for w in question.lower().split() if len(w) >= MIN_KEYWORD_LEN}

        # Sort newest-first so recency is the tiebreaker
        candidates = sorted(inbox.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)

        scored: list[tuple[int, str, str]] = []  # (score, filename, content)
        for f in candidates:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            name_score = sum(1 for kw in keywords if kw in f.stem.lower())
            content_score = sum(1 for kw in keywords if kw in content[:2000].lower())
            scored.append((name_score + content_score, f.name, content))

        scored.sort(key=lambda x: x[0], reverse=True)

        parts: list[str] = []
        total = 0
        for _, fname, content in scored[:MAX_INBOX_FILES]:
            if total >= CONTEXT_CHARS:
                break
            chunk = content[: CONTEXT_CHARS - total]
            parts.append(f"--- {fname} ---\n{chunk}")
            total += len(chunk)

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Context gathering — LanceDB vector memory (semantic)
    # ------------------------------------------------------------------

    async def _query_memory(self, question: str, settings) -> str:
        """Return semantically relevant stored memories as a context block.

        Skipped silently if the memory DB doesn't exist or is empty.
        Uses the same embedding singleton as MemoryTool to avoid loading
        SentenceTransformer twice on the Pi.
        """
        try:
            results = await asyncio.to_thread(
                self._query_memory_sync,
                question,
                settings.memory_db_path,
                settings.memory_embedding_model,
            )
        except Exception:
            logger.warning("Memory vector search failed; skipping.", exc_info=True)
            return ""

        if not results:
            return ""

        lines = ["--- stored memories ---"]
        for r in results:
            lines.append(f"[relevance={r['similarity']:.2f}] {r['content']}")
        logger.debug("Memory context: %d hit(s) for %r", len(results), question)
        return "\n".join(lines)

    def _query_memory_sync(
        self, query_text: str, db_path: str, model_name: str
    ) -> list[dict]:
        """Blocking LanceDB search — called via asyncio.to_thread."""
        import lancedb
        from tools.memory import TABLE_NAME, _embed  # reuse module-level encoder singleton

        db = lancedb.connect(db_path)
        if TABLE_NAME not in db.list_tables():
            return []

        table = db.open_table(TABLE_NAME)
        if table.count_rows() == 0:
            return []

        vec = _embed(query_text, model_name)
        hits = (
            table.search(vec)
            .metric("cosine")
            .limit(MAX_MEMORY_HITS)
            .to_list()
        )

        return [
            {"content": h["content"], "similarity": 1.0 - h["_distance"]}
            for h in hits
            if (1.0 - h["_distance"]) >= MEMORY_MIN_SIMILARITY
        ]

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    async def _ask_ollama(self, question: str, context: str, settings) -> str:
        client = ollama.AsyncClient(host=settings.ollama_base_url)
        user_content = (
            f"Context:\n{context}\n\nQuestion: {question}" if context else question
        )
        try:
            response = await asyncio.wait_for(
                client.chat(
                    model=settings.ollama_model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                ),
                timeout=settings.ollama_timeout,
            )
            return response["message"]["content"].strip()
        except Exception as exc:
            logger.warning(
                "Local inference failed for question %r (%s); flagging for cloud brain",
                question, exc,
            )
            raise CloudBrainFallback(str(exc)) from exc
