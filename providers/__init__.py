from abc import ABC, abstractmethod


class BaseProvider(ABC):
    @abstractmethod
    async def run(self) -> None:
        """Start the provider's main loop."""

    def register_engine(self, engine) -> None:  # noqa: ANN001
        """Hook called by the engine so providers can subscribe to task updates.

        Override to register callbacks via engine.register_notify_callback().
        The default implementation is a no-op.
        """
