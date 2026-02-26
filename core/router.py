import asyncio
import json
import logging
from pathlib import Path

import ollama
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


class RouterOutput(BaseModel):
    tool_name: str
    params: dict
    handoff: bool


class Router:
    """Calls the local Ollama model to classify a task and produce a RouterOutput."""

    SYSTEM_PROMPT = (
        "You are a task router. Given a user request and their preferences, "
        "respond with ONLY a valid JSON object with exactly these keys:\n"
        '  "tool_name": string  (one of: arxiv, git_sync, memory)\n'
        '  "params":    object  (tool-specific parameters)\n'
        '  "handoff":   boolean (true if the task requires cloud brain)\n'
        "Do NOT include any explanation or markdown fences."
    )

    def __init__(
        self,
        model: str,
        user_prefs_path: str,
        llm_semaphore: asyncio.Semaphore,
        base_url: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self.user_prefs_path = Path(user_prefs_path)
        self.llm_semaphore = llm_semaphore
        self.client = ollama.AsyncClient(host=base_url)

    def _load_user_prefs(self) -> str:
        if self.user_prefs_path.exists():
            return self.user_prefs_path.read_text(encoding="utf-8")
        logger.warning("user_prefs not found at %s", self.user_prefs_path)
        return ""

    async def route(self, request_text: str) -> RouterOutput:
        """Route *request_text* to a tool via Ollama; acquires LLM semaphore."""
        user_prefs = self._load_user_prefs()
        prompt = f"{user_prefs}\n\n---\nUser request: {request_text}" if user_prefs else request_text

        async with self.llm_semaphore:
            logger.debug("Calling Ollama model=%s", self.model)
            response = await self.client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )

        raw = response["message"]["content"].strip()
        logger.debug("Ollama raw response: %s", raw)
        return self._parse(raw)

    def _parse(self, raw: str) -> RouterOutput:
        """Parse raw LLM output into a RouterOutput, raising ValueError on failure."""
        # Strip accidental markdown fences
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                line for line in lines if not line.startswith("```")
            ).strip()
        try:
            data = json.loads(raw)
            return RouterOutput(**data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError(f"Invalid router output: {raw!r}") from exc
