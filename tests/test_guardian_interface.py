"""Tests for guardian.interface_check — structural/signature validation."""
import inspect
import pytest

from guardian.interface_check import (
    ValidationIssue,
    _check_brain,
    _check_tool,
    _check_provider,
    validate_registries,
)
from tools.base import BaseTool
from brains.base import BaseBrain


# ---------------------------------------------------------------------------
# Helpers — minimal concrete classes
# ---------------------------------------------------------------------------


class GoodTool(BaseTool):
    tool_name = "good_tool"

    async def run_local(self, params: dict) -> None:
        pass

    def get_spawn_cmd(self, params: dict) -> str:
        return "echo good"


class NoNameTool(BaseTool):
    tool_name = ""

    async def run_local(self, params: dict) -> None:
        pass

    def get_spawn_cmd(self, params: dict) -> str:
        return "echo"


class BadRunLocalTool(BaseTool):
    tool_name = "bad_run_local"

    def run_local(self, params: dict) -> None:  # not async
        pass

    def get_spawn_cmd(self, params: dict) -> str:
        return "echo"


class WrongParamTool(BaseTool):
    tool_name = "wrong_param"

    async def run_local(self, wrong_name: dict) -> None:
        pass

    def get_spawn_cmd(self, wrong_name: dict) -> str:
        return "echo"


class GoodBrain(BaseBrain):
    brain_name = "good_brain"

    def get_spawn_cmd(self, tool_name: str, params: dict) -> str:
        return "echo brain"


class NoNameBrain(BaseBrain):
    brain_name = ""

    def get_spawn_cmd(self, tool_name: str, params: dict) -> str:
        return "echo"


class BadParamBrain(BaseBrain):
    brain_name = "bad_brain"

    def get_spawn_cmd(self, wrong: str, also_wrong: dict) -> str:
        return "echo"


class GoodProvider:
    async def run(self) -> None:
        pass


class MissingRunProvider:
    pass


class SyncRunProvider:
    def run(self) -> None:
        pass


class ExtraParamProvider:
    async def run(self, extra) -> None:
        pass


# ---------------------------------------------------------------------------
# Tool checks
# ---------------------------------------------------------------------------


def test_valid_tool_passes():
    issues = _check_tool(GoodTool)
    assert issues == []


def test_tool_missing_name_is_error():
    issues = _check_tool(NoNameTool)
    errors = [i for i in issues if i.severity == "error"]
    assert any("tool_name" in i.issue_text for i in errors)


def test_tool_non_async_run_local_is_error():
    issues = _check_tool(BadRunLocalTool)
    errors = [i for i in issues if i.severity == "error"]
    assert any("async" in i.issue_text for i in errors)


def test_tool_wrong_param_name_is_error():
    issues = _check_tool(WrongParamTool)
    errors = [i for i in issues if i.severity == "error"]
    # Both run_local and get_spawn_cmd have wrong param name
    assert len(errors) >= 1


# ---------------------------------------------------------------------------
# Brain checks
# ---------------------------------------------------------------------------


def test_valid_brain_passes():
    issues = _check_brain(GoodBrain)
    assert issues == []


def test_brain_missing_name_is_error():
    issues = _check_brain(NoNameBrain)
    errors = [i for i in issues if i.severity == "error"]
    assert any("brain_name" in i.issue_text for i in errors)


def test_brain_wrong_get_spawn_cmd_params_is_error():
    issues = _check_brain(BadParamBrain)
    errors = [i for i in issues if i.severity == "error"]
    assert any("get_spawn_cmd" in i.issue_text for i in errors)


# ---------------------------------------------------------------------------
# Provider checks
# ---------------------------------------------------------------------------


def test_valid_provider_passes():
    issues = _check_provider(GoodProvider)
    assert issues == []


def test_provider_missing_run_is_error():
    issues = _check_provider(MissingRunProvider)
    errors = [i for i in issues if i.severity == "error"]
    assert any("run" in i.issue_text for i in errors)


def test_provider_sync_run_is_error():
    issues = _check_provider(SyncRunProvider)
    errors = [i for i in issues if i.severity == "error"]
    assert any("async" in i.issue_text for i in errors)


def test_provider_extra_param_is_error():
    issues = _check_provider(ExtraParamProvider)
    errors = [i for i in issues if i.severity == "error"]
    assert any("(self)" in i.issue_text for i in errors)


# ---------------------------------------------------------------------------
# Danger-zone warning
# ---------------------------------------------------------------------------


def test_danger_zone_warning(tmp_path, monkeypatch):
    """A source file referencing /etc/passwd should produce a warning."""
    from guardian.interface_check import _scan_source_for_danger

    # Write a fake module file with a system path reference
    src = tmp_path / "evil_tool.py"
    src.write_text('open("/etc/passwd")')

    # Patch inspect.getfile to return our fake path
    monkeypatch.setattr(inspect, "getfile", lambda cls: str(src))

    issues = _scan_source_for_danger(GoodTool)
    warnings = [i for i in issues if i.severity == "warning"]
    assert len(warnings) == 1
    assert "system path" in warnings[0].issue_text


# ---------------------------------------------------------------------------
# validate_registries integration
# ---------------------------------------------------------------------------


def test_validate_registries_removes_bad_tool():
    """Bad tools are quarantined (removed) from the registry in-place."""

    class FakeRegistry:
        _registry: dict = {}

    tool_reg = {"good_tool": GoodTool, "bad_run_local": BadRunLocalTool}
    brain_reg = FakeRegistry()
    brain_reg._registry = {}

    issues = validate_registries(tool_reg, brain_reg)

    assert "good_tool" in tool_reg, "Good tool must survive"
    assert "bad_run_local" not in tool_reg, "Bad tool must be quarantined"
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) >= 1


def test_validate_registries_removes_bad_brain():
    class FakeRegistry:
        _registry: dict = {}

    tool_reg = {}
    brain_reg = FakeRegistry()
    brain_reg._registry = {"good_brain": GoodBrain, "bad_brain": BadParamBrain}

    validate_registries(tool_reg, brain_reg)

    assert "good_brain" in brain_reg._registry
    assert "bad_brain" not in brain_reg._registry
