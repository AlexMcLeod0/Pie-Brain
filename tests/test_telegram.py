"""Tests for providers/telegram.py — result matching, /status, and event loop fix."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# We import only the pieces we can test without a live bot token.
# The Application / Bot objects are always mocked.

_GET_SETTINGS = "providers.telegram.get_settings"


@pytest.fixture
def mock_settings(tmp_path):
    s = MagicMock()
    s.telegram_bot_token = "fake-token"
    s.telegram_allowed_user_ids = []
    s.telegram_result_poll_interval = 5
    s.db_path = str(tmp_path / "tasks.db")
    s.brain_inbox = str(tmp_path / "inbox")
    return s


@pytest.fixture
def provider(mock_settings):
    """Build a TelegramProvider with Application fully mocked."""
    mock_app = MagicMock()
    mock_app.add_handler = MagicMock()

    with patch(_GET_SETTINGS, return_value=mock_settings), \
         patch("providers.telegram.Application") as mock_cls:
        mock_cls.builder.return_value.token.return_value.post_init.return_value \
            .build.return_value = mock_app

        from providers.telegram import TelegramProvider
        p = TelegramProvider()
        p.app = mock_app
        return p


# ---------------------------------------------------------------------------
# Result matching — _send_result
# ---------------------------------------------------------------------------

async def test_send_result_uses_task_id_prefixed_file(tmp_path, mock_settings, provider):
    """_send_result picks up the file named {task_id}_*.md, not any stray file."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    mock_settings.brain_inbox = str(inbox)

    # Write a file belonging to task 42 and a decoy for task 99
    (inbox / "42_arxiv_search_query.md").write_text("Correct result for task 42")
    (inbox / "99_arxiv_search_query.md").write_text("Wrong result for task 99")

    task = MagicMock()
    task.id = 42
    task.chat_id = 1001
    task.tool_name = "arxiv"

    mock_bot = AsyncMock()
    provider.settings = mock_settings

    with patch("providers.telegram.mark_notified", new=AsyncMock()):
        await provider._send_result(mock_bot, task)

    sent_text = mock_bot.send_message.call_args.kwargs["text"]
    assert "Correct result for task 42" in sent_text
    assert "Wrong result" not in sent_text


async def test_send_result_falls_back_when_no_file(tmp_path, mock_settings, provider):
    """If no {task_id}_*.md exists, sends the generic completion message."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    mock_settings.brain_inbox = str(inbox)

    task = MagicMock()
    task.id = 7
    task.chat_id = 2002
    task.tool_name = "arxiv"

    mock_bot = AsyncMock()
    provider.settings = mock_settings

    with patch("providers.telegram.mark_notified", new=AsyncMock()):
        await provider._send_result(mock_bot, task)

    sent_text = mock_bot.send_message.call_args.kwargs["text"]
    assert "Task #7 complete" in sent_text


async def test_send_result_truncates_long_output(tmp_path, mock_settings, provider):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    mock_settings.brain_inbox = str(inbox)
    (inbox / "5_result.md").write_text("x" * 5000)

    task = MagicMock()
    task.id = 5
    task.chat_id = 3003
    task.tool_name = "memory"

    mock_bot = AsyncMock()
    provider.settings = mock_settings

    with patch("providers.telegram.mark_notified", new=AsyncMock()):
        await provider._send_result(mock_bot, task)

    sent_text = mock_bot.send_message.call_args.kwargs["text"]
    assert "…(truncated)" in sent_text
    assert len(sent_text) <= 4100  # 4000 content + truncation notice


# ---------------------------------------------------------------------------
# /status with no args — recent tasks list
# ---------------------------------------------------------------------------

async def test_cmd_status_no_args_shows_recent_tasks(provider, mock_settings):
    update = MagicMock()
    update.message = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 1
    context = MagicMock()
    context.args = []

    from core.db import Task, TaskStatus
    recent = [
        Task(id=3, request_text="third task", status=TaskStatus.done),
        Task(id=2, request_text="second task", status=TaskStatus.executing),
        Task(id=1, request_text="first task", status=TaskStatus.done),
    ]

    provider.settings = mock_settings
    with patch("providers.telegram.get_recent_tasks", new=AsyncMock(return_value=recent)):
        await provider._cmd_status(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "#3" in reply
    assert "#2" in reply
    assert "done" in reply
    assert "executing" in reply


async def test_cmd_status_no_args_empty_db(provider, mock_settings):
    update = MagicMock()
    update.message = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 1
    context = MagicMock()
    context.args = []

    provider.settings = mock_settings
    with patch("providers.telegram.get_recent_tasks", new=AsyncMock(return_value=[])):
        await provider._cmd_status(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "No tasks" in reply


# ---------------------------------------------------------------------------
# Event loop fix — post_init hook registers the delivery task
# ---------------------------------------------------------------------------

async def test_on_startup_creates_delivery_task(provider):
    """_on_startup creates an asyncio task for _deliver_results."""
    delivered = []

    async def fake_deliver():
        delivered.append(True)
        # Immediately return so the test doesn't hang
        return

    provider._deliver_results = fake_deliver
    mock_application = MagicMock()

    await provider._on_startup(mock_application)
    # Yield control so the created task can start
    await asyncio.sleep(0)

    assert delivered == [True]
