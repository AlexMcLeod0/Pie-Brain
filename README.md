# Pie-Brain

<!-- GRAPHIC: project logo — a Raspberry Pi board with a stylised brain/circuit overlay. Suggested size: 600 × 200 px, centred. -->

> **A privacy-first, locally-routed AI assistant for Raspberry Pi — deployed in one command.**

A 1.5 B-parameter model running entirely on-device acts as an *intent router*: it reads your request, decides which tool can answer it locally, and only reaches out to a cloud brain when the task genuinely needs it. Everything else — inference, task queueing, memory, scheduling — stays on the Pi.

[![Tests](https://img.shields.io/github/actions/workflow/status/AlexMcLeod0/Pie-Brain/tests.yml?label=tests)](https://github.com/AlexMcLeod0/Pie-Brain/actions)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-GNU_Affero-green)](LICENSE)

---

## Table of Contents

1. [What Pie-Brain Does](#what-pie-brain-does)
2. [Architecture](#architecture)
3. [Quick Start](#quick-start)
4. [Configuration](#configuration)
5. [Built-in Tools](#built-in-tools)
6. [Project Layout](#project-layout)
7. [Extending Pie-Brain](#extending-pie-brain)
8. [Contributing](#contributing)
9. [Security](#security)

---

## What Pie-Brain Does

Send a message to your Telegram bot (or let the scheduler fire a timed job). The local router — a quantised [`qwen2.5:1.5b`](https://ollama.com/library/qwen2.5) model served by [Ollama](https://ollama.ai) — classifies the request and returns a structured routing decision:

- **Local tool** → runs the tool directly on the Pi and delivers the result back to Telegram.
- **Cloud handoff** → spawns a cloud brain (default: [Claude Code](https://claude.ai/code)) as a background process; the result is written to `~/brain/inbox/` and delivered once complete.

Your data never leaves the device unless *you* decide a task needs cloud assistance.

---

## Architecture

<!-- GRAPHIC: data-flow diagram. Suggested layout (left → right):
     [Telegram / Scheduler]  →  [SQLite queue]  →  [Engine / Router]
            ↓ local                                        ↓ handoff
       [Tool (Pi)]                                  [Cloud Brain subprocess]
     Both paths write Markdown to ~/brain/inbox/; Telegram picks it up and delivers it. -->

```
Request
  │
  ▼
Provider  ──────────────────────────────────►  SQLite task queue (tasks.db)
(Telegram / Scheduler)                                  │
                                                        ▼
                                              Engine worker loop
                                                        │
                                          ┌─────────────┴──────────────┐
                                          │   Ollama router (local)     │
                                          │   qwen2.5:1.5b              │
                                          └──────┬──────────────┬───────┘
                                                 │              │
                                          handoff=false   handoff=true
                                                 │              │
                                          ┌──────▼──┐    ┌──────▼──────────┐
                                          │  Tool   │    │  Cloud Brain    │
                                          │  (Pi)   │    │  subprocess     │
                                          └──────┬──┘    └──────┬──────────┘
                                                 │              │
                                          ┌──────▼──────────────▼──────┐
                                          │   ~/brain/inbox/  (Markdown)│
                                          └────────────────────────────┘
                                                        │
                                                        ▼
                                              Telegram result delivery
```

**Key design decisions:**

| Constraint | Reason |
|---|---|
| Global semaphore (1 LLM + 1 cloud brain at a time) | Prevents OOM on Pi 4's 4 GB RAM |
| Atomic file writes (`tempfile` + `os.replace`) | Avoids partial reads during result delivery |
| Strict Pydantic models for all LLM output | Crashes fast on malformed router responses |
| Rotating logs (5 MB max) | Keeps the SD card healthy over months of uptime |
| Guardian module validates every module at startup | Community tools can't break auto-discovery or inject shell commands |

---

## Quick Start

### Prerequisites

| Requirement | Notes |
|---|---|
| **Raspberry Pi 4** (2 GB+ RAM) | Tested on Pi 4 4 GB; Pi 5 also works |
| **Raspberry Pi OS Lite (64-bit)** | Recommended — no desktop overhead. [Download](https://www.raspberrypi.com/software/) |
| **Python 3.11+** | Pre-installed on recent Pi OS images |
| **git** | `sudo apt install git` |
| **Ollama** | [ollama.ai](https://ollama.ai) — one-line installer |
| **Telegram bot token** | Create a bot with [@BotFather](https://t.me/BotFather) |
| **Claude Code CLI** *(optional)* | Only needed for cloud brain handoff. `npm install -g @anthropic-ai/claude-code` |

### Install

First run:
```bash
curl -fsSL https://raw.githubusercontent.com/AlexMcLeod0/Pie-Brain/main/setup.sh -o setup.sh
```
Then run:
```bash
bash setup.sh
```

The interactive installer will:
1. Check prerequisites and install the [`uv`](https://github.com/astral-sh/uv) package manager if needed.
2. Ask which brain, messaging provider, and tools to install.
3. Clone the repo, prune unused modules, and install only the required Python dependencies.
4. Collect your Telegram token, allowed user IDs, and Ollama model name.
5. Write a `config.yaml` and a locked-down `.env` file (`chmod 600`).
6. Optionally install a **systemd user service** so the engine starts automatically on login.

### First run

```bash
# Pull the router model (once)
ollama pull qwen2.5:1.5b

# Authenticate the cloud brain (if using Claude Code)
claude login

# Start the engine
systemctl --user start pie-brain
# — or, without systemd —
cd ~/pie-brain && uv run python -m core.engine
```

Open Telegram, send your bot a message, and watch the response appear.

> **Tip:** Edit `~/brain/profile/user_prefs.md` to give the router personal context — preferred summary length, language, topic focus, etc. This file is prepended to every routing prompt.

---

## Configuration

Settings are loaded from `.env` (generated by setup.sh) and can be overridden in `config.yaml`. A full reference:

```yaml
# config.yaml — all fields are optional; shown with defaults

ollama_model: "qwen2.5:1.5b"
ollama_base_url: "http://localhost:11434"
ollama_timeout: 300         # seconds; generous for CPU-bound Pi 4
ollama_max_retries: 3

default_cloud_brain: "claude_code"

# Paths (~ is expanded)
db_path: "~/.pie-brain/tasks.db"
log_dir: "~/.pie-brain/logs"
brain_inbox: "~/brain/inbox"
user_prefs_path: "~/brain/profile/user_prefs.md"

# Telegram
telegram_bot_token: ""
telegram_allowed_user_ids: []   # empty = allow anyone (not recommended)
telegram_result_poll_interval: 5

# ArXiv daily discovery
arxiv_discover_keywords:
  - "large language models"
  - "reinforcement learning"
  - "computer vision"

# Memory (LanceDB)
memory_db_path: "~/.pie-brain/memory"
memory_embedding_model: "all-MiniLM-L6-v2"

# Guardian hot-watcher
guardian_poll_interval: 60      # seconds between scans for new modules
guardian_allowed_write_paths:
  - "~/brain"
  - "~/.pie-brain"
```

Sensitive values (`telegram_bot_token`, etc.) belong in `.env`, not `config.yaml`, and `.env` is `.gitignore`d.

---

## Built-in Tools

| Tool | `tool_name` | What it does |
|---|---|---|
| **ArXiv** | `arxiv` | Specific paper search by ID or query; daily discover of papers matching configured keywords published in the last 24 h |
| **Memory** | `memory` | Store and retrieve notes in a local LanceDB vector store; cosine-similarity deduplication (threshold 0.8) |
| **Git Sync** | `git_sync` | `pull --rebase` before a task; `checkout -b`, `commit`, and `gh pr create` after — keeps cloud-brain edits on a branch |

Results are written as Markdown files to `~/brain/inbox/` and delivered back to Telegram automatically.

---

## Project Layout

```
pie-brain/
│
├── core/
│   ├── engine.py          Main async worker loop; polls DB, dispatches tools or spawns brains
│   ├── router.py          Ollama routing logic; returns strict {tool_name, params, handoff} JSON
│   └── db.py              aiosqlite schema, Task model, TaskStatus enum, atomic_write helper
│
├── tools/
│   ├── base.py            BaseTool ABC  (tool_name, run_local, get_spawn_cmd)
│   ├── __init__.py        Auto-collects BaseTool subclasses into TOOL_REGISTRY at import
│   ├── arxiv.py           ArXiv search + daily discover
│   ├── memory.py          LanceDB vector memory
│   └── git_sync.py        Git pull/commit/PR automation
│
├── brains/
│   ├── base.py            BaseBrain ABC  (brain_name, get_spawn_cmd)
│   ├── registry.py        Auto-loads BaseBrain subclasses; injects semaphore on get()
│   └── claude_code.py     Claude Code brain (spawns the `claude` CLI)
│
├── providers/
│   ├── __init__.py        BaseProvider ABC  (async run())
│   ├── telegram.py        Telegram bot frontend + background result delivery
│   └── scheduler.py       Wall-clock cron jobs (default: daily ArXiv discover at 00:00 UTC)
│
├── guardian/
│   ├── interface_check.py Startup structural validation; quarantines bad modules in-place
│   ├── sanitizer.py       Spawn command safety checker (called before every subprocess)
│   ├── validator.py       Message integrity middleware (called before enqueue_task)
│   ├── smoke_test.py      Full hot-add smoke test for runtime-discovered modules
│   └── watcher.py         Async poller: detects new .py files and hot-registers or quarantines them
│
├── config/
│   └── settings.py        pydantic-settings Settings class; reads .env + config.yaml
│
├── tests/                 pytest test suite (122 tests)
├── setup.sh               Interactive one-command installer
├── pyproject.toml         Build config, optional dependency extras, pytest settings
└── .env                   Runtime secrets (generated by setup.sh; never committed)
```

The registries are built at import time by introspecting `__subclasses__()`, so dropping a new `.py` file into `tools/`, `brains/`, or `providers/` is all it takes for the engine to discover it — no manual registration required.

---

## Extending Pie-Brain

Pie-Brain is designed to be extended. The three extension points are **tools**, **brains**, and **providers**. Each follows a small ABC contract, and the Guardian module validates every module automatically.

### Adding a Tool

```python
# tools/my_tool.py
from tools.base import BaseTool

class MyTool(BaseTool):
    tool_name = "my_tool"          # must be unique and non-empty

    async def run_local(self, params: dict) -> None:
        """Execute the tool locally on the Pi."""
        # Write results to ~/brain/inbox/<task_id>_<name>.md
        ...

    def get_spawn_cmd(self, params: dict) -> str:
        """Return the shell command for cloud-brain handoff."""
        return f"claude --print 'run my_tool with params {params}'"
```

That's it. The engine will discover `MyTool` automatically on next start (or immediately, via the hot-module watcher).

### Adding a Brain

```python
# brains/my_brain.py
from brains.base import BaseBrain

class MyBrain(BaseBrain):
    brain_name = "my_brain"

    def get_spawn_cmd(self, tool_name: str, params: dict) -> str:
        return f"my-ai-cli --tool {tool_name}"
```

Set `DEFAULT_CLOUD_BRAIN=my_brain` in `.env` to activate it.

### Adding a Provider

```python
# providers/my_provider.py
from providers import BaseProvider
from core.db import enqueue_task
from config.settings import get_settings

class MyProvider(BaseProvider):
    async def run(self) -> None:
        settings = get_settings()
        # Poll your source and call enqueue_task(settings.db_path, text)
        ...
```

---

## Contributing

Contributions are welcome. Please read these guidelines before opening a pull request.

### Scope — one PR, one change

Each pull request must contain **exactly one** of the following:

- A single new **tool** (one `.py` file in `tools/` plus a `_runner.py` if needed)
- A single new **brain** (one `.py` file in `brains/`)
- A single new **provider** (one `.py` file in `providers/`)
- A focused **core change** (bug fix, performance improvement, or new feature in `core/`, `guardian/`, or `config/`)

Mixed PRs — for example, a new tool bundled with a refactor of `engine.py` — will be asked to split.

### Interface contract

Every contributed module must satisfy the ABC defined in its base class (`BaseTool`, `BaseBrain`, or `BaseProvider`). The Guardian module checks this automatically at startup and in CI; a module that fails the interface check will be quarantined and will never run.

### Security requirements

- **No destructive shell access.** Tools and brains must not request, invoke, or construct commands that write to system paths (`/etc`, `/usr`, `/sys`, `/proc`, `/root`), execute arbitrary shell pipelines, or spawn additional engine processes.
- **No shell operators in spawn commands.** `get_spawn_cmd()` must return a single command string — no `;`, `|`, `&&`, `||`, or command substitution (`$(...)`, backticks). The Guardian sanitizer will block any command that contains them.
- **No new mandatory pip dependencies without discussion.** The engine is designed to run on a Pi 4. If your module requires a heavy library, open an issue first and propose it as an optional extra in `pyproject.toml`.
- **Scope access to `~/brain/` and `~/.pie-brain/` only.** All file output must go to these directories. The Guardian interface checker will flag any source file that references paths outside these trees.

### Tests

Every contribution must include tests. Aim for at least one test per public method or logical branch. Run the full suite before submitting:

```bash
uv run pytest tests/ -v
```

All 122 existing tests must continue to pass.

### Pull request checklist

- [ ] One logical change per PR
- [ ] `BaseTool` / `BaseBrain` / `BaseProvider` interface satisfied
- [ ] No destructive shell access or system-path writes
- [ ] Tests included and all passing
- [ ] `.env` and secrets not committed
- [ ] `config.yaml` updated with any new settings (with sensible defaults)

---

## Security

Pie-Brain runs on a device that may be exposed to untrusted input via Telegram. The **Guardian** module provides three independent layers of defence:

| Layer | Where it runs | What it checks |
|---|---|---|
| **Interface checker** | Engine startup | Tool/brain/provider ABC conformance; source-level scan for system-path references |
| **Spawn sanitizer** | Before every `subprocess` call | Shell operators, command substitution, recursive engine spawns, system-path writes |
| **Message validator** | Before every `enqueue_task` | Empty messages, non-UTF-8 content, messages over 2 000 characters |

A module that fails the interface check is removed from the registry before the engine starts accepting tasks. A spawn command that fails the sanitizer raises a `RuntimeError` and marks the task `failed` — the subprocess is never created.

**Telegram access control:** Set `TELEGRAM_ALLOWED_USER_IDS` in `.env` to a comma-separated list of your Telegram user IDs. Leaving this blank allows any Telegram user to queue tasks — not recommended for a device on your home network.

**Cloud brain principle of least privilege:** The default Claude Code brain uses `claude --print`, which only prints output and does not grant the bot interactive shell access. Avoid using `--dangerously-skip-permissions` in production.

To report a security vulnerability, please open a [GitHub issue](https://github.com/AlexMcLeod0/Pie-Brain/issues) marked **[security]**.
