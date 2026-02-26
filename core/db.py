import json
import logging
import os
import tempfile
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
    metadata    TEXT    DEFAULT '{}'
);
"""


class TaskStatus(str, Enum):
    pending = "pending"
    routing = "routing"
    executing = "executing"
    done = "done"


class Task(BaseModel):
    id: int | None = None
    request_text: str
    status: TaskStatus = TaskStatus.pending
    tool_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Task":
        return cls(
            id=row["id"],
            request_text=row["request_text"],
            status=TaskStatus(row["status"]),
            tool_name=row["tool_name"],
            metadata=json.loads(row["metadata"] or "{}"),
        )


async def init_db(db_path: str) -> None:
    """Create DB file + schema if not present."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(DB_SCHEMA)
        await db.commit()
    logger.info("Database initialised at %s", db_path)


async def enqueue_task(db_path: str, request_text: str, metadata: dict | None = None) -> int:
    """Insert a new pending task; returns its id."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "INSERT INTO tasks (request_text, status, metadata) VALUES (?, ?, ?)",
            (request_text, TaskStatus.pending.value, json.dumps(metadata or {})),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def get_pending_tasks(db_path: str) -> list[Task]:
    """Fetch all tasks with status=pending."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY id ASC",
            (TaskStatus.pending.value,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [Task.from_row(r) for r in rows]


async def update_task_status(
    db_path: str,
    task_id: int,
    status: TaskStatus,
    tool_name: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Atomically update a task's status (and optionally tool_name/metadata)."""
    async with aiosqlite.connect(db_path) as db:
        if tool_name is not None and metadata is not None:
            await db.execute(
                "UPDATE tasks SET status=?, tool_name=?, metadata=? WHERE id=?",
                (status.value, tool_name, json.dumps(metadata), task_id),
            )
        elif tool_name is not None:
            await db.execute(
                "UPDATE tasks SET status=?, tool_name=? WHERE id=?",
                (status.value, tool_name, task_id),
            )
        else:
            await db.execute(
                "UPDATE tasks SET status=? WHERE id=?",
                (status.value, task_id),
            )
        await db.commit()


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def atomic_write(path: str | Path, content: str) -> None:
    """Write *content* to *path* atomically using a temp file + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise


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
