"""Main async engine loop."""
import asyncio
import logging
from pathlib import Path

from config.settings import get_settings
from core.db import (
    TaskStatus,
    init_db,
    get_pending_tasks,
    update_task_status,
    setup_logging,
)
from core.router import Router
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

    async def run(self) -> None:
        """Start the engine; polls DB and dispatches tasks indefinitely."""
        setup_logging(self.settings.log_dir)
        await init_db(self.settings.db_path)
        self._running = True
        logger.info(
            "Engine started. model=%s brain=%s",
            self.settings.ollama_model,
            self.settings.default_cloud_brain,
        )
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

            # Route via Ollama
            router_output = await self.router.route(task.request_text)
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

            if router_output.handoff:
                await self._spawn_brain(router_output.tool_name, router_output.params)
            else:
                tool_cls = TOOL_REGISTRY.get(router_output.tool_name)
                if tool_cls is None:
                    raise ValueError(f"Unknown tool: {router_output.tool_name!r}")
                tool = tool_cls()
                # Inject task ID so tools can name output files unambiguously
                params = {**router_output.params, "_task_id": task.id}
                await tool.run_local(params)

            await update_task_status(db, task.id, TaskStatus.done)

        except Exception as exc:
            logger.exception("Task %d failed: %s", task.id, exc)
            await update_task_status(
                db, task.id, TaskStatus.failed,
                metadata={"error": str(exc)},
            )

    async def _spawn_brain(self, tool_name: str, params: dict) -> None:
        """Spawn a cloud brain subprocess; uses nohup for harness-restart survival."""
        brain = self.brain_registry.get(self.settings.default_cloud_brain)
        cmd_str = brain.get_spawn_cmd(tool_name, params)

        # Wrap in nohup so the child outlives a harness restart
        full_cmd = f"nohup {cmd_str} &"
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
