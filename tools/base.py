import json
from abc import ABC, abstractmethod


class BaseTool(ABC):
    tool_name: str = ""
    routing_description: str = ""  # one-line hint used to build the router system prompt
    # Few-shot examples: list of (user_message, params_json) pairs.
    # The router embeds these verbatim so the model sees concrete input→output patterns.
    routing_examples: list[tuple[str, str]] = []

    @abstractmethod
    async def run_local(self, params: dict) -> None:
        """Execute the tool locally on the Pi."""

    def get_spawn_cmd(self, params: dict) -> str:
        """Return a shell command to run this tool as a subprocess."""
        params_json = json.dumps(params)
        return f"python -m tools.runner {self.tool_name} local '{params_json}'"
