"""Tests for RouterOutput Pydantic parsing (Ollama mocked)."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.router import Router, RouterOutput


def make_router(max_retries: int = 3, timeout: float = 300.0) -> Router:
    sem = asyncio.Semaphore(1)
    return Router(
        model="qwen2.5:1.5b",
        user_prefs_path="/nonexistent/prefs.md",
        llm_semaphore=sem,
        max_retries=max_retries,
        timeout=timeout,
    )


# ---- RouterOutput parsing tests (no network) --------------------------------

def test_router_output_valid():
    data = {"tool_name": "arxiv", "params": {"query": "transformers"}, "handoff": False}
    out = RouterOutput(**data)
    assert out.tool_name == "arxiv"
    assert out.handoff is False


def test_router_output_handoff_true():
    data = {"tool_name": "git_sync", "params": {}, "handoff": True}
    out = RouterOutput(**data)
    assert out.handoff is True


def test_parse_clean_json():
    router = make_router()
    raw = json.dumps({"tool_name": "memory", "params": {"action": "query"}, "handoff": False})
    result = router._parse(raw)
    assert result.tool_name == "memory"


def test_parse_strips_markdown_fences():
    router = make_router()
    raw = '```json\n{"tool_name": "arxiv", "params": {}, "handoff": false}\n```'
    result = router._parse(raw)
    assert result.tool_name == "arxiv"


def test_parse_invalid_json_raises():
    router = make_router()
    with pytest.raises(ValueError):
        router._parse("not json at all")


def test_parse_missing_field_raises():
    router = make_router()
    with pytest.raises(ValueError):
        router._parse('{"tool_name": "arxiv"}')  # missing params + handoff


# ---- route() integration (Ollama mocked) ------------------------------------

async def test_route_calls_ollama():
    router = make_router()
    expected = {"tool_name": "arxiv", "params": {"query": "RL"}, "handoff": False}
    mock_response = {"message": {"content": json.dumps(expected)}}

    with patch.object(router.client, "chat", new=AsyncMock(return_value=mock_response)):
        result = await router.route("Find papers on RL")

    assert result.tool_name == "arxiv"
    assert result.handoff is False


async def test_route_retries_on_transient_error():
    """A single transient failure is retried and the second attempt succeeds."""
    router = make_router(max_retries=3)
    expected = {"tool_name": "arxiv", "params": {"query": "RL"}, "handoff": False}
    mock_response = {"message": {"content": json.dumps(expected)}}

    with patch.object(
        router.client, "chat",
        new=AsyncMock(side_effect=[asyncio.TimeoutError(), mock_response]),
    ):
        result = await router.route("Find papers on RL")

    assert result.tool_name == "arxiv"


async def test_route_raises_after_all_retries_exhausted():
    """RuntimeError is raised when every retry attempt fails."""
    router = make_router(max_retries=2)

    with patch.object(
        router.client, "chat",
        new=AsyncMock(side_effect=asyncio.TimeoutError()),
    ):
        with pytest.raises(RuntimeError, match="failed after 2 attempt"):
            await router.route("Find papers on RL")
