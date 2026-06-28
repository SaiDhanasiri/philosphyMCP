"""Shared helpers for connecting to the philosophy MCP server over stdio.

Both the Claude runner and the Gemini runner are MCP *clients*: they launch the
server (`python -m mcp_server.server`) as a local subprocess and talk to it over
stdio. Only the model-specific tool formatting and ReAct loop differ between
them, so the connection plumbing lives here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from mcp import StdioServerParameters

# Repo root = parent of the `agent` package; the server is launched from here so
# the `mcp_server` package is importable in the subprocess.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def server_params() -> StdioServerParameters:
    """Parameters for launching the philosophy MCP server as a stdio subprocess."""
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        cwd=str(PROJECT_ROOT),
        env={**os.environ},
    )


def result_to_text(result: Any) -> str:
    """Render an MCP CallToolResult's content blocks into a single string."""
    parts: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts) if parts else "(no content returned)"
