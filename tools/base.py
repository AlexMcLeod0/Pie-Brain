import json
from abc import ABC, abstractmethod


class BaseTool(ABC):
    tool_name: str = ""

    @abstractmethod
    async def run_local(self, params: dict) -> None:
        """Execute the tool locally on the Pi."""

    def get_spawn_cmd(self, params: dict) -> str:
        """Return a shell command to run this tool as a subprocess."""
        params_json = json.dumps(params)
        return f"python -m tools.runner {self.tool_name} local '{params_json}'"
