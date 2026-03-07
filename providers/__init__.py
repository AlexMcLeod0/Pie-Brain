from abc import ABC, abstractmethod


class BaseProvider(ABC):
    @abstractmethod
    async def run(self) -> None:
        """Start the provider's main loop."""

    def register_engine(self, engine) -> None:  # noqa: ANN001
        """Hook called by the engine so providers can subscribe to events.

        Override to register callbacks via engine.register_notify_callback()
        and/or engine.register_broadcast_callback().
        The default implementation is a no-op.
        """

    async def broadcast(self, message: str) -> None:
        """Send an unsolicited system message to all provider recipients.

        Override in concrete providers to deliver the message through their
        channel (e.g. Telegram push).  Default is a no-op so providers that
        have no concept of unsolicited messages don't need to implement it.
        """
