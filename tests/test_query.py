"""Tests for tools/query.py."""
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.query import CONTEXT_CHARS, MAX_INBOX_FILES, QueryTool


@pytest.fixture
def tool():
    return QueryTool()


@pytest.fixture
def mock_settings(tmp_path):
    s = MagicMock()
    s.brain_inbox = str(tmp_path / "inbox")
    s.ollama_base_url = "http://localhost:11434"
    s.ollama_model = "qwen2.5:1.5b"
    s.ollama_timeout = 30
    return s


# ---------------------------------------------------------------------------
# _gather_context
# ---------------------------------------------------------------------------

def test_gather_context_returns_empty_for_missing_inbox(tmp_path, tool):
    result = tool._gather_context("anything", str(tmp_path / "nonexistent"))
    assert result == ""


def test_gather_context_returns_empty_for_empty_inbox(tmp_path, tool):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    result = tool._gather_context("anything", str(inbox))
    assert result == ""


def test_gather_context_includes_keyword_match(tmp_path, tool):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "1_arxiv_transformers.md").write_text("Transformers are powerful architectures.")
    (inbox / "2_arxiv_convnets.md").write_text("ConvNets use convolutions for vision tasks.")

    result = tool._gather_context("Tell me about transformers", str(inbox))
    assert "Transformers are powerful" in result


def test_gather_context_prefers_keyword_match_over_recency(tmp_path, tool):
    """A keyword-matching older file ranks above a recent but irrelevant file."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()

    # Write the relevant file first (older mtime), then an irrelevant recent one
    relevant = inbox / "1_arxiv_llm.md"
    relevant.write_text("Large language models are trained on massive datasets.")
    time.sleep(0.02)  # ensure distinct mtime
    for i in range(MAX_INBOX_FILES):
        (inbox / f"{i+10}_unrelated.md").write_text("Unrelated content about cooking recipes.")

    result = tool._gather_context("What are language models?", str(inbox))
    assert "Large language models" in result


def test_gather_context_respects_context_char_limit(tmp_path, tool):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for i in range(10):
        (inbox / f"{i}_big.md").write_text("word " * 2000)

    result = tool._gather_context("word", str(inbox))
    # Allow a small overhead for the "--- filename ---" headers
    assert len(result) <= CONTEXT_CHARS + 200


def test_gather_context_caps_number_of_files(tmp_path, tool):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for i in range(MAX_INBOX_FILES + 3):
        (inbox / f"{i}_file.md").write_text(f"content {i}")

    result = tool._gather_context("content", str(inbox))
    # No more than MAX_INBOX_FILES separators in the output
    assert result.count("--- ") <= MAX_INBOX_FILES


# ---------------------------------------------------------------------------
# run_local
# ---------------------------------------------------------------------------

async def test_run_local_writes_output_file(tmp_path, tool, mock_settings):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    mock_settings.brain_inbox = str(inbox)

    with patch("tools.query.get_settings", return_value=mock_settings), \
         patch.object(tool, "_ask_ollama", new=AsyncMock(return_value="Great answer here.")):
        await tool.run_local({"question": "What is AI?", "_task_id": 42})

    output = inbox / "42_query.md"
    assert output.exists()
    text = output.read_text()
    assert "What is AI?" in text
    assert "Great answer here." in text


async def test_run_local_raises_on_empty_question(tool, mock_settings):
    with patch("tools.query.get_settings", return_value=mock_settings):
        with pytest.raises(ValueError, match="question"):
            await tool.run_local({"_task_id": 1})


async def test_run_local_raises_on_whitespace_only_question(tool, mock_settings):
    with patch("tools.query.get_settings", return_value=mock_settings):
        with pytest.raises(ValueError, match="question"):
            await tool.run_local({"question": "   ", "_task_id": 1})


async def test_run_local_passes_context_to_ollama(tmp_path, tool, mock_settings):
    """run_local passes gathered context into _ask_ollama."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "5_arxiv_rl.md").write_text("Reinforcement learning uses reward signals.")
    mock_settings.brain_inbox = str(inbox)

    captured: list[tuple] = []

    async def fake_ask(question, context, settings):
        captured.append((question, context))
        return "Some answer."

    with patch("tools.query.get_settings", return_value=mock_settings), \
         patch.object(tool, "_ask_ollama", side_effect=fake_ask):
        await tool.run_local({"question": "What about reinforcement learning?", "_task_id": 7})

    assert captured
    _, context = captured[0]
    assert "Reinforcement learning" in context


# ---------------------------------------------------------------------------
# _ask_ollama error handling
# ---------------------------------------------------------------------------

async def test_ask_ollama_returns_error_string_on_failure(tool, mock_settings):
    mock_client = MagicMock()
    mock_client.chat = AsyncMock(side_effect=RuntimeError("connection refused"))

    with patch("tools.query.ollama.AsyncClient", return_value=mock_client):
        result = await tool._ask_ollama("What?", "", mock_settings)

    assert "Error" in result
    assert "connection refused" in result


async def test_ask_ollama_sends_context_in_user_message(tool, mock_settings):
    """When context is non-empty it is prepended to the user message."""
    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value={"message": {"content": "answer"}})
    context = "Some previous result."

    with patch("tools.query.ollama.AsyncClient", return_value=mock_client):
        await tool._ask_ollama("What happened?", context, mock_settings)

    call_messages = mock_client.chat.call_args.kwargs["messages"]
    user_msg = next(m for m in call_messages if m["role"] == "user")
    assert context in user_msg["content"]
    assert "What happened?" in user_msg["content"]


async def test_ask_ollama_omits_context_prefix_when_empty(tool, mock_settings):
    """When context is empty, only the question is sent."""
    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value={"message": {"content": "answer"}})

    with patch("tools.query.ollama.AsyncClient", return_value=mock_client):
        await tool._ask_ollama("Hello!", "", mock_settings)

    call_messages = mock_client.chat.call_args.kwargs["messages"]
    user_msg = next(m for m in call_messages if m["role"] == "user")
    assert user_msg["content"] == "Hello!"


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

def test_query_tool_registered():
    from tools import TOOL_REGISTRY
    assert "query" in TOOL_REGISTRY
    assert TOOL_REGISTRY["query"] is QueryTool
