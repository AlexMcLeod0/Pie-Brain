"""Tests for guardian.watcher — async hot-module watcher."""
import asyncio
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from guardian.watcher import _snapshot, _new_files, _quarantine, watch_for_new_modules
from guardian.smoke_test import SmokeResult


# ---------------------------------------------------------------------------
# _snapshot / _new_files
# ---------------------------------------------------------------------------


def test_snapshot_ignores_dunder_files(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "__init__.py").write_text("")
    (tmp_path / "tools" / "base.py").write_text("")
    (tmp_path / "tools" / "my_tool.py").write_text("")

    snap = _snapshot(tmp_path)
    paths = {p.name for p in snap}
    assert "__init__.py" not in paths
    assert "base.py" not in paths
    assert "my_tool.py" in paths


def test_new_files_detects_additions(tmp_path):
    (tmp_path / "tools").mkdir()
    existing = tmp_path / "tools" / "existing.py"
    existing.write_text("")
    known = {existing: existing.stat().st_mtime}

    # Add a new file
    new = tmp_path / "tools" / "new_tool.py"
    new.write_text("")

    found = _new_files(known, tmp_path)
    assert new in found
    assert existing not in found


def test_new_files_ignores_base_and_registry(tmp_path):
    (tmp_path / "brains").mkdir()
    for name in ("base.py", "registry.py", "__init__.py"):
        (tmp_path / "brains" / name).write_text("")

    known: dict = {}
    found = _new_files(known, tmp_path)
    assert found == []


# ---------------------------------------------------------------------------
# _quarantine
# ---------------------------------------------------------------------------


def test_quarantine_moves_file(tmp_path, monkeypatch):
    src = tmp_path / "evil_tool.py"
    src.write_text("bad code")

    quarantine_dir = tmp_path / "quarantine"
    monkeypatch.setattr("guardian.watcher._QUARANTINE_DIR", quarantine_dir)

    _quarantine(src)

    assert not src.exists()
    assert (quarantine_dir / "evil_tool.py").exists()


# ---------------------------------------------------------------------------
# watch_for_new_modules integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watch_registers_passing_module(tmp_path):
    """A module that passes smoke test is hot-registered."""
    (tmp_path / "tools").mkdir()

    tool_registry: dict = {}
    brain_registry = MagicMock()
    brain_registry._registry = {}

    pass_result = SmokeResult(ok=True)

    with (
        patch("guardian.watcher.smoke_test.run", new=AsyncMock(return_value=pass_result)),
        patch("guardian.watcher._hot_register") as mock_register,
        patch("guardian.watcher._quarantine") as mock_quarantine,
    ):
        task = asyncio.create_task(
            watch_for_new_modules(
                tool_registry,
                brain_registry,
                base_dir=tmp_path,
                poll_interval=0,  # immediate poll
            )
        )
        # Yield once so the watcher runs synchronous startup code and takes its
        # initial snapshot (tools/ is empty at this point).
        await asyncio.sleep(0)

        # Create the file AFTER the snapshot so the watcher treats it as new.
        new_tool = tmp_path / "tools" / "cool_tool.py"
        new_tool.write_text("# cool tool")

        # Give the watcher time to complete one poll cycle and process the file.
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    mock_register.assert_called_once()
    mock_quarantine.assert_not_called()


@pytest.mark.asyncio
async def test_watch_quarantines_failing_module(tmp_path):
    """A module that fails smoke test is quarantined."""
    (tmp_path / "tools").mkdir()

    tool_registry: dict = {}
    brain_registry = MagicMock()
    brain_registry._registry = {}

    fail_result = SmokeResult(ok=False, reason="ImportError: broken")

    with (
        patch("guardian.watcher.smoke_test.run", new=AsyncMock(return_value=fail_result)),
        patch("guardian.watcher._hot_register") as mock_register,
        patch("guardian.watcher._quarantine") as mock_quarantine,
    ):
        task = asyncio.create_task(
            watch_for_new_modules(
                tool_registry,
                brain_registry,
                base_dir=tmp_path,
                poll_interval=0,
            )
        )
        # Let the watcher take its initial snapshot before we add the bad file.
        await asyncio.sleep(0)

        bad_tool = tmp_path / "tools" / "bad_tool.py"
        bad_tool.write_text("# bad")

        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    mock_quarantine.assert_called_once_with(bad_tool)
    mock_register.assert_not_called()
