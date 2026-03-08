import json
from abc import ABC, abstractmethod


class CloudBrainFallback(Exception):
    """Raised by a tool's run_local() to signal that this task exceeds local
    capability and should be re-dispatched to the configured cloud brain.

    The engine catches this specifically in _handle() and calls _spawn_brain()
    rather than marking the task as failed.
    """


class BaseTool(ABC):
    tool_name: str = ""
    routing_description: str = ""  # one-line hint used to build the router system prompt
    # Few-shot examples: list of (user_message, params_json) pairs.
    # The router embeds these verbatim so the model sees concrete input→output patterns.
    routing_examples: list[tuple[str, str]] = []
    # Set to True on tools that are always required and must never be disabled/pruned.
    required: bool = False

    @abstractmethod
    async def run_local(self, params: dict) -> str | None:
        """Execute the tool locally on the Pi. Return a result string to deliver to the user, or None."""

    async def post_task(self, params: dict, result: str | None) -> None:
        """Called by the engine after run_local() succeeds. Override for post-task side-effects.

        Failures here are logged but never propagate — the task is already done.
        """

    def get_spawn_cmd(self, params: dict) -> str:
        """Return a shell command to run this tool as a subprocess."""
        params_json = json.dumps(params)
        return f"python -m tools.runner {self.tool_name} local '{params_json}'"
