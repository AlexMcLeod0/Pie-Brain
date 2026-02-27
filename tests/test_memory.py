"""Tests for tools/memory.py (lancedb and sentence-transformers mocked)."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

import tools.memory as mem_module
from tools.memory import MemoryTool, SIMILARITY_THRESHOLD, TABLE_NAME

# ---------------------------------------------------------------------------
# Constants / shared fixtures
# ---------------------------------------------------------------------------

FAKE_VEC = [0.1, 0.2, 0.3, 0.4]  # 4-dim dummy embedding
FAKE_MODEL = "all-MiniLM-L6-v2"
FAKE_DB_PATH = "/tmp/fake_memory_db"
FAKE_INBOX = "/tmp/fake_inbox"

_EMBED = "tools.memory._embed"
_LANCEDB = "tools.memory.lancedb"
_GET_SETTINGS = "tools.memory.get_settings"
_ATOMIC_WRITE = "tools.memory.atomic_write"
_TO_THREAD = "tools.memory.asyncio.to_thread"


@pytest.fixture
def mock_settings(tmp_path):
    s = MagicMock()
    s.memory_db_path = str(tmp_path / "memory")
    s.memory_embedding_model = FAKE_MODEL
    s.brain_inbox = str(tmp_path / "inbox")
    return s


def make_table(rows: list[dict] | None = None) -> MagicMock:
    """Build a mock LanceDB table with controllable rows."""
    table = MagicMock()
    row_count = len(rows) if rows else 0
    table.count_rows.return_value = row_count

    # Chain: table.search(v).metric("cosine").limit(k).to_list()
    search_chain = MagicMock()
    search_chain.metric.return_value = search_chain
    search_chain.limit.return_value = search_chain
    search_chain.to_list.return_value = rows or []
    table.search.return_value = search_chain

    return table


def make_db(table: MagicMock, table_exists: bool = True) -> MagicMock:
    db = MagicMock()
    db.list_tables.return_value = [TABLE_NAME] if table_exists else []
    db.open_table.return_value = table
    db.create_table.return_value = table
    return db


# ---------------------------------------------------------------------------
# _store — empty table (first insert)
# ---------------------------------------------------------------------------

async def test_store_inserts_when_table_empty(mock_settings):
    table = make_table(rows=[])  # count_rows → 0
    db = make_db(table, table_exists=False)

    with patch(_EMBED, return_value=FAKE_VEC), \
         patch(_LANCEDB + ".connect", return_value=db), \
         patch(_GET_SETTINGS, return_value=mock_settings), \
         patch(_TO_THREAD, new=AsyncMock(side_effect=lambda fn, *a: fn(*a))):
        await MemoryTool()._store({"content": "Hello world", "source_path": "test.md"})

    table.add.assert_called_once()
    added = table.add.call_args[0][0][0]
    assert added["content"] == "Hello world"
    assert added["source_path"] == "test.md"
    assert "created_at" in added


# ---------------------------------------------------------------------------
# _store — duplicate detection
# ---------------------------------------------------------------------------

async def test_store_skips_duplicate(mock_settings):
    """High-similarity hit → no insert."""
    hit = {
        "content": "Hello world",
        "source_path": "original.md",
        "created_at": "2026-01-01T00:00:00+00:00",
        "_distance": 1.0 - 0.95,  # similarity = 0.95 > threshold
    }
    table = make_table(rows=[hit])
    db = make_db(table)

    with patch(_EMBED, return_value=FAKE_VEC), \
         patch(_LANCEDB + ".connect", return_value=db), \
         patch(_GET_SETTINGS, return_value=mock_settings), \
         patch(_TO_THREAD, new=AsyncMock(side_effect=lambda fn, *a: fn(*a))):
        await MemoryTool()._store({"content": "Hello world", "source_path": "new.md"})

    table.add.assert_not_called()


async def test_store_inserts_below_threshold(mock_settings):
    """Low-similarity hit → new record is inserted."""
    hit = {
        "content": "Something completely different",
        "source_path": "other.md",
        "created_at": "2026-01-01T00:00:00+00:00",
        "_distance": 1.0 - 0.5,  # similarity = 0.5 < threshold
    }
    table = make_table(rows=[hit])
    db = make_db(table)

    with patch(_EMBED, return_value=FAKE_VEC), \
         patch(_LANCEDB + ".connect", return_value=db), \
         patch(_GET_SETTINGS, return_value=mock_settings), \
         patch(_TO_THREAD, new=AsyncMock(side_effect=lambda fn, *a: fn(*a))):
        await MemoryTool()._store({"content": "New content", "source_path": "new.md"})

    table.add.assert_called_once()


async def test_store_threshold_is_inclusive(mock_settings):
    """Similarity exactly at threshold is treated as a duplicate."""
    hit = {
        "content": "Borderline",
        "source_path": "border.md",
        "created_at": "2026-01-01T00:00:00+00:00",
        "_distance": 1.0 - SIMILARITY_THRESHOLD,  # exactly at threshold
    }
    table = make_table(rows=[hit])
    db = make_db(table)

    with patch(_EMBED, return_value=FAKE_VEC), \
         patch(_LANCEDB + ".connect", return_value=db), \
         patch(_GET_SETTINGS, return_value=mock_settings), \
         patch(_TO_THREAD, new=AsyncMock(side_effect=lambda fn, *a: fn(*a))):
        await MemoryTool()._store({"content": "Borderline", "source_path": "new.md"})

    table.add.assert_not_called()


async def test_store_raises_on_empty_content(mock_settings):
    with patch(_GET_SETTINGS, return_value=mock_settings):
        with pytest.raises(ValueError, match="requires 'content'"):
            await MemoryTool()._store({"source_path": "test.md"})


# ---------------------------------------------------------------------------
# _query
# ---------------------------------------------------------------------------

async def test_query_writes_results_file(mock_settings, tmp_path):
    mock_settings.brain_inbox = str(tmp_path)
    hit = {
        "content": "Some stored memory content.",
        "source_path": "notes.md",
        "created_at": "2026-01-01T00:00:00+00:00",
        "_distance": 0.1,
    }
    table = make_table(rows=[hit])
    db = make_db(table)

    with patch(_EMBED, return_value=FAKE_VEC), \
         patch(_LANCEDB + ".connect", return_value=db), \
         patch(_GET_SETTINGS, return_value=mock_settings), \
         patch(_TO_THREAD, new=AsyncMock(side_effect=lambda fn, *a: fn(*a))):
        await MemoryTool()._query({"query": "test query", "top_k": 3})

    out = tmp_path / "memory_query.md"
    assert out.exists()
    content = out.read_text()
    assert "test query" in content
    assert "notes.md" in content
    assert "Some stored memory content." in content


async def test_query_no_table_writes_empty_result(mock_settings, tmp_path):
    mock_settings.brain_inbox = str(tmp_path)
    db = make_db(MagicMock(), table_exists=False)

    with patch(_EMBED, return_value=FAKE_VEC), \
         patch(_LANCEDB + ".connect", return_value=db), \
         patch(_GET_SETTINGS, return_value=mock_settings), \
         patch(_TO_THREAD, new=AsyncMock(side_effect=lambda fn, *a: fn(*a))):
        await MemoryTool()._query({"query": "anything"})

    content = (tmp_path / "memory_query.md").read_text()
    assert "No memories found" in content


async def test_query_raises_on_empty_query(mock_settings):
    with patch(_GET_SETTINGS, return_value=mock_settings):
        with pytest.raises(ValueError, match="requires 'query'"):
            await MemoryTool()._query({})


# ---------------------------------------------------------------------------
# _format_results
# ---------------------------------------------------------------------------

def test_format_results_empty():
    out = MemoryTool()._format_results("needle", [])
    assert "No memories found" in out
    assert "needle" in out


def test_format_results_shows_similarity():
    results = [{"content": "abc", "source_path": "x.md", "created_at": "2026-01-01", "similarity": 0.92}]
    out = MemoryTool()._format_results("q", results)
    assert "0.920" in out
    assert "x.md" in out


def test_format_results_truncates_long_content():
    results = [{
        "content": "x" * 700,
        "source_path": "big.md",
        "created_at": "2026-01-01",
        "similarity": 0.8,
    }]
    out = MemoryTool()._format_results("q", results)
    assert "…" in out
    assert "x" * 601 not in out


# ---------------------------------------------------------------------------
# memory_runner entry point
# ---------------------------------------------------------------------------

def test_memory_runner_calls_run_local():
    import json
    import tools.memory_runner as runner

    params = {"action": "store", "content": "hello", "source_path": "x.md"}
    mock_run_local = AsyncMock()

    def fake_asyncio_run(coro):
        coro.close()

    with patch("tools.memory_runner.asyncio.run", side_effect=fake_asyncio_run), \
         patch.object(MemoryTool, "run_local", mock_run_local), \
         patch("sys.argv", ["memory_runner", json.dumps(params)]):
        runner.main()

    mock_run_local.assert_called_once_with(params)
