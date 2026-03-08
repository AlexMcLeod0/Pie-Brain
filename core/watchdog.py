"""systemd watchdog integration.

Provides a dependency-free sd_notify() implementation (writes directly to
$NOTIFY_SOCKET) and a long-running heartbeat coroutine for the engine.

When the engine is *not* running under systemd, $NOTIFY_SOCKET is unset and
every call is a no-op — so this module is safe to use unconditionally.
"""
import asyncio
import logging
import os
import socket

logger = logging.getLogger(__name__)


def sd_notify(state: str) -> None:
    """Send a state string to the systemd notification socket.

    Common states:
        "READY=1"       — service is fully initialised and accepting work
        "WATCHDOG=1"    — heartbeat; resets the watchdog timer
        "STOPPING=1"    — clean shutdown in progress

    No-op when $NOTIFY_SOCKET is not set (i.e. not running under systemd).
    """
    notify_socket = os.environ.get("NOTIFY_SOCKET")
    if not notify_socket:
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(state.encode(), notify_socket)
    except OSError:
        logger.warning("sd_notify: failed to send %r to %s", state, notify_socket)


async def watchdog_heartbeat(interval: int = 30) -> None:
    """Send WATCHDOG=1 to systemd every *interval* seconds.

    The service file should set WatchdogSec to at least 2× this interval so
    a single slow iteration never triggers a spurious restart.  The engine
    starts this as a background task before entering its main loop.
    """
    logger.debug("Watchdog heartbeat started (interval=%ds)", interval)
    while True:
        sd_notify("WATCHDOG=1")
        await asyncio.sleep(interval)
