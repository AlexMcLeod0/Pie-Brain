"""Subprocess entry point: python -m tools.memory_runner '<params_json>'"""
import asyncio
import json
import sys

from tools.memory import MemoryTool


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m tools.memory_runner '<params_json>'", file=sys.stderr)
        sys.exit(1)
    params = json.loads(sys.argv[1])
    asyncio.run(MemoryTool().run_local(params))


if __name__ == "__main__":
    main()
