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

    def _build_system_prompt(self) -> str:
        """Build the routing system prompt from whatever tools are in TOOL_REGISTRY.

        Imported lazily so the router never needs updating when tools are added.
        Includes few-shot examples from each tool's routing_examples attribute so
        the model sees concrete input→output pairs rather than descriptions alone.
        """
        from tools import TOOL_REGISTRY  # noqa: PLC0415 — intentional lazy import

        tool_names = ", ".join(TOOL_REGISTRY) if TOOL_REGISTRY else "none"
        tool_lines = "".join(
            f"  {name}: {cls.routing_description}\n" if cls.routing_description
            else f"  {name}\n"
            for name, cls in TOOL_REGISTRY.items()
        )

        example_lines = ""
        for name, cls in TOOL_REGISTRY.items():
            for user_msg, params_json in cls.routing_examples:
                full = (
                    f'{{"tool_name": "{name}", "params": {params_json}, "handoff": false}}'
                )
                example_lines += f'User: "{user_msg}"\n{full}\n'

        examples_section = f"\nExamples:\n{example_lines}" if example_lines else ""

        return (
            "You are a task router. Given a user request and their preferences, "
            "respond with ONLY a valid JSON object with exactly these keys:\n"
            f'  "tool_name": string  (one of: {tool_names})\n'
            '  "params":    object  (tool-specific parameters)\n'
            '  "handoff":   boolean (true if the task requires cloud brain)\n'
            f"Tools:\n{tool_lines}"
            f"{examples_section}\n"
            "Use handoff=true only for tasks requiring deep reasoning.\n"
            "Do NOT include any explanation or markdown fences."
        )

    def __init__(
        self,
        model: str,
        user_prefs_path: str,
        llm_semaphore: asyncio.Semaphore,
        base_url: str = "http://localhost:11434",
        timeout: float = 300.0,
        max_retries: int = 3,
    ) -> None:
        self.model = model
        self.user_prefs_path = Path(user_prefs_path)
        self.llm_semaphore = llm_semaphore
        self.client = ollama.AsyncClient(host=base_url)
        self.timeout = timeout
        self.max_retries = max_retries

    def _load_user_prefs(self) -> str:
        if self.user_prefs_path.exists():
            return self.user_prefs_path.read_text(encoding="utf-8")
        logger.warning("user_prefs not found at %s", self.user_prefs_path)
        return ""

    async def route(self, request_text: str) -> RouterOutput:
        """Route *request_text* to a tool via Ollama; acquires LLM semaphore.

        Retries up to *max_retries* times on timeout or transient errors, with
        exponential backoff between attempts (1 s, 2 s, 4 s, …).
        """
        user_prefs = self._load_user_prefs()
        prompt = f"{user_prefs}\n\n---\nUser request: {request_text}" if user_prefs else request_text

        last_exc: Exception = RuntimeError("No attempts made")
        for attempt in range(1, self.max_retries + 1):
            try:
                async with self.llm_semaphore:
                    logger.debug(
                        "Calling Ollama model=%s (attempt %d/%d)",
                        self.model, attempt, self.max_retries,
                    )
                    response = await asyncio.wait_for(
                        self.client.chat(
                            model=self.model,
                            messages=[
                                {"role": "system", "content": self._build_system_prompt()},
                                {"role": "user", "content": prompt},
                            ],
                        ),
                        timeout=self.timeout,
                    )
                raw = response["message"]["content"].strip()
                logger.debug("Ollama raw response: %s", raw)
                return self._parse(raw)
            except asyncio.TimeoutError as exc:
                logger.warning(
                    "Ollama timed out after %ss (attempt %d/%d)",
                    self.timeout, attempt, self.max_retries,
                )
                last_exc = exc
            except Exception as exc:
                logger.warning(
                    "Ollama error on attempt %d/%d: %s",
                    attempt, self.max_retries, exc,
                )
                last_exc = exc

            if attempt < self.max_retries:
                backoff = 2 ** (attempt - 1)
                logger.debug("Retrying in %ss…", backoff)
                await asyncio.sleep(backoff)

        raise RuntimeError(
            f"Ollama failed after {self.max_retries} attempt(s)"
        ) from last_exc

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
