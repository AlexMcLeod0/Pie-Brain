"""Tests for guardian.sanitizer — spawn command safety checks."""
import pytest

from guardian.sanitizer import check_spawn_cmd, SanitizeResult


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _ok(cmd: str) -> bool:
    return check_spawn_cmd(cmd).ok


def _violations(cmd: str) -> list[str]:
    return check_spawn_cmd(cmd).violations


# ---------------------------------------------------------------------------
# Shell operator tests
# ---------------------------------------------------------------------------


def test_bare_pipe_is_blocked():
    result = check_spawn_cmd("cat /tmp/foo | rm -rf /")
    assert not result.ok
    assert any("operator" in v for v in result.violations)


def test_semicolon_is_blocked():
    result = check_spawn_cmd("echo hello; rm -rf /")
    assert not result.ok
    assert any("operator" in v for v in result.violations)


def test_double_ampersand_is_blocked():
    result = check_spawn_cmd("true && rm -rf /")
    assert not result.ok
    assert any("operator" in v for v in result.violations)


def test_double_pipe_is_blocked():
    result = check_spawn_cmd("false || rm -rf /")
    assert not result.ok
    assert any("operator" in v for v in result.violations)


def test_pipe_inside_single_quotes_is_allowed():
    # Pipe is safely quoted — should not trigger
    result = check_spawn_cmd("claude --print 'grep foo | bar'")
    assert result.ok, f"Unexpected violations: {result.violations}"


def test_pipe_inside_double_quotes_is_allowed():
    result = check_spawn_cmd('claude --print "grep foo | bar"')
    assert result.ok, f"Unexpected violations: {result.violations}"


# ---------------------------------------------------------------------------
# Command substitution
# ---------------------------------------------------------------------------


def test_dollar_paren_substitution_blocked():
    result = check_spawn_cmd("echo $(whoami)")
    assert not result.ok
    assert any("substitution" in v for v in result.violations)


def test_backtick_substitution_blocked():
    result = check_spawn_cmd("echo `whoami`")
    assert not result.ok
    assert any("substitution" in v for v in result.violations)


# ---------------------------------------------------------------------------
# Recursive engine spawn
# ---------------------------------------------------------------------------


def test_core_engine_module_blocked():
    result = check_spawn_cmd("python -m core.engine")
    assert not result.ok
    assert any("recursive" in v for v in result.violations)


def test_core_engine_path_blocked():
    result = check_spawn_cmd("python core/engine.py")
    assert not result.ok
    assert any("recursive" in v for v in result.violations)


# ---------------------------------------------------------------------------
# System path write
# ---------------------------------------------------------------------------


def test_etc_path_blocked():
    result = check_spawn_cmd("claude --print task > /etc/crontab")
    assert not result.ok
    assert any("system path" in v for v in result.violations)


def test_usr_path_blocked():
    result = check_spawn_cmd("cp evil /usr/bin/evil")
    assert not result.ok
    assert any("system path" in v for v in result.violations)


# ---------------------------------------------------------------------------
# Clean commands
# ---------------------------------------------------------------------------


def test_clean_claude_command_passes():
    cmd = "claude --print 'summarise arxiv 2401.00001'"
    result = check_spawn_cmd(cmd)
    assert result.ok, f"Unexpected violations: {result.violations}"


def test_nohup_wrapped_clean_command_passes():
    cmd = "nohup claude --dangerously-skip-permissions --print 'do the thing' &"
    result = check_spawn_cmd(cmd)
    assert result.ok, f"Unexpected violations: {result.violations}"


def test_empty_string_passes():
    # Edge case: empty string has no violations
    result = check_spawn_cmd("")
    assert result.ok


def test_sanitize_result_dataclass():
    r = SanitizeResult(ok=True)
    assert r.violations == []
    r2 = SanitizeResult(ok=False, violations=["bad"])
    assert r2.violations == ["bad"]
