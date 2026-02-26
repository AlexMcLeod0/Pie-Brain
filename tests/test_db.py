"""Tests for core/db.py task CRUD using an in-memory SQLite database."""
import pytest

from core.db import TaskStatus, enqueue_task, get_pending_tasks, init_db, update_task_status

IN_MEMORY = ":memory:"


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
    # Task should no longer be in pending list
    pending = await get_pending_tasks(db)
    assert len(pending) == 0


async def test_enqueue_with_metadata(db):
    task_id = await enqueue_task(db, "daily discover", metadata={"mode": "discover"})
    tasks = await get_pending_tasks(db)
    task = next(t for t in tasks if t.id == task_id)
    assert task.metadata == {"mode": "discover"}
