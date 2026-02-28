"""Message integrity middleware — called in providers before enqueue_task()."""
import logging

logger = logging.getLogger(__name__)

MAX_MESSAGE_LEN = 2000


def validate_message(text: str) -> tuple[bool, str]:
    """
    Validate an incoming message before it is written to the task queue.

    Returns (True, "") on success or (False, reason) on rejection.
    Rejection is logged at WARNING level by the caller.
    """
    if not text:
        return False, "Empty message."

    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        return False, f"Non-UTF-8 content: {exc}"

    if len(text) > MAX_MESSAGE_LEN:
        return False, f"Message too long ({len(text)} chars; limit {MAX_MESSAGE_LEN})."

    return True, ""
