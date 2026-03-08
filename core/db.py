import json
import logging
from enum import Enum
from pathlib import Path
from typing import Any

import aiosqlite
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_text TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending',
    tool_name   TEXT,
    metadata    TEXT    DEFAULT '{}',
    chat_id     INTEGER,
    notified    INTEGER NOT NULL DEFAULT 0,
    result      TEXT,
    attempt     INTEGER NOT NULL DEFAULT 0,
    retry_after TEXT
);
"""


class TaskStatus(str, Enum):
    pending = "pending"
    routing = "routing"
    executing = "executing"
    done = "done"
    failed = "failed"
    dead = "dead"  # exhausted all retry attempts


class Task(BaseModel):
    id: int | None = None
    request_text: str
    status: TaskStatus = TaskStatus.pending
    tool_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    chat_id: int | None = None
    notified: bool = False
    result: str | None = None
    attempt: int = 0
    retry_after: str | None = None  # ISO-8601 UTC; None means "ready now"

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Task":
        return cls(
            id=row["id"],
            request_text=row["request_text"],
            status=TaskStatus(row["status"]),
            tool_name=row["tool_name"],
            metadata=json.loads(row["metadata"] or "{}"),
            chat_id=row["chat_id"],
            notified=bool(row["notified"]),
            result=row["result"],
            attempt=row["attempt"] or 0,
            retry_after=row["retry_after"],
        )


async def init_db(db_path: str) -> None:
    """Create DB file + schema if not present."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(DB_SCHEMA)
        # Migrate existing databases that predate newer columns.
        for migration in (
            "ALTER TABLE tasks ADD COLUMN result TEXT",
            "ALTER TABLE tasks ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE tasks ADD COLUMN retry_after TEXT",
        ):
            try:
                await db.execute(migration)
                await db.commit()
            except aiosqlite.OperationalError:
                pass  # column already exists
    logger.info("Database initialised at %s", db_path)


async def enqueue_task(
    db_path: str,
    request_text: str,
    metadata: dict | None = None,
    chat_id: int | None = None,
) -> int:
    """Insert a new pending task; returns its id."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "INSERT INTO tasks (request_text, status, metadata, chat_id) VALUES (?, ?, ?, ?)",
            (request_text, TaskStatus.pending.value, json.dumps(metadata or {}), chat_id),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def get_pending_tasks(db_path: str) -> list[Task]:
    """Fetch pending tasks that are ready to run (retry_after has elapsed or is unset)."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM tasks
               WHERE status = ?
                 AND (retry_after IS NULL OR retry_after <= strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
               ORDER BY id ASC""",
            (TaskStatus.pending.value,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [Task.from_row(r) for r in rows]


async def reset_for_retry(
    db_path: str,
    task_id: int,
    next_attempt: int,
    retry_after: str,
    metadata: dict | None = None,
) -> None:
    """Reset a failed task back to pending for its next retry attempt."""
    fields = ["status = ?", "attempt = ?", "retry_after = ?"]
    values: list = [TaskStatus.pending.value, next_attempt, retry_after]
    if metadata is not None:
        fields.append("metadata = ?")
        values.append(json.dumps(metadata))
    values.append(task_id)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", values)
        await db.commit()


async def update_task_status(
    db_path: str,
    task_id: int,
    status: TaskStatus,
    tool_name: str | None = None,
    metadata: dict | None = None,
    result: str | None = None,
) -> None:
    """Atomically update a task's status (and optionally tool_name/metadata/result)."""
    fields = ["status = ?"]
    values: list = [status.value]
    if tool_name is not None:
        fields.append("tool_name = ?")
        values.append(tool_name)
    if metadata is not None:
        fields.append("metadata = ?")
        values.append(json.dumps(metadata))
    if result is not None:
        fields.append("result = ?")
        values.append(result)
    values.append(task_id)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        await db.commit()


async def get_task_by_id(db_path: str, task_id: int) -> Task | None:
    """Fetch a single task by id, or None if not found."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cursor:
            row = await cursor.fetchone()
    return Task.from_row(row) if row else None


async def get_completed_unnotified(db_path: str) -> list[Task]:
    """Return done tasks that have a chat_id but haven't been notified yet."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks WHERE status = ? AND chat_id IS NOT NULL AND notified = 0",
            (TaskStatus.done.value,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [Task.from_row(r) for r in rows]


async def mark_notified(db_path: str, task_id: int) -> None:
    """Set notified=1 for a task."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("UPDATE tasks SET notified = 1 WHERE id = ?", (task_id,))
        await db.commit()


async def get_recent_tasks(db_path: str, limit: int = 5) -> list[Task]:
    """Fetch the most recently created tasks, newest first."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
    return [Task.from_row(r) for r in rows]


def setup_logging(log_dir: str, level: int = logging.INFO) -> None:
    """Configure rotating file + stderr logging."""
    import logging.handlers

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        log_path / "pie-brain.log",
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    root.addHandler(stream_handler)
