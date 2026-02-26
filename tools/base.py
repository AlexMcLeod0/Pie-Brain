from abc import ABC, abstractmethod


class BaseTool(ABC):
    tool_name: str = ""

    @abstractmethod
    async def run_local(self, params: dict) -> None:
        """Execute the tool locally on the Pi."""

    @abstractmethod
    def get_spawn_cmd(self, params: dict) -> str:
        """Return a shell command string for cloud-brain handoff."""
