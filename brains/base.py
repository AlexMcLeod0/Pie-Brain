from abc import ABC, abstractmethod


class BaseBrain(ABC):
    brain_name: str = ""

    @abstractmethod
    def get_spawn_cmd(self, tool_name: str, params: dict) -> str:
        """Return a shell command string that invokes this brain for the given tool/params."""
