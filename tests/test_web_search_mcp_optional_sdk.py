"""Preserve import-only use without the optional MCP SDK."""

import subprocess
import sys
from pathlib import Path


def test_module_import_does_not_load_optional_sdk() -> None:
    """A fresh process rejects every MCP import before loading the gateway."""
    script = '''
import importlib.abc
import importlib
import sys
import typing

class NoMCP(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mcp" or fullname.startswith("mcp."):
            raise ModuleNotFoundError("optional SDK deliberately unavailable", name=fullname)

for name in tuple(sys.modules):
    if name == "mcp" or name.startswith("mcp."):
        del sys.modules[name]
blocker = NoMCP()
sys.meta_path.insert(0, blocker)
gateway = importlib.import_module("contextual_orchestrator.web_search_mcp")
assert not any(name == "mcp" or name.startswith("mcp.") for name in sys.modules)
assert typing.get_type_hints(gateway._mcp_tool_error)["return"] is typing.Any
# Construction is lazy, not silently available without its SDK.
try:
    gateway._mcp_tool_error("web_search", RuntimeError("private sentinel"))
except ModuleNotFoundError as error:
    assert error.name == "mcp"
else:
    raise AssertionError("error envelope construction did not require the SDK")
sys.meta_path.remove(blocker)
# The exact same imported helper works once SDK loading becomes available.
result = gateway._mcp_tool_error("web_search", RuntimeError("private sentinel"))
assert result.is_error is True
assert [item.text for item in result.content] == ["Error executing tool web_search"]
assert "private sentinel" not in result.model_dump_json()
'''
    result = subprocess.run(
        [sys.executable, "-B", "-W", "error", "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
