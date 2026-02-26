# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pie-Brain is a modular, async task-routing engine for Raspberry Pi 4. A local 1.5B Ollama model ("The Router") acts as an intent router, dispatching tasks to local tools or handing off to a cloud brain (default: Claude Code) for heavy lifting.

## Architecture

### Data Flow
1. Request enters via a provider (Telegram bot or scheduler heartbeat) → written to SQLite queue (`tasks.db`)
2. `core/engine.py` worker loop polls the DB, picks up `pending` tasks
3. `core/router.py` calls Ollama, prepending `~/brain/profile/user_prefs.md` to every prompt; expects strict JSON output: `{tool_name, params, handoff}`
4. If `handoff=False`: run `tool.run_local()` on the Pi
5. If `handoff=True`: get `tool.get_spawn_cmd()` → execute via `asyncio.create_subprocess_exec` (nohup pattern for harness-restart survival)
6. All Markdown output goes to `~/brain/inbox/`

### Key Constraints (Pi 4 Optimized)
- **Global semaphore**: only one LLM inference AND one Claude Code instance at a time (OOM prevention)
- **Atomic file writes**: always use `tempfile` + `os.replace` for Markdown updates
- **Strict Pydantic models** for all settings and LLM output parsing
- **Rotating logs** (max 5MB) to `~/.pie-brain/logs/`

### Module Map
- `core/db.py` — SQLite schema + Pydantic task models; task statuses: `pending → routing → executing → done`
- `core/router.py` — Ollama routing logic (ollama-python); must output `{tool_name, params, handoff}` JSON
- `core/engine.py` — Main async worker loop
- `tools/base.py` — `BaseTool` ABC; all tools must implement `run_local()` and `get_spawn_cmd()`
- `tools/arxiv.py` — Specific search (ID/Title) + Daily Discover (last 24h)
- `tools/git_sync.py` — `pull --rebase` pre-task; `checkout -b`, `commit`, `gh pr create` post-task
- `tools/memory.py` — LanceDB + sentence-transformers; dedup threshold: similarity > 0.8 aborts and links existing file
- `providers/telegram.py` — Telegram bot frontend
- `providers/scheduler.py` — Heartbeat/cron jobs
- `brains/` — Swappable cloud brain implementations (e.g., `claude_code.py`, `aider.py`)
- `config/` — pydantic-settings; `DEFAULT_CLOUD_BRAIN` toggled via env var or `config.yaml`

### Brain Registry Pattern
The harness **never** calls a cloud tool directly. It requests a command string from the `ActiveBrain` instance via `BaseBrain` and executes it via `asyncio.create_subprocess_exec`. New brains are auto-loaded from `/brains` by `BrainRegistry`.

## Development Setup

This project targets Python on Raspberry Pi 4. Key dependencies (from spec):
- `ollama-python` — Local LLM inference
- `lancedb` + `sentence-transformers` — Vector memory/dedup
- `pydantic-settings` — Config and LLM output validation
- `python-telegram-bot` (or equivalent) — Telegram provider

Install dependencies:
```bash
pip install -e ".[dev]"
```

Run the engine:
```bash
python -m core.engine
```

Run tests:
```bash
pytest
pytest tests/test_router.py  # single test file
pytest -k "test_name"        # single test by name
```
