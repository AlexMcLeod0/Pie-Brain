"""Spawn command sanitization — called before every asyncio.create_subprocess_exec."""
import re
from dataclasses import dataclass, field


@dataclass
class SanitizeResult:
    ok: bool
    violations: list[str] = field(default_factory=list)


# Patterns that are always dangerous regardless of quoting
_RECURSIVE_SPAWN_RE = re.compile(r"core[./]engine")
_SYSTEM_PATH_WRITE_RE = re.compile(r"/(etc|usr|sys|proc|root)(?:[/ \t]|$)")
# Command substitution (outside quoting context doesn't matter — always dangerous)
_CMD_SUBSTITUTION_RE = re.compile(r"\$\(|`")


def _tokenize_unquoted(cmd: str) -> list[str]:
    """
    Return only the unquoted portions of *cmd*.

    Tracks single/double quote depth so that operators inside quotes are ignored.
    Handles basic backslash escaping inside double quotes.
    """
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    in_single = False
    in_double = False

    while i < len(cmd):
        ch = cmd[i]

        if in_single:
            if ch == "'":
                in_single = False
            # inside single quotes nothing is special
            i += 1
            continue

        if in_double:
            if ch == "\\" and i + 1 < len(cmd):
                i += 2  # skip escaped char
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue

        # Unquoted context
        if ch == "'":
            in_single = True
            # flush buffer as a separate token for clarity
            parts.append("".join(buf))
            buf = []
        elif ch == '"':
            in_double = True
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1

    parts.append("".join(buf))
    return parts


# Shell operators we block in unquoted context
_SHELL_OPERATOR_RE = re.compile(r"\||\;|&&|\|\|")


def check_spawn_cmd(cmd: str) -> SanitizeResult:
    """
    Validate *cmd* against spawn safety rules.

    Returns SanitizeResult(ok=True) if all checks pass, or
    SanitizeResult(ok=False, violations=[...]) listing each violation.
    """
    violations: list[str] = []

    # 1. Command substitution — always blocked regardless of quoting
    if _CMD_SUBSTITUTION_RE.search(cmd):
        violations.append("command substitution ($(...) or backtick) is not allowed")

    # 2. Recursive engine spawn — always blocked
    if _RECURSIVE_SPAWN_RE.search(cmd):
        violations.append("recursive engine spawn (core.engine / core/engine) is not allowed")

    # 3. System path write — always blocked
    if _SYSTEM_PATH_WRITE_RE.search(cmd):
        violations.append("write to system path (/etc, /usr, /sys, /proc, /root) is not allowed")

    # 4. Shell operators in unquoted context
    unquoted_parts = _tokenize_unquoted(cmd)
    unquoted_text = "".join(unquoted_parts)
    if _SHELL_OPERATOR_RE.search(unquoted_text):
        violations.append(
            "shell operator (|, ;, &&, ||) in unquoted context is not allowed"
        )

    return SanitizeResult(ok=len(violations) == 0, violations=violations)
