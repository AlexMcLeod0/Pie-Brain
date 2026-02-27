"""Tests for tools/git_sync.py (subprocess mocked)."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from tools.git_sync import GitSyncTool


def make_proc(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> AsyncMock:
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate.return_value = (stdout, stderr)
    proc.wait = AsyncMock(return_value=None)
    return proc


# ---------------------------------------------------------------------------
# _run
# ---------------------------------------------------------------------------

async def test_run_returns_stdout_on_success():
    proc = make_proc(stdout=b"hello\n")
    with patch("tools.git_sync.asyncio.create_subprocess_exec", return_value=proc):
        result = await GitSyncTool._run("git", "status", cwd=".")
    assert result == "hello"


async def test_run_raises_on_nonzero_exit():
    proc = make_proc(returncode=1, stderr=b"fatal: not a git repo")
    with patch("tools.git_sync.asyncio.create_subprocess_exec", return_value=proc):
        with pytest.raises(RuntimeError, match="not a git repo"):
            await GitSyncTool._run("git", "pull", cwd=".")


# ---------------------------------------------------------------------------
# _pre_task
# ---------------------------------------------------------------------------

async def test_pre_task_calls_pull_rebase():
    with patch.object(GitSyncTool, "_run", new=AsyncMock(return_value="")) as mock_run:
        await GitSyncTool()._pre_task({"repo_path": "/repo"})
    mock_run.assert_awaited_once_with("git", "pull", "--rebase", cwd="/repo")


async def test_pre_task_propagates_error():
    with patch.object(GitSyncTool, "_run", new=AsyncMock(side_effect=RuntimeError("conflict"))):
        with pytest.raises(RuntimeError, match="conflict"):
            await GitSyncTool()._pre_task({"repo_path": "/repo"})


# ---------------------------------------------------------------------------
# _post_task — branch handling
# ---------------------------------------------------------------------------

async def test_post_task_checks_out_existing_branch():
    """Uses git checkout (no -b) when branch already exists."""
    tool = GitSyncTool()
    mock_run = AsyncMock(return_value="")

    with patch.object(GitSyncTool, "_branch_exists", new=AsyncMock(return_value=True)), \
         patch.object(GitSyncTool, "_run", mock_run):
        await tool._post_task({"repo_path": "/repo", "branch": "feat/x", "message": "msg"})

    cmds = [c.args for c in mock_run.call_args_list]
    assert ("git", "checkout", "feat/x") in cmds
    assert ("git", "checkout", "-b", "feat/x") not in cmds


async def test_post_task_creates_new_branch():
    """Uses git checkout -b when branch does not exist."""
    tool = GitSyncTool()
    mock_run = AsyncMock(return_value="")

    with patch.object(GitSyncTool, "_branch_exists", new=AsyncMock(return_value=False)), \
         patch.object(GitSyncTool, "_run", mock_run):
        await tool._post_task({"repo_path": "/repo", "branch": "feat/new", "message": "msg"})

    cmds = [c.args for c in mock_run.call_args_list]
    assert ("git", "checkout", "-b", "feat/new") in cmds


# ---------------------------------------------------------------------------
# _post_task — staging
# ---------------------------------------------------------------------------

async def test_post_task_stages_specific_paths():
    """Uses git add -- <paths> when params["paths"] is provided."""
    tool = GitSyncTool()
    mock_run = AsyncMock(return_value="")

    with patch.object(GitSyncTool, "_branch_exists", new=AsyncMock(return_value=False)), \
         patch.object(GitSyncTool, "_run", mock_run):
        await tool._post_task({
            "repo_path": "/repo",
            "branch": "b",
            "message": "m",
            "paths": ["src/foo.py", "src/bar.py"],
        })

    cmds = [c.args for c in mock_run.call_args_list]
    assert ("git", "add", "--", "src/foo.py", "src/bar.py") in cmds


async def test_post_task_stages_all_when_no_paths():
    """Falls back to git add -A when params["paths"] is absent."""
    tool = GitSyncTool()
    mock_run = AsyncMock(return_value="")

    with patch.object(GitSyncTool, "_branch_exists", new=AsyncMock(return_value=False)), \
         patch.object(GitSyncTool, "_run", mock_run):
        await tool._post_task({"repo_path": "/repo", "branch": "b", "message": "m"})

    cmds = [c.args for c in mock_run.call_args_list]
    assert ("git", "add", "-A") in cmds


# ---------------------------------------------------------------------------
# _post_task — PR title / body
# ---------------------------------------------------------------------------

async def test_post_task_uses_custom_pr_title_and_body():
    tool = GitSyncTool()
    mock_run = AsyncMock(return_value="")

    with patch.object(GitSyncTool, "_branch_exists", new=AsyncMock(return_value=False)), \
         patch.object(GitSyncTool, "_run", mock_run):
        await tool._post_task({
            "repo_path": "/repo",
            "branch": "b",
            "message": "commit msg",
            "pr_title": "My PR",
            "pr_body": "Details here.",
        })

    cmds = [c.args for c in mock_run.call_args_list]
    assert ("gh", "pr", "create", "--title", "My PR", "--body", "Details here.") in cmds


# ---------------------------------------------------------------------------
# git_sync_runner entry point
# ---------------------------------------------------------------------------

def test_git_sync_runner_calls_run_local():
    import tools.git_sync_runner as runner

    params = {"phase": "pre", "repo_path": "/repo"}
    mock_run_local = AsyncMock()

    def fake_asyncio_run(coro):
        coro.close()

    with patch("tools.git_sync_runner.asyncio.run", side_effect=fake_asyncio_run), \
         patch.object(GitSyncTool, "run_local", mock_run_local), \
         patch("sys.argv", ["git_sync_runner", json.dumps(params)]):
        runner.main()

    mock_run_local.assert_called_once_with(params)
