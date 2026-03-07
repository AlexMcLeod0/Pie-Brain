"""Shared filesystem utilities used across core and tools."""
import os
import tempfile
from pathlib import Path


def atomic_write(path: str | Path, content: str) -> None:
    """Write *content* to *path* atomically using a temp file + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise
