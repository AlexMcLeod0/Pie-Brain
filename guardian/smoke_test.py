"""Full smoke test for live hot-add of tool modules."""
import asyncio
import importlib
import importlib.util
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from tools.base import BaseTool

logger = logging.getLogger(__name__)


@dataclass
class SmokeResult:
    ok: bool
    reason: str = ""


def _load_module_from_path(path: Path):
    """Dynamically import a module from a file path and return the module object."""
    module_name = f"_guardian_smoke_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec for {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def _find_new_tool_subclass(before: set[type]) -> type[BaseTool] | None:
    """Return the first BaseTool subclass that wasn't present before the import."""
    after = set(BaseTool.__subclasses__())
    new = after - before
    for cls in new:
        if cls.tool_name:
            return cls
    return None


async def run(path: Path) -> SmokeResult:
    """
    Smoke-test a newly discovered tool module at *path*.

    Steps:
      1. Import the module (catch ImportError)
      2. Locate the new BaseTool subclass
      3. Call get_spawn_cmd({}) — must return a non-empty str
      4. In a temp dir with mocked I/O, call run_local({})
    """
    # Snapshot existing subclasses before import
    before: set[type] = set(BaseTool.__subclasses__())

    # Step 1: import
    try:
        _load_module_from_path(path)
    except Exception as exc:
        return SmokeResult(ok=False, reason=f"ImportError: {exc}")

    # Step 2: find new subclass
    tool_cls = _find_new_tool_subclass(before)
    if tool_cls is None:
        return SmokeResult(ok=False, reason="No BaseTool subclass with tool_name found in module")

    try:
        instance = tool_cls()
    except Exception as exc:
        return SmokeResult(ok=False, reason=f"Instantiation failed: {exc}")

    # Step 3: get_spawn_cmd
    try:
        cmd = instance.get_spawn_cmd({})
        if not isinstance(cmd, str) or not cmd.strip():
            return SmokeResult(ok=False, reason="get_spawn_cmd({}) returned empty or non-str")
    except Exception as exc:
        return SmokeResult(ok=False, reason=f"get_spawn_cmd raised: {exc}")

    # Step 4: run_local with mocked I/O
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        mock_targets = [
            "aiohttp.ClientSession",
            "httpx.AsyncClient",
        ]
        patches = []
        for target in mock_targets:
            try:
                p = patch(target, new_callable=MagicMock)
                patches.append(p)
                p.start()
            except (AttributeError, ModuleNotFoundError):
                pass

        # Patch common file-write helpers to redirect to temp dir
        orig_atomic = None
        try:
            from core import db as _db_mod

            orig_atomic = _db_mod.atomic_write

            async def _safe_write(path_arg, content):  # type: ignore[override]
                safe_path = tmp_path / Path(path_arg).name
                await orig_atomic(safe_path, content)

            _db_mod.atomic_write = _safe_write
        except (ImportError, AttributeError):
            pass

        try:
            await instance.run_local({})
        except Exception as exc:
            return SmokeResult(ok=False, reason=f"run_local raised: {exc}")
        finally:
            for p in patches:
                p.stop()
            if orig_atomic is not None:
                try:
                    from core import db as _db_mod
                    _db_mod.atomic_write = orig_atomic
                except (ImportError, AttributeError):
                    pass

    return SmokeResult(ok=True)
