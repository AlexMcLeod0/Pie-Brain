"""Dev mode: auto-pull git updates and restart the engine on new commits."""
import asyncio
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent


async def watch_for_updates(poll_interval: int = 60) -> None:
    """Periodically fetch from origin and restart if new commits are found.

    Uses FETCH_HEAD so no branch name is hard-coded — works regardless of
    which branch was cloned.  On a successful pull the process is replaced
    via os.execv so systemd (or any process supervisor) sees a clean restart.
    """
    repo = str(_PROJECT_ROOT)
    logger.info(
        "Dev mode enabled: polling for git updates every %ds (repo=%s)",
        poll_interval,
        repo,
    )

    while True:
        await asyncio.sleep(poll_interval)
        try:
            # ── Fetch from origin ────────────────────────────────────────────
            fetch = await asyncio.create_subprocess_exec(
                "git", "-C", repo, "fetch", "origin",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            rc = await fetch.wait()
            if rc != 0:
                logger.warning("Dev mode: git fetch failed (rc=%d), skipping", rc)
                continue

            # ── Count commits we're behind FETCH_HEAD ────────────────────────
            behind_proc = await asyncio.create_subprocess_exec(
                "git", "-C", repo, "rev-list", "HEAD..FETCH_HEAD", "--count",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await behind_proc.communicate()
            count = int(stdout.decode().strip() or "0")

            if count == 0:
                logger.debug("Dev mode: already up to date")
                continue

            logger.info(
                "Dev mode: %d new commit(s) detected — pulling and restarting",
                count,
            )

            # ── Pull ─────────────────────────────────────────────────────────
            pull = await asyncio.create_subprocess_exec(
                "git", "-C", repo, "pull", "--rebase",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            rc = await pull.wait()
            if rc != 0:
                logger.warning(
                    "Dev mode: git pull --rebase failed (rc=%d), skipping restart",
                    rc,
                )
                continue

            logger.info("Dev mode: pull succeeded — restarting engine")
            # Replace the current process; supervisor will see PID unchanged.
            os.execv(sys.executable, [sys.executable] + sys.argv)

        except Exception:
            logger.exception("Dev mode watcher error")
