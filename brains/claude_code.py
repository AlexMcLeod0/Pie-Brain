"""Claude Code cloud brain."""
import asyncio
import json
import logging

from brains.base import BaseBrain

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
        return (
            f"You are Pie-Brain's cloud assistant.\n"
            f"Tool requested: {tool_name}\n"
            f"Parameters: {json.dumps(params, indent=2)}\n"
            f"Please complete this task and write any Markdown output to ~/brain/inbox/."
        )
