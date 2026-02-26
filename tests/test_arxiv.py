"""Tests for tools/arxiv.py (arxiv API and get_settings mocked)."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.arxiv import ArxivTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Author:
    def __init__(self, name: str) -> None:
        self.name = name


def make_paper(
    title: str = "Test Paper",
    paper_id: str = "2301.00001",
    hours_ago: float = 1.0,
    categories: list[str] | None = None,
    n_authors: int = 2,
) -> MagicMock:
    paper = MagicMock()
    paper.entry_id = f"http://arxiv.org/abs/{paper_id}v1"
    paper.title = title
    paper.authors = [_Author(f"Author {i}") for i in range(n_authors)]
    paper.summary = "A paper about testing things in great detail."
    paper.published = datetime.now(tz=timezone.utc) - timedelta(hours=hours_ago)
    paper.categories = categories or ["cs.LG"]
    paper.pdf_url = f"http://arxiv.org/pdf/{paper_id}v1"
    return paper


def fake_to_thread(fn, *args, **kwargs):
    """Synchronous stand-in for asyncio.to_thread used in tests."""
    return fn(*args, **kwargs)


# Patch target shared across tests
_TO_THREAD = "tools.arxiv.asyncio.to_thread"
_GET_SETTINGS = "tools.arxiv.get_settings"


@pytest.fixture
def mock_settings(tmp_path):
    s = MagicMock()
    s.brain_inbox = str(tmp_path)
    s.arxiv_discover_keywords = ["machine learning"]
    return s


# ---------------------------------------------------------------------------
# _specific_search
# ---------------------------------------------------------------------------

async def test_specific_search_by_query_writes_file(tmp_path, mock_settings):
    paper = make_paper(title="RL Survey", paper_id="2301.00001")
    mock_client = MagicMock()
    mock_client.results.return_value = [paper]

    with patch("tools.arxiv.arxiv.Client", return_value=mock_client), \
         patch(_TO_THREAD, new=AsyncMock(side_effect=fake_to_thread)), \
         patch(_GET_SETTINGS, return_value=mock_settings):
        await ArxivTool()._specific_search({"query": "reinforcement learning"})

    out = tmp_path / "arxiv_search_query.md"
    assert out.exists()
    content = out.read_text()
    assert "RL Survey" in content
    assert "2301.00001" in content


async def test_specific_search_by_id_uses_id_list(tmp_path, mock_settings):
    paper = make_paper(title="Attention Is All You Need", paper_id="1706.03762")
    mock_client = MagicMock()
    mock_client.results.return_value = [paper]

    with patch("tools.arxiv.arxiv.Client", return_value=mock_client) as mock_cls, \
         patch(_TO_THREAD, new=AsyncMock(side_effect=fake_to_thread)), \
         patch(_GET_SETTINGS, return_value=mock_settings):
        await ArxivTool()._specific_search({"id": "1706.03762"})

    # Verify Search was constructed with id_list
    import arxiv as _arxiv
    call_args = mock_cls.return_value.results.call_args
    search_obj = call_args[0][0]
    assert search_obj.id_list == ["1706.03762"]

    out = tmp_path / "arxiv_search_1706.03762.md"
    assert out.exists()


async def test_specific_search_no_params_raises():
    with pytest.raises(ValueError, match="requires 'query' or 'id'"):
        await ArxivTool()._specific_search({})


async def test_specific_search_no_results_writes_placeholder(tmp_path, mock_settings):
    mock_client = MagicMock()
    mock_client.results.return_value = []

    with patch("tools.arxiv.arxiv.Client", return_value=mock_client), \
         patch(_TO_THREAD, new=AsyncMock(side_effect=fake_to_thread)), \
         patch(_GET_SETTINGS, return_value=mock_settings):
        await ArxivTool()._specific_search({"query": "obscure query xyz"})

    content = (tmp_path / "arxiv_search_query.md").read_text()
    assert "No papers found" in content


# ---------------------------------------------------------------------------
# _daily_discover
# ---------------------------------------------------------------------------

async def test_daily_discover_includes_recent_papers(tmp_path, mock_settings):
    recent = make_paper(title="Fresh Paper", hours_ago=2)
    mock_client = MagicMock()
    mock_client.results.return_value = [recent]

    with patch("tools.arxiv.arxiv.Client", return_value=mock_client), \
         patch(_TO_THREAD, new=AsyncMock(side_effect=fake_to_thread)), \
         patch(_GET_SETTINGS, return_value=mock_settings):
        await ArxivTool()._daily_discover({})

    content = (tmp_path / "arxiv_daily_discover.md").read_text()
    assert "Fresh Paper" in content


async def test_daily_discover_excludes_old_papers(tmp_path, mock_settings):
    old = make_paper(title="Old Paper", hours_ago=30)
    mock_client = MagicMock()
    mock_client.results.return_value = [old]

    with patch("tools.arxiv.arxiv.Client", return_value=mock_client), \
         patch(_TO_THREAD, new=AsyncMock(side_effect=fake_to_thread)), \
         patch(_GET_SETTINGS, return_value=mock_settings):
        await ArxivTool()._daily_discover({})

    content = (tmp_path / "arxiv_daily_discover.md").read_text()
    assert "Old Paper" not in content
    assert "No papers found" in content


async def test_daily_discover_deduplicates(tmp_path, mock_settings):
    mock_settings.arxiv_discover_keywords = ["ml", "dl"]
    shared = make_paper(title="Shared Paper", paper_id="2301.00001", hours_ago=1)
    unique = make_paper(title="Unique Paper", paper_id="2301.00002", hours_ago=1)

    mock_client = MagicMock()
    # Both keywords return shared; second keyword also returns unique
    mock_client.results.side_effect = [[shared], [shared, unique]]

    with patch("tools.arxiv.arxiv.Client", return_value=mock_client), \
         patch(_TO_THREAD, new=AsyncMock(side_effect=fake_to_thread)), \
         patch(_GET_SETTINGS, return_value=mock_settings):
        await ArxivTool()._daily_discover({})

    content = (tmp_path / "arxiv_daily_discover.md").read_text()
    assert content.count("Shared Paper") == 1
    assert "Unique Paper" in content


async def test_daily_discover_keywords_from_params(tmp_path, mock_settings):
    """params["keywords"] takes priority over settings."""
    paper = make_paper(title="Custom KW Paper", hours_ago=1)
    mock_client = MagicMock()
    mock_client.results.return_value = [paper]

    with patch("tools.arxiv.arxiv.Client", return_value=mock_client) as mock_cls, \
         patch(_TO_THREAD, new=AsyncMock(side_effect=fake_to_thread)), \
         patch(_GET_SETTINGS, return_value=mock_settings):
        await ArxivTool()._daily_discover({"keywords": ["custom keyword"]})

    # Only one Search call (one keyword)
    assert mock_client.results.call_count == 1


# ---------------------------------------------------------------------------
# _format_papers
# ---------------------------------------------------------------------------

def test_format_papers_empty():
    content = ArxivTool()._format_papers("Test Heading", [])
    assert "No papers found" in content
    assert "Test Heading" in content


def test_format_papers_truncates_long_summary():
    paper = make_paper()
    paper.summary = "x" * 500
    content = ArxivTool()._format_papers("Heading", [paper])
    assert "…" in content
    # Summary in output should be ≤ 400 chars + ellipsis
    assert "x" * 401 not in content


def test_format_papers_et_al_for_many_authors():
    paper = make_paper(n_authors=5)
    content = ArxivTool()._format_papers("Heading", [paper])
    assert "et al." in content


def test_format_papers_generated_at_present():
    ts = datetime(2026, 2, 26, 12, 0, tzinfo=timezone.utc)
    content = ArxivTool()._format_papers("Heading", [], generated_at=ts)
    assert "2026-02-26T12:00 UTC" in content


# ---------------------------------------------------------------------------
# arxiv_runner entry point
# ---------------------------------------------------------------------------

def test_arxiv_runner_calls_run_local():
    """Runner parses sys.argv JSON and passes it to ArxivTool.run_local."""
    import json
    import tools.arxiv_runner as runner

    params = {"query": "transformers", "mode": "search"}
    mock_run_local = AsyncMock()

    def fake_asyncio_run(coro):
        coro.close()  # suppress "coroutine never awaited" warning

    with patch("tools.arxiv_runner.asyncio.run", side_effect=fake_asyncio_run), \
         patch.object(ArxivTool, "run_local", mock_run_local), \
         patch("sys.argv", ["arxiv_runner", json.dumps(params)]):
        runner.main()

    mock_run_local.assert_called_once_with(params)
