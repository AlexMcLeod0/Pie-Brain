# MASTER SPEC: Project "Pie-Brain"
## 1. Objective
Build a modular, asynchronous task-routing engine for Raspberry Pi 4. It must bridge a local 1.5B Ollama model (The Router) with specialized local tools and a cloud-handoff mechanism (Claude Code) for heavy lifting.
## 2. Core Architecture

* Queue: SQLite (tasks.db) storage for all incoming requests. Fields: id, request_text, status (pending/routing/executing/done), tool_name, metadata (JSON).
* The Router: Background worker using ollama-python.
* Prompt: Must strictly output JSON identifying tool_name, params, and handoff (boolean).
* Context: Must prepend ~/brain/profile/user_prefs.md to every routing prompt.
* Worker Loop: Async process that monitors the DB, routes via Ollama, and executes tools.

## 3. Tool Standard & "The Contract"

* All tools reside in /tools and inherit from BaseTool.
* Logic: handoff=False executes run_local() on Pi. handoff=True executes get_spawn_cmd() to trigger claude code.
* Tool List:
* ArXiv Tool: Specific search (ID/Title) + Daily Discover (last 24h). Output: Markdown in ~/brain/inbox/.
* Git Tool: Handles pull --rebase pre-task and checkout -b, commit, gh pr create post-task.
* Vector Tool: Uses LanceDB + sentence-transformers for deduplication. Logic: If similarity > 0.8, abort new search and link existing file.


## 4. Resource & Style Guidelines (Pi 4 Optimized)

* Concurrency: Use asyncio.create_subprocess_exec for Claude Code spawning. Use nohup logic to ensure tasks survive if the harness restarts.
* Reliability: Use Atomic File Writes (tempfile + os.replace) for all Markdown updates.
* Memory Management: Use a Global Lock or Semaphore to ensure only one LLM inference and one Claude Code instance run simultaneously to prevent OOM.
* Data Integrity: Strict Pydantic models for settings and LLM outputs.
* Logging: Rotating file logs (max 5MB) to ~/.pie-brain/logs/.

## 5. Directory Structure

```text
pie-brain/
├── core/
│   ├── db.py          # SQLite/Pydantic models
│   ├── router.py      # Ollama logic
│   └── engine.py      # Main Async loop
├── tools/
│   ├── base.py        # Abstract Base Class
│   ├── arxiv.py
│   ├── git_sync.py
│   └── memory.py      # LanceDB logic
├── providers/
│   ├── telegram.py    # Frontend
│   └── scheduler.py   # Heartbeat/Cron
└── config/            # pydantic-settings
```

### 6. Swappable Cloud Brain Architecture:
* Provider Pattern: Implement a /brains directory with a BaseBrain abstract class.
* Brain Registration: Create a BrainRegistry that auto-loads any brain defined in /brains (e.g., claude_code.py, aider.py).
* Manifest Control: Use pydantic-settings to allow the user to toggle DEFAULT_CLOUD_BRAIN via an environment variable or config.yaml.
* Handoff Encapsulation: The Harness must never call a cloud tool directly; it must request a command string from the ActiveBrain instance and execute it via asyncio.create_subprocess_exec.