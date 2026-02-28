"""Async hot-module watcher — detects new .py files at runtime."""
import asyncio
import logging
import shutil
from pathlib import Path

from guardian import smoke_test

logger = logging.getLogger(__name__)

_WATCH_DIRS = ("tools", "brains", "providers")
_QUARANTINE_DIR = Path("~/.pie-brain/quarantine").expanduser()


def _snapshot(base: Path) -> dict[Path, float]:
    """Return {path: mtime} for all .py files in watched dirs."""
    result: dict[Path, float] = {}
    for sub in _WATCH_DIRS:
        d = base / sub
        if d.exists():
            for p in d.glob("*.py"):
                if p.name not in ("__init__.py", "base.py", "registry.py"):
                    result[p] = p.stat().st_mtime
    return result


def _new_files(known: dict[Path, float], base: Path) -> list[Path]:
    """Return paths present on disk but not (yet) in *known*."""
    new: list[Path] = []
    for sub in _WATCH_DIRS:
        d = base / sub
        if d.exists():
            for p in d.glob("*.py"):
                if p.name not in ("__init__.py", "base.py", "registry.py"):
                    if p not in known:
                        new.append(p)
    return new


def _quarantine(path: Path) -> None:
    """Move *path* to the quarantine directory."""
    _QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    dest = _QUARANTINE_DIR / path.name
    try:
        shutil.move(str(path), dest)
        logger.error("Guardian: quarantined %s → %s", path, dest)
    except OSError as exc:
        logger.error("Guardian: failed to quarantine %s: %s", path, exc)


def _hot_register(path: Path, tool_registry: dict, brain_registry) -> None:
    """Add a successfully smoke-tested module to the appropriate registry."""
    from tools.base import BaseTool
    from brains.base import BaseBrain

    parent = path.parent.name
    stem = path.stem

    if parent == "tools":
        import importlib
        try:
            mod = importlib.import_module(f"tools.{stem}")
        except ImportError:
            return
        for cls in BaseTool.__subclasses__():
            if cls.__module__ == f"tools.{stem}" and cls.tool_name:
                tool_registry[cls.tool_name] = cls
                logger.info("Guardian: hot-registered tool %r", cls.tool_name)

    elif parent == "brains":
        import importlib
        try:
            mod = importlib.import_module(f"brains.{stem}")
        except ImportError:
            return
        for cls in BaseBrain.__subclasses__():
            if cls.__module__ == f"brains.{stem}" and cls.brain_name:
                brain_registry._registry[cls.brain_name] = cls
                logger.info("Guardian: hot-registered brain %r", cls.brain_name)


async def watch_for_new_modules(
    tool_registry: dict,
    brain_registry,
    base_dir: Path | None = None,
    poll_interval: int = 60,
) -> None:
    """
    Async task that polls for new .py files in tools/, brains/, providers/.

    New files are smoke-tested; passing files are hot-registered, failing files
    are moved to ~/.pie-brain/quarantine/.
    """
    if base_dir is None:
        base_dir = Path(__file__).parent.parent  # project root

    known = _snapshot(base_dir)
    logger.info("Guardian watcher started (poll_interval=%ds)", poll_interval)

    while True:
        await asyncio.sleep(poll_interval)
        for path in _new_files(known, base_dir):
            logger.info("Guardian: new module detected: %s", path)
            result = await smoke_test.run(path)
            if result.ok:
                _hot_register(path, tool_registry, brain_registry)
                logger.info("Guardian: hot-registered %s", path.name)
            else:
                _quarantine(path)
                logger.error("Guardian: quarantined %s — %s", path.name, result.reason)
            known[path] = path.stat().st_mtime if path.exists() else 0.0
