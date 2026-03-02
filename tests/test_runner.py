"""Tests for the unified tools/runner.py entry point."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import tools.runner as runner_module
from tools.arxiv import ArxivTool
from tools.git_sync import GitSyncTool
from tools.memory import MemoryTool


def fake_asyncio_run(coro):
    coro.close()


@pytest.mark.parametrize("tool_name,tool_cls,params", [
    ("arxiv",    ArxivTool,    {"query": "transformers", "mode": "search"}),
    ("git_sync", GitSyncTool,  {"phase": "pre", "repo_path": "/repo"}),
    ("memory",   MemoryTool,   {"action": "store", "content": "hi", "source_path": "x.md"}),
])
def test_runner_local_calls_run_local(tool_name, tool_cls, params):
    """'local' mode looks up the tool and calls run_local with the parsed params."""
    mock_run_local = AsyncMock()
    with (
        patch("tools.runner.asyncio.run", side_effect=fake_asyncio_run),
        patch.object(tool_cls, "run_local", mock_run_local),
        patch("sys.argv", ["runner", tool_name, "local", json.dumps(params)]),
    ):
        runner_module.main()

    mock_run_local.assert_called_once_with(params)


def test_runner_spawn_calls_brain_get_spawn_cmd():
    """'spawn' mode invokes the configured brain's get_spawn_cmd and executes it."""
    mock_brain = MagicMock()
    mock_brain.get_spawn_cmd.return_value = "claude --print '...'"
    mock_settings = MagicMock()
    mock_settings.default_cloud_brain = "claude_code"
    params = {"query": "transformers"}

    with (
        patch("tools.runner.BrainRegistry") as mock_registry_cls,
        patch("tools.runner.get_settings", return_value=mock_settings),
        patch("tools.runner.subprocess.run"),
        patch("sys.argv", ["runner", "arxiv", "spawn", json.dumps(params)]),
    ):
        mock_registry_cls.return_value.get.return_value = mock_brain
        runner_module.main()

    mock_brain.get_spawn_cmd.assert_called_once_with("arxiv", params)


def test_runner_unknown_tool_exits():
    with patch("sys.argv", ["runner", "nonexistent", "local", "{}"]):
        with pytest.raises(SystemExit) as exc_info:
            runner_module.main()
    assert exc_info.value.code == 1


def test_runner_missing_args_exits():
    with patch("sys.argv", ["runner", "arxiv"]):
        with pytest.raises(SystemExit) as exc_info:
            runner_module.main()
    assert exc_info.value.code == 1


def test_runner_unknown_mode_exits():
    with patch("sys.argv", ["runner", "arxiv", "invalid", "{}"]):
        with pytest.raises(SystemExit) as exc_info:
            runner_module.main()
    assert exc_info.value.code == 1
