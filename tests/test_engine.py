"""Tests for Engine._handle fallback behaviour (routing failure, unknown tool)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.db import Task, TaskStatus
from core.engine import Engine
from core.router import RouterOutput


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_settings(tmp_path):
    s = MagicMock()
    s.db_path = str(tmp_path / "tasks.db")
    s.ollama_model = "test-model"
    s.user_prefs_path = str(tmp_path / "prefs.md")
    s.ollama_base_url = "http://localhost:11434"
    s.ollama_timeout = 10
    s.ollama_max_retries = 1
    s.default_cloud_brain = "claude_code"
    s.guardian_poll_interval = 60
    s.build_semaphores.return_value = (asyncio.Semaphore(1), asyncio.Semaphore(1))
    return s


@pytest.fixture
def engine(fake_settings):
    with patch("core.engine.get_settings", return_value=fake_settings), \
         patch("core.engine.BrainRegistry"):
        return Engine()


def _pending_task(text: str = "hello", task_id: int = 1) -> Task:
    return Task(id=task_id, request_text=text, status=TaskStatus.pending, chat_id=999)


# Shared patches applied in every _handle test
_HANDLE_PATCHES = [
    patch("core.engine.update_task_status", new_callable=AsyncMock),
    patch("core.engine.get_task_by_id", new_callable=AsyncMock),
]


# ---------------------------------------------------------------------------
# Routing failure → query fallback
# ---------------------------------------------------------------------------

async def test_handle_routing_failure_falls_back_to_query(engine):
    """When routing raises, the task is handled by the query tool instead of failing."""
    task = _pending_task("How's it hanging?")

    mock_tool_instance = AsyncMock()
    mock_tool_cls = MagicMock(return_value=mock_tool_instance)

    with patch("core.engine.update_task_status", new_callable=AsyncMock), \
         patch("core.engine.get_task_by_id", new_callable=AsyncMock), \
         patch.object(engine.router, "route", side_effect=RuntimeError("bad JSON")), \
         patch.dict("tools.TOOL_REGISTRY", {"query": mock_tool_cls}, clear=True):
        await engine._handle(task)

    mock_tool_instance.run_local.assert_awaited_once()
    params = mock_tool_instance.run_local.call_args[0][0]
    assert params["question"] == "How's it hanging?"
    assert params["_task_id"] == task.id


async def test_handle_routing_failure_does_not_mark_failed(engine):
    """A routing fallback completes as done, not failed."""
    task = _pending_task("How's it hanging?")
    captured_statuses: list[TaskStatus] = []

    async def record_status(db, task_id, status, **_kw):
        captured_statuses.append(status)

    mock_tool_cls = MagicMock(return_value=AsyncMock())

    with patch("core.engine.update_task_status", side_effect=record_status), \
         patch("core.engine.get_task_by_id", new_callable=AsyncMock), \
         patch.object(engine.router, "route", side_effect=RuntimeError("timeout")), \
         patch.dict("tools.TOOL_REGISTRY", {"query": mock_tool_cls}, clear=True):
        await engine._handle(task)

    assert TaskStatus.failed not in captured_statuses
    assert TaskStatus.done in captured_statuses


# ---------------------------------------------------------------------------
# Unknown tool name → query fallback
# ---------------------------------------------------------------------------

async def test_handle_unknown_tool_falls_back_to_query(engine):
    """When the router returns an unregistered tool name, query handles it."""
    task = _pending_task("summarise everything")
    bad_output = RouterOutput(tool_name="nonexistent", params={}, handoff=False)

    mock_tool_instance = AsyncMock()
    mock_tool_cls = MagicMock(return_value=mock_tool_instance)

    with patch("core.engine.update_task_status", new_callable=AsyncMock), \
         patch("core.engine.get_task_by_id", new_callable=AsyncMock), \
         patch.object(engine.router, "route", new=AsyncMock(return_value=bad_output)), \
         patch.dict("tools.TOOL_REGISTRY", {"query": mock_tool_cls}, clear=True):
        await engine._handle(task)

    mock_tool_instance.run_local.assert_awaited_once()
    params = mock_tool_instance.run_local.call_args[0][0]
    assert params["question"] == "summarise everything"


async def test_handle_unknown_tool_no_query_fallback_fails(engine):
    """If query is also missing from the registry, the task fails cleanly."""
    task = _pending_task("do something weird")
    bad_output = RouterOutput(tool_name="ghost_tool", params={}, handoff=False)
    captured_statuses: list[TaskStatus] = []

    async def record_status(db, task_id, status, **_kw):
        captured_statuses.append(status)

    with patch("core.engine.update_task_status", side_effect=record_status), \
         patch("core.engine.get_task_by_id", new_callable=AsyncMock), \
         patch.object(engine.router, "route", new=AsyncMock(return_value=bad_output)), \
         patch.dict("tools.TOOL_REGISTRY", {}, clear=True):
        await engine._handle(task)

    assert TaskStatus.failed in captured_statuses
