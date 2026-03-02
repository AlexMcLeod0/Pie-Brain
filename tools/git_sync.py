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

    # ------------------------------------------------------------------

    async def _pre_task(self, params: dict) -> None:
        """Run git pull --rebase before a task."""
        repo_path = params.get("repo_path", ".")
        logger.info("GitSync pre-task: pull --rebase in %s", repo_path)
        await self._run("git", "pull", "--rebase", cwd=repo_path)

    async def _post_task(self, params: dict) -> None:
        """Checkout branch, stage, commit, and open a PR."""
        repo_path = params.get("repo_path", ".")
        branch = params.get("branch", "pie-brain/auto")
        message = params.get("message", "chore: automated update from Pie-Brain")
        # paths=None means stage everything; a list stages only those paths
        paths: list[str] | None = params.get("paths")
        pr_title = params.get("pr_title", message)
        pr_body = params.get("pr_body", "Automated update from Pie-Brain.")

        logger.info("GitSync post-task: branch=%s message=%r", branch, message)

        if await self._branch_exists(branch, repo_path):
            await self._run("git", "checkout", branch, cwd=repo_path)
        else:
            await self._run("git", "checkout", "-b", branch, cwd=repo_path)

        if paths:
            await self._run("git", "add", "--", *paths, cwd=repo_path)
        else:
            await self._run("git", "add", "-A", cwd=repo_path)

        await self._run("git", "commit", "-m", message, cwd=repo_path)
        await self._run(
            "gh", "pr", "create",
            "--title", pr_title,
            "--body", pr_body,
            cwd=repo_path,
        )

    # ------------------------------------------------------------------

    async def _branch_exists(self, branch: str, cwd: str) -> bool:
        """Return True if *branch* already exists in the repo at *cwd*."""
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "--verify", branch,
            cwd=cwd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0

    @staticmethod
    async def _run(*cmd: str, cwd: str = ".") -> str:
        """Run *cmd* in *cwd*, returning stdout. Raises RuntimeError on failure."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"Command {cmd} failed (rc={proc.returncode}): {stderr.decode().strip()}"
            )
        out = stdout.decode().strip()
        logger.debug("Command %s ok: %s", cmd, out)
        return out
