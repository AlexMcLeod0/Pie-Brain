"""Claude Code cloud brain."""
import asyncio
import json
import logging

from brains.base import BaseBrain
from config.settings import get_settings

logger = logging.getLogger(__name__)


class ClaudeCodeBrain(BaseBrain):
    brain_name = "claude_code"

    def __init__(self, cloud_brain_semaphore: asyncio.Semaphore | None = None) -> None:
        self._semaphore = cloud_brain_semaphore

    def get_spawn_cmd(self, tool_name: str, params: dict) -> str:
        """Build a `claude` CLI invocation for the given task."""
        prompt = self._build_prompt(tool_name, params)
        # Escape single quotes in the prompt for shell safety
        safe_prompt = prompt.replace("'", "'\\''")
        return f"claude --print '{safe_prompt}'"

    def _build_prompt(self, tool_name: str, params: dict) -> str:
        task_id = params.get("_task_id", "unknown")
        inbox = get_settings().brain_inbox
        return (
            f"You are Pie-Brain's cloud assistant.\n"
            f"Tool requested: {tool_name}\n"
            f"Parameters: {json.dumps(params, indent=2)}\n"
            f"Please complete this task and write your Markdown output to "
            f"{inbox}/{task_id}_result.md"
        )
