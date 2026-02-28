from abc import ABC, abstractmethod


class BaseProvider(ABC):
    @abstractmethod
    async def run(self) -> None:
        """Start the provider's main loop."""
