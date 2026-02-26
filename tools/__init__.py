"""Auto-collect all BaseTool subclasses into TOOL_REGISTRY at import time."""
import importlib
import pkgutil
from pathlib import Path

from tools.base import BaseTool

# Import every module in this package so subclasses are registered
_pkg_path = str(Path(__file__).parent)
for _info in pkgutil.iter_modules([_pkg_path]):
    if _info.name not in ("base",):
        importlib.import_module(f"tools.{_info.name}")

TOOL_REGISTRY: dict[str, type[BaseTool]] = {
    cls.tool_name: cls
    for cls in BaseTool.__subclasses__()
    if cls.tool_name
}

__all__ = ["BaseTool", "TOOL_REGISTRY"]
