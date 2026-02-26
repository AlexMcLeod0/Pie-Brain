"""Tests for BaseTool registry auto-collection."""
import pytest

from tools import TOOL_REGISTRY
from tools.base import BaseTool


def test_registry_not_empty():
    assert len(TOOL_REGISTRY) > 0, "TOOL_REGISTRY should contain at least one tool"


def test_known_tools_registered():
    for name in ("arxiv", "git_sync", "memory"):
        assert name in TOOL_REGISTRY, f"Tool {name!r} not found in registry"


def test_all_registry_values_are_basetool_subclasses():
    for name, cls in TOOL_REGISTRY.items():
        assert issubclass(cls, BaseTool), f"{name} is not a BaseTool subclass"


def test_tool_names_match_keys():
    for key, cls in TOOL_REGISTRY.items():
        assert cls.tool_name == key, (
            f"Registry key {key!r} does not match tool_name {cls.tool_name!r}"
        )


def test_tools_have_required_methods():
    for name, cls in TOOL_REGISTRY.items():
        assert hasattr(cls, "run_local"), f"{name} missing run_local"
        assert hasattr(cls, "get_spawn_cmd"), f"{name} missing get_spawn_cmd"
