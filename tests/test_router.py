"""Tests for RouterOutput Pydantic parsing (Ollama mocked)."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.router import Router, RouterOutput


def make_router() -> Router:
    sem = asyncio.Semaphore(1)
    return Router(
        model="qwen2.5:1.5b",
        user_prefs_path="/nonexistent/prefs.md",
        llm_semaphore=sem,
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
