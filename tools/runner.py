"""Unified subprocess entry point: python -m tools.runner <tool_name> <local|spawn> '<params_json>'"""
import asyncio
import json
import subprocess
import sys

from brains.registry import BrainRegistry
from config.settings import get_settings
from tools import TOOL_REGISTRY


def main() -> None:
    if len(sys.argv) < 4:
        print(
            "Usage: python -m tools.runner <tool_name> <local|spawn> '<params_json>'",
            file=sys.stderr,
        )
        sys.exit(1)

    tool_name, mode, params_json = sys.argv[1], sys.argv[2], sys.argv[3]
    params = json.loads(params_json)

    tool_cls = TOOL_REGISTRY.get(tool_name)
    if tool_cls is None:
        print(
            f"Unknown tool: {tool_name!r}. Available: {list(TOOL_REGISTRY)}",
            file=sys.stderr,
        )
        sys.exit(1)

    tool = tool_cls()
    if mode == "local":
        asyncio.run(tool.run_local(params))
    elif mode == "spawn":
        settings = get_settings()
        brain = BrainRegistry().get(settings.default_cloud_brain)
        cmd = brain.get_spawn_cmd(tool_name, params)
        subprocess.run(["bash", "-c", f"nohup {cmd} &"], check=False)
    else:
        print(f"Unknown mode: {mode!r}. Expected 'local' or 'spawn'.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
