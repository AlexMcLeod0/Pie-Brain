"""Auto-loading brain registry."""
import asyncio
import importlib
import pkgutil
import logging
from pathlib import Path

from brains.base import BaseBrain

logger = logging.getLogger(__name__)


class BrainRegistry:
    def __init__(self, cloud_brain_semaphore: asyncio.Semaphore | None = None) -> None:
        self._semaphore = cloud_brain_semaphore
        self._registry: dict[str, type[BaseBrain]] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Import every module in brains/ to trigger subclass registration."""
        pkg_path = str(Path(__file__).parent)
        for info in pkgutil.iter_modules([pkg_path]):
            if info.name not in ("base", "registry"):
                importlib.import_module(f"brains.{info.name}")

        for cls in BaseBrain.__subclasses__():
            if cls.brain_name:
                self._registry[cls.brain_name] = cls
                logger.debug("Brain registered: %s", cls.brain_name)

    def get(self, name: str) -> BaseBrain:
        """Return an instantiated brain by name, injecting the semaphore."""
        brain_cls = self._registry.get(name)
        if brain_cls is None:
            raise KeyError(f"No brain registered under {name!r}. Available: {list(self._registry)}")
        try:
            return brain_cls(cloud_brain_semaphore=self._semaphore)
        except TypeError:
            return brain_cls()

    @property
    def available(self) -> list[str]:
        return list(self._registry.keys())
