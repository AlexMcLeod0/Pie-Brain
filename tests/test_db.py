"""Tests for core/db.py task CRUD using a temp SQLite database."""
import pytest

from core.db import (
    TaskStatus,
    enqueue_task,
    get_completed_unnotified,
    get_pending_tasks,
    get_task_by_id,
    init_db,
    mark_notified,
    update_task_status,
)


@pytest.fixture
async def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return db_path


async def test_enqueue_returns_id(db):
    task_id = await enqueue_task(db, "Find arxiv papers on LLMs")
    assert isinstance(task_id, int)
    assert task_id >= 1


async def test_get_pending_tasks(db):
    await enqueue_task(db, "task one")
    await enqueue_task(db, "task two")
    tasks = await get_pending_tasks(db)
    assert len(tasks) == 2
    assert all(t.status == TaskStatus.pending for t in tasks)


async def test_update_task_status(db):
    task_id = await enqueue_task(db, "a task")
    await update_task_status(db, task_id, TaskStatus.routing)
    pending = await get_pending_tasks(db)
    assert not any(t.id == task_id for t in pending)


async def test_update_task_with_tool_name(db):
    task_id = await enqueue_task(db, "search arxiv")
    await update_task_status(db, task_id, TaskStatus.executing, tool_name="arxiv")
    pending = await get_pending_tasks(db)
    assert len(pending) == 0


async def test_enqueue_with_metadata(db):
    task_id = await enqueue_task(db, "daily discover", metadata={"mode": "discover"})
    tasks = await get_pending_tasks(db)
    task = next(t for t in tasks if t.id == task_id)
    assert task.metadata == {"mode": "discover"}


async def test_enqueue_stores_chat_id(db):
    task_id = await enqueue_task(db, "hello", chat_id=42)
    task = await get_task_by_id(db, task_id)
    assert task is not None
    assert task.chat_id == 42


async def test_get_task_by_id_missing(db):
    result = await get_task_by_id(db, 9999)
    assert result is None


async def test_get_completed_unnotified(db):
    task_id = await enqueue_task(db, "some task", chat_id=99)
    await update_task_status(db, task_id, TaskStatus.done)
    tasks = await get_completed_unnotified(db)
    assert any(t.id == task_id for t in tasks)
    assert all(not t.notified for t in tasks)


async def test_mark_notified(db):
    task_id = await enqueue_task(db, "notify me", chat_id=99)
    await update_task_status(db, task_id, TaskStatus.done)
    await mark_notified(db, task_id)
    tasks = await get_completed_unnotified(db)
    assert not any(t.id == task_id for t in tasks)


async def test_completed_without_chat_id_not_returned(db):
    task_id = await enqueue_task(db, "no chat id task")
    await update_task_status(db, task_id, TaskStatus.done)
    tasks = await get_completed_unnotified(db)
    assert not any(t.id == task_id for t in tasks)
