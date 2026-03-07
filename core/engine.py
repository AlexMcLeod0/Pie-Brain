"""Main async engine loop."""
import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Awaitable

import guardian
from config.settings import get_settings
from core.db import (
    Task,
    TaskStatus,
    init_db,
    enqueue_task,
    get_pending_tasks,
    get_task_by_id,
    get_recent_tasks as _db_get_recent_tasks,
    get_completed_unnotified,
    mark_notified,
    update_task_status,
    setup_logging,
)
from core.router import Router, RouterOutput
from tools import TOOL_REGISTRY
from brains.registry import BrainRegistry

logger = logging.getLogger(__name__)

POLL_INTERVAL = 2.0  # seconds between DB polls


class Engine:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.llm_sem, self.brain_sem = self.settings.build_semaphores()
        self.router = Router(
            model=self.settings.ollama_model,
            user_prefs_path=self.settings.user_prefs_path,
            llm_semaphore=self.llm_sem,
            base_url=self.settings.ollama_base_url,
            timeout=self.settings.ollama_timeout,
            max_retries=self.settings.ollama_max_retries,
        )
        self.brain_registry = BrainRegistry(cloud_brain_semaphore=self.brain_sem)
        self._running = False
        self._scheduler = None  # set in run()
        self._notify_callbacks: list[Callable[..., Awaitable[None]]] = []
        self._broadcast_callbacks: list[Callable[[str], Awaitable[None]]] = []

    def register_notify_callback(self, cb: Callable[..., Awaitable[None]]) -> None:
        """Register a coroutine called on every task status transition."""
        self._notify_callbacks.append(cb)

    def register_broadcast_callback(self, cb: Callable[[str], Awaitable[None]]) -> None:
        """Register a coroutine called when the engine broadcasts a system message."""
        self._broadcast_callbacks.append(cb)

    async def broadcast_all(self, message: str) -> None:
        """Fan a system message out to all registered providers."""
        for cb in self._broadcast_callbacks:
            try:
                await cb(message)
            except Exception:
                logger.exception("Broadcast callback error")

    # ------------------------------------------------------------------
    # Public task API — providers call these instead of touching core.db
    # ------------------------------------------------------------------

    async def submit_task(
        self, text: str, chat_id: int | None = None, metadata: dict | None = None
    ) -> int:
        """Enqueue a new task and return its ID."""
        return await enqueue_task(self.settings.db_path, text, metadata=metadata, chat_id=chat_id)

    async def get_task(self, task_id: int) -> Task | None:
        """Fetch a single task by ID."""
        return await get_task_by_id(self.settings.db_path, task_id)

    async def get_recent_tasks(self, limit: int = 5) -> list[Task]:
        """Fetch the most recently created tasks, newest first."""
        return await _db_get_recent_tasks(self.settings.db_path, limit=limit)

    async def get_deliverable_results(self) -> list[Task]:
        """Return completed tasks that have a chat_id but haven't been notified."""
        return await get_completed_unnotified(self.settings.db_path)

    async def mark_result_delivered(self, task_id: int) -> None:
        """Mark a task's result as delivered to the user."""
        await mark_notified(self.settings.db_path, task_id)

    def schedule_daily(self, utc_time: str, description: str, metadata: dict) -> None:
        """Register a new daily recurring job with the running scheduler."""
        if self._scheduler is None:
            logger.warning("schedule_daily called but scheduler is not running.")
            return
        self._scheduler.add_daily(utc_time, description, metadata)

    async def _notify(self, task_id: int) -> None:
        """Fetch the current task state and fan-out to all registered callbacks."""
        if not self._notify_callbacks:
            return
        task = await get_task_by_id(self.settings.db_path, task_id)
        if task is None:
            return
        for cb in self._notify_callbacks:
            try:
                await cb(task)
            except Exception:
                logger.exception("Notify callback error for task %d", task_id)

    async def run(self) -> None:
        """Start the engine; polls DB and dispatches tasks indefinitely."""
        setup_logging(self.settings.log_dir)
        await init_db(self.settings.db_path)
        self._running = True

        # Start scheduler (always; jobs are added dynamically via ScheduleTool)
        from providers.scheduler import Scheduler
        self._scheduler = Scheduler()
        self._scheduler.register_engine(self)
        asyncio.create_task(self._scheduler.run())
        logger.info("Scheduler started.")

        # Start providers
        if self.settings.telegram_bot_token:
            try:
                from providers.telegram import TelegramProvider
                tp = TelegramProvider()
                tp.register_engine(self)
                asyncio.create_task(tp.run())
                logger.info("Telegram provider started.")
            except ImportError:
                logger.warning("Telegram provider not available (not installed).")

        # Validate all registered modules at startup
        guardian.validate_registries(TOOL_REGISTRY, self.brain_registry)

        logger.info(
            "Engine started. model=%s brain=%s",
            self.settings.ollama_model,
            self.settings.default_cloud_brain,
        )

        # Start hot-module watcher
        asyncio.create_task(
            guardian.watch_for_new_modules(
                TOOL_REGISTRY,
                self.brain_registry,
                poll_interval=self.settings.guardian_poll_interval,
            )
        )

        # Start dev-mode git watcher (disabled by default)
        if self.settings.dev_mode:
            from core.dev_watcher import watch_for_updates
            asyncio.create_task(
                watch_for_updates(
                    poll_interval=self.settings.dev_mode_poll_interval,
                    notify_fn=lambda: self.broadcast_all("Update complete"),
                )
            )
            logger.info("Dev mode active: auto-pull enabled.")

        while self._running:
            tasks = await get_pending_tasks(self.settings.db_path)
            for task in tasks:
                asyncio.create_task(self._handle(task))
            await asyncio.sleep(POLL_INTERVAL)

    async def stop(self) -> None:
        self._running = False
        logger.info("Engine stopping.")

    async def _handle(self, task) -> None:
        db = self.settings.db_path
        try:
            # Mark as routing
            await update_task_status(db, task.id, TaskStatus.routing)
            await self._notify(task.id)

            # Route via Ollama — fall back to query on parse/timeout failures
            try:
                router_output = await self.router.route(task.request_text)
            except Exception as exc:
                logger.warning(
                    "Task %d routing failed (%s); falling back to query", task.id, exc
                )
                router_output = RouterOutput(
                    tool_name="query",
                    params={"question": task.request_text},
                    handoff=False,
                )

            logger.info(
                "Task %d → tool=%s handoff=%s",
                task.id,
                router_output.tool_name,
                router_output.handoff,
            )

            # Mark as executing
            await update_task_status(
                db, task.id, TaskStatus.executing,
                tool_name=router_output.tool_name,
                metadata={"params": router_output.params, "handoff": router_output.handoff},
            )
            await self._notify(task.id)

            result: str | None = None
            if router_output.handoff:
                await self._spawn_brain(router_output.tool_name, router_output.params)
            else:
                tool_cls = TOOL_REGISTRY.get(router_output.tool_name)
                if tool_cls is None:
                    logger.warning(
                        "Task %d: unknown tool %r, falling back to query",
                        task.id, router_output.tool_name,
                    )
                    tool_cls = TOOL_REGISTRY.get("query")
                    if tool_cls is None:
                        raise ValueError(
                            f"Unknown tool {router_output.tool_name!r} and no 'query' fallback"
                        )
                    router_output = RouterOutput(
                        tool_name="query",
                        params={"question": task.request_text},
                        handoff=False,
                    )
                tool = tool_cls()
                # Inject engine reference for tools that opt in (e.g. ScheduleTool)
                if hasattr(tool, "register_engine"):
                    tool.register_engine(self)
                # Inject task ID so tools can name output files unambiguously
                params = {**router_output.params, "_task_id": task.id}
                result = await tool.run_local(params)

            await update_task_status(db, task.id, TaskStatus.done, result=result)
            await self._notify(task.id)

        except Exception as exc:
            logger.exception("Task %d failed: %s", task.id, exc)
            await update_task_status(
                db, task.id, TaskStatus.failed,
                metadata={"error": str(exc)},
            )
            await self._notify(task.id)

    async def _spawn_brain(self, tool_name: str, params: dict) -> None:
        """Spawn a cloud brain subprocess; uses nohup for harness-restart survival."""
        brain = self.brain_registry.get(self.settings.default_cloud_brain)
        cmd_str = brain.get_spawn_cmd(tool_name, params)

        # Wrap in nohup so the child outlives a harness restart
        full_cmd = f"nohup {cmd_str} &"

        # Safety check before execution
        result = guardian.check_spawn_cmd(full_cmd)
        if not result.ok:
            raise RuntimeError(f"spawn blocked by guardian: {'; '.join(result.violations)}")

        logger.info("Spawning brain: %s", full_cmd)

        async with self.brain_sem:
            proc = await asyncio.create_subprocess_exec(
                "bash", "-c", full_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()


def main() -> None:
    engine = Engine()
    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        logger.info("Interrupted.")


if __name__ == "__main__":
    main()
