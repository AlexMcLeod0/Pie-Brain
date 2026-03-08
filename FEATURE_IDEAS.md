# Pie-Brain Feature Ideas

> Generated 2026-03-07. Use this document to evaluate and prioritise potential additions before scheduling development work.
> Last reviewed 2026-03-08.
>
> **Completed / already implemented:** Tool auto-discovery (engine + installer), Unified notification delivery (Telegram push + polling fallback, idempotent `notified` flag).

---

## Priority 1 — Foundation *(ship before wide release)*

### ~~Tool Auto-Discovery~~ ✅ Done
Already implemented: `tools/__init__.py` uses `pkgutil.iter_modules` at import time; `setup.sh` dynamically discovers tools from the filesystem and reads descriptions from `routing_description` via ast.

---

### Health Watchdog & Process Supervisor
**What:** A lightweight daemon (or generated systemd unit file) that monitors the engine process and restarts it on crash or OOM kill.
**Why:** A Pi running 24/7 will encounter memory pressure, SD card hiccups, and network drops. Without this, the system silently stops working with no indication to the user.
**Priority:** P1

---

### Task Retry / Dead-Letter Queue
**What:** Transient failures (network timeout, Ollama cold start) trigger automatic retries with exponential backoff (e.g. 3 attempts). Tasks that exhaust retries move to a `dead` status visible in the CLI.
**Why:** Currently a task fails permanently on any error. Foundational for reliability in a network-connected, always-on deployment.
**Priority:** P1

---

### ~~Unified Notification Delivery~~ ✅ Done
Already implemented: Telegram provider pushes live status updates on every engine transition and delivers the final result via `_send_result()` (checks `task.result` then globs inbox files). A background polling loop catches any results missed by the push path. `mark_result_delivered()` is only called after a successful send, so transient Telegram outages are retried automatically.

Remaining gap (low priority): future providers (REST API, MQTT) will need to implement the same `register_notify_callback` + delivery pattern — but that work belongs to those provider features, not here.

---

## Priority 2 — Usability *(before community handoff)*

### REST API Provider
**What:** A small FastAPI/aiohttp endpoint (`POST /tasks`, `GET /tasks/{id}`) alongside the existing Telegram and scheduler providers.
**Why:** Lets anyone integrate Pie-Brain with Home Assistant, iOS Shortcuts, n8n, or a plain `curl` cron job — without needing a Telegram bot. Essential for adoption across diverse setups.
**Priority:** P2

---

### Simple Status Dashboard
**What:** A single-page, server-side-rendered HTML view on `localhost:7070` showing queue depth, recent task history, memory entry count, and active brain. No JS framework, no build step.
**Why:** Dramatically reduces the "is it working?" friction for new users. The Pi 4 can serve this trivially with aiohttp or Flask.
**Priority:** P2

---

### Brain Cost / Token Tracker
**What:** Log tokens used and estimated cost per cloud-brain call to SQLite. A `pie-brain stats` CLI command summarises cumulative spend.
**Why:** Open-source users paying for Claude/OpenAI API calls need visibility before costs surprise them. Builds trust and encourages responsible use.
**Priority:** P2

---

### Per-Tool YAML Configuration
**What:** Merge a `config/tools.yaml` file into pydantic-settings so tool defaults (ArXiv categories, max papers, memory dedup threshold, etc.) are user-configurable without code edits.
**Why:** Customisation currently requires forking. This is a prerequisite for the project being genuinely usable out of the box across different users' workflows.
**Priority:** P2

---

## Priority 3 — Ecosystem *(post-release)*

### MQTT Provider
**What:** Publish task results to an MQTT broker and accept new tasks via subscribed topics.
**Why:** The Pi is a natural home-automation hub. This opens integrations with Home Assistant, Node-RED, and IoT sensors without a custom adapter per service.
**Priority:** P3

---

### Web Scraper Tool
**What:** Fetch a URL, strip to main content (Readability-style), write to inbox and optionally store to LanceDB memory.
**Why:** Pairs naturally with the existing memory tool — articles are stored semantically and queryable later. Fully local; no GPU required.
**Priority:** P3

---

### Tool Chaining / Pipelines
**What:** Allow a task's `params` to declare `depends_on: [task_id]` so the engine sequences them and passes the prior result forward (e.g. `arxiv_discover → summarise_batch → send_digest`).
**Why:** The SQLite schema supports this with a foreign key; the engine loop needs a topological sort pass. Enables powerful multi-step workflows without user intervention.
**Priority:** P3

---

### Multi-User Isolation
**What:** An allowlist (`config/users.yaml`) plus a `user_id` column in the task DB so a household or small team can share one Pi without seeing each other's tasks or memory.
**Why:** The Telegram provider currently assumes one owner. Multi-user support widens the addressable audience significantly for an open-source release.
**Priority:** P3

---

### Voice Input via Whisper.cpp
**What:** Accept audio clips from Telegram voice messages, transcribe locally with `whisper.cpp` (quantised Q4 model runs on Pi 4 in ~10s for short clips), feed transcript into the normal task pipeline.
**Why:** High "wow factor" for demos and genuinely useful for hands-free use. Purely local — no cloud transcription needed.
**Priority:** P3

---

## Priority 4 — Nice-to-Have

### Inbox Pruner / Archiver Tool
**What:** Auto-archive `~/brain/inbox/` files older than N days to a compressed `~/brain/archive/` directory, keeping the working inbox scannable.
**Why:** Long-running deployments accumulate hundreds of Markdown files. Low complexity, high quality-of-life.
**Priority:** P4

---

### Structured Tool Result Schema
**What:** Replace free-form string returns with a `ToolResult(text, metadata, attachments)` Pydantic model so providers can render results differently (Telegram file vs. message, dashboard metadata panel, etc.).
**Why:** Good API surface to establish early — retrofitting this after multiple tools and providers exist will be a breaking change.
**Priority:** P4

---

### Ollama Model Auto-Upgrade Check
**What:** On scheduler heartbeat, check if a newer quantisation of the routing model is available locally via `ollama list` and log a notice if the pinned model is outdated.
**Why:** Keeps the router sharp without manual intervention. Low implementation cost.
**Priority:** P4

---

## Summary Table

| Feature | Priority | Area |
|---|---|---|
| ~~Tool auto-discovery~~ ✅ | Done | Core |
| Health watchdog & supervisor | P1 | Ops |
| Task retry / dead-letter queue | P1 | Core |
| ~~Unified notification delivery~~ ✅ | Done | Providers |
| REST API provider | P2 | Providers |
| Simple status dashboard | P2 | Ops |
| Brain cost / token tracker | P2 | Observability |
| Per-tool YAML configuration | P2 | Config |
| MQTT provider | P3 | Providers |
| Web scraper tool | P3 | Tools |
| Tool chaining / pipelines | P3 | Core |
| Multi-user isolation | P3 | Core |
| Voice input via Whisper.cpp | P3 | Providers |
| Inbox pruner / archiver | P4 | Tools |
| Structured tool result schema | P4 | Core |
| Ollama model auto-upgrade check | P4 | Ops |
