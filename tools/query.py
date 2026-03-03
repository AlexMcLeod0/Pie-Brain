"""Query tool — answers questions using previous task results as context."""
import asyncio
import logging
from pathlib import Path

import ollama

from config.settings import get_settings
from core.db import atomic_write
from tools.base import BaseTool

logger = logging.getLogger(__name__)

CONTEXT_CHARS = 6000   # max chars of context fed to the LLM
MAX_INBOX_FILES = 5    # cap on how many inbox files to pull into context
MIN_KEYWORD_LEN = 4    # ignore short words (the, is, a, …) when scoring

SYSTEM_PROMPT = (
    "You are a knowledgeable assistant with access to previous research results. "
    "Answer the user's question concisely and accurately using the provided context. "
    "If the context does not contain relevant information, answer from your own "
    "knowledge and say so briefly."
)


class QueryTool(BaseTool):
    tool_name = "query"
    routing_description = (
        "answer a question about previous results or casual conversation; "
        'params must include {"question": "<the user\'s full message>"}'
    )

    async def run_local(self, params: dict) -> None:
        question = params.get("question", "").strip()
        task_id = params.get("_task_id", 0)
        if not question:
            raise ValueError("query tool requires a non-empty 'question' param")

        settings = get_settings()
        context = self._gather_context(question, settings.brain_inbox)
        answer = await self._ask_ollama(question, context, settings)

        out_path = Path(settings.brain_inbox) / f"{task_id}_query.md"
        atomic_write(out_path, f"# {question}\n\n{answer}\n")
        logger.info("Query #%d answered, output → %s", task_id, out_path)

    # ------------------------------------------------------------------
    # Context gathering
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
            logger.exception("Ollama error in query tool for question %r", question)
            return f"Error getting answer: {exc}"
