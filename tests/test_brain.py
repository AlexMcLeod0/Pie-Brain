"""Tests for brains/claude_code.py."""
import asyncio

from brains.claude_code import ClaudeCodeBrain


def make_brain() -> ClaudeCodeBrain:
    return ClaudeCodeBrain(cloud_brain_semaphore=asyncio.Semaphore(1))


# ---------------------------------------------------------------------------
# get_spawn_cmd / _build_prompt
# ---------------------------------------------------------------------------

def test_prompt_includes_task_id_in_output_path():
    brain = make_brain()
    cmd = brain.get_spawn_cmd("arxiv", {"query": "RL", "_task_id": 42})
    assert "42_result.md" in cmd


def test_prompt_fallback_when_no_task_id():
    brain = make_brain()
    cmd = brain.get_spawn_cmd("arxiv", {"query": "RL"})
    assert "unknown_result.md" in cmd


def test_prompt_contains_tool_name_and_params():
    brain = make_brain()
    cmd = brain.get_spawn_cmd("memory", {"action": "query", "query": "test", "_task_id": 7})
    assert "memory" in cmd
    assert "query" in cmd


def test_get_spawn_cmd_escapes_single_quotes():
    """Single quotes in the prompt are shell-escaped."""
    brain = make_brain()
    # _build_prompt will include params JSON — inject a single quote via tool_name
    # We verify the escaping mechanism works at the cmd level
    cmd = brain.get_spawn_cmd("arxiv", {"note": "it's a test", "_task_id": 1})
    # The shell string should not contain a bare unescaped single quote
    # inside the outer 'claude --print '...' wrapper
    inner = cmd[len("claude --print '"):-1]  # strip wrapper quotes
    assert "'" not in inner or "'\\''" in cmd  # bare ' only allowed if escaped
