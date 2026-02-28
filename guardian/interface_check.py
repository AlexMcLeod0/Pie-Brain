"""Structural/signature validation for tools, brains, and providers."""
import inspect
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from brains.base import BaseBrain
from tools.base import BaseTool

logger = logging.getLogger(__name__)

SYSTEM_PATH_RE = re.compile(r'["\'/](etc|usr|var|sys|proc|root|boot|lib|bin|sbin)/')


@dataclass
class ValidationIssue:
    module_name: str
    issue_text: str
    severity: str  # "error" | "warning"


def _check_tool(cls: type) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    name = getattr(cls, "tool_name", None)
    mod = cls.__module__

    # tool_name must be a non-empty string
    if not isinstance(name, str) or not name.strip():
        issues.append(ValidationIssue(mod, "tool_name is missing or empty", "error"))

    # run_local must be an async method accepting (self, params: dict)
    run_local = getattr(cls, "run_local", None)
    if run_local is None:
        issues.append(ValidationIssue(mod, "missing run_local method", "error"))
    else:
        if not inspect.iscoroutinefunction(run_local):
            issues.append(ValidationIssue(mod, "run_local must be async", "error"))
        sig = inspect.signature(run_local)
        params = list(sig.parameters.keys())
        # params[0] = self, params[1] = params
        if len(params) < 2 or params[1] != "params":
            issues.append(
                ValidationIssue(mod, "run_local must accept (self, params: dict)", "error")
            )

    # get_spawn_cmd must be a method accepting (self, params: dict) returning str
    get_spawn_cmd = getattr(cls, "get_spawn_cmd", None)
    if get_spawn_cmd is None:
        issues.append(ValidationIssue(mod, "missing get_spawn_cmd method", "error"))
    else:
        if inspect.iscoroutinefunction(get_spawn_cmd):
            issues.append(ValidationIssue(mod, "get_spawn_cmd must not be async", "error"))
        sig = inspect.signature(get_spawn_cmd)
        params = list(sig.parameters.keys())
        if len(params) < 2 or params[1] != "params":
            issues.append(
                ValidationIssue(mod, "get_spawn_cmd must accept (self, params: dict)", "error")
            )

    return issues


def _check_brain(cls: type) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    name = getattr(cls, "brain_name", None)
    mod = cls.__module__

    if not isinstance(name, str) or not name.strip():
        issues.append(ValidationIssue(mod, "brain_name is missing or empty", "error"))

    get_spawn_cmd = getattr(cls, "get_spawn_cmd", None)
    if get_spawn_cmd is None:
        issues.append(ValidationIssue(mod, "missing get_spawn_cmd method", "error"))
    else:
        if inspect.iscoroutinefunction(get_spawn_cmd):
            issues.append(ValidationIssue(mod, "get_spawn_cmd must not be async", "error"))
        sig = inspect.signature(get_spawn_cmd)
        param_names = list(sig.parameters.keys())
        # Expected: (self, tool_name: str, params: dict)
        if len(param_names) < 3 or param_names[1] != "tool_name" or param_names[2] != "params":
            issues.append(
                ValidationIssue(
                    mod,
                    "get_spawn_cmd must accept (self, tool_name: str, params: dict)",
                    "error",
                )
            )

    return issues


def _check_provider(cls: type) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    mod = cls.__module__

    run = getattr(cls, "run", None)
    if run is None:
        issues.append(ValidationIssue(mod, "missing run() method", "error"))
    else:
        if not inspect.iscoroutinefunction(run):
            issues.append(ValidationIssue(mod, "run() must be async", "error"))
        sig = inspect.signature(run)
        param_names = list(sig.parameters.keys())
        # Only self allowed
        if len(param_names) != 1:
            issues.append(
                ValidationIssue(mod, "run() must have signature (self)", "error")
            )

    return issues


def _scan_source_for_danger(cls: type) -> list[ValidationIssue]:
    """Scan module source for writes to system paths (warning only)."""
    issues: list[ValidationIssue] = []
    try:
        mod_file = inspect.getfile(cls)
        source = Path(mod_file).read_text(encoding="utf-8", errors="replace")
        if SYSTEM_PATH_RE.search(source):
            issues.append(
                ValidationIssue(
                    cls.__module__,
                    f"source references a system path ({mod_file}); manual review recommended",
                    "warning",
                )
            )
    except (TypeError, OSError):
        pass
    return issues


def validate_registries(
    tool_registry: dict,
    brain_registry,  # BrainRegistry — avoid circular import
    provider_classes: list[type] | None = None,
) -> list[ValidationIssue]:
    """
    Validate all registered tools, brains, and providers.
    Quarantines (removes) entries with error-severity issues in-place.
    Returns all issues found (both errors and warnings).
    """
    from providers import BaseProvider  # local import to avoid circular deps

    all_issues: list[ValidationIssue] = []

    # --- Tools ---
    bad_tool_keys: list[str] = []
    for tool_name, cls in list(tool_registry.items()):
        issues = _check_tool(cls) + _scan_source_for_danger(cls)
        all_issues.extend(issues)
        has_error = any(i.severity == "error" for i in issues)
        if has_error:
            bad_tool_keys.append(tool_name)
            logger.error(
                "Guardian: quarantining tool %r — %s",
                tool_name,
                "; ".join(i.issue_text for i in issues if i.severity == "error"),
            )
        for issue in issues:
            log = logger.error if issue.severity == "error" else logger.warning
            log("Guardian [tool:%s] %s: %s", tool_name, issue.severity, issue.issue_text)

    for key in bad_tool_keys:
        del tool_registry[key]

    # --- Brains ---
    bad_brain_keys: list[str] = []
    for brain_name, cls in list(brain_registry._registry.items()):
        issues = _check_brain(cls) + _scan_source_for_danger(cls)
        all_issues.extend(issues)
        has_error = any(i.severity == "error" for i in issues)
        if has_error:
            bad_brain_keys.append(brain_name)
            logger.error(
                "Guardian: quarantining brain %r — %s",
                brain_name,
                "; ".join(i.issue_text for i in issues if i.severity == "error"),
            )
        for issue in issues:
            log = logger.error if issue.severity == "error" else logger.warning
            log("Guardian [brain:%s] %s: %s", brain_name, issue.severity, issue.issue_text)

    for key in bad_brain_keys:
        del brain_registry._registry[key]

    # --- Providers ---
    for cls in (provider_classes or []):
        issues = _check_provider(cls)
        all_issues.extend(issues)
        for issue in issues:
            log = logger.error if issue.severity == "error" else logger.warning
            log(
                "Guardian [provider:%s] %s: %s",
                cls.__name__,
                issue.severity,
                issue.issue_text,
            )

    return all_issues
