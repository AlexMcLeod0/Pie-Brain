"""Git sync tool — pre-task pull and post-task commit/PR."""
import asyncio
import logging

from tools.base import BaseTool

logger = logging.getLogger(__name__)


class GitSyncTool(BaseTool):
    tool_name = "git_sync"

    async def run_local(self, params: dict) -> None:
        phase = params.get("phase", "pre")
        if phase == "post":
            await self._post_task(params)
        else:
            await self._pre_task(params)

    def get_spawn_cmd(self, params: dict) -> str:
        import json
        return f"python -m tools.git_sync_runner '{json.dumps(params)}'"

    # ------------------------------------------------------------------
    async def _pre_task(self, params: dict) -> None:
        """Run git pull --rebase before a task. (stub)"""
        repo_path = params.get("repo_path", ".")
        logger.info("GitSync pre-task: pull --rebase in %s", repo_path)
        # TODO: run git pull --rebase
        await self._run("git", "pull", "--rebase", cwd=repo_path)

    async def _post_task(self, params: dict) -> None:
        """Checkout branch, commit, and open a PR. (stub)"""
        repo_path = params.get("repo_path", ".")
        branch = params.get("branch", "pie-brain/auto")
        message = params.get("message", "chore: automated update from Pie-Brain")
        logger.info("GitSync post-task: branch=%s message=%r", branch, message)

        # TODO: proper branch detection, staging, and PR creation
        await self._run("git", "checkout", "-b", branch, cwd=repo_path)
        await self._run("git", "add", "-A", cwd=repo_path)
        await self._run("git", "commit", "-m", message, cwd=repo_path)
        await self._run("gh", "pr", "create", "--fill", cwd=repo_path)

    @staticmethod
    async def _run(*cmd: str, cwd: str = ".") -> None:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error("Command %s failed (rc=%d): %s", cmd, proc.returncode, stderr.decode())
        else:
            logger.debug("Command %s ok: %s", cmd, stdout.decode())
