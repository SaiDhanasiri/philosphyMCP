"""CLI agent loop for the philosophy agent (Claude / Anthropic).

Connects to the philosophy MCP server over stdio (as a local subprocess), then
runs a ReAct-style loop with Claude: Claude calls MCP tools, the runner executes
them and returns results, repeating until Claude produces a final text answer.

Usage:
    python -m agent.runner "What do empiricists say about personal identity?"

For a Gemini-driven equivalent, see agent/gemini_runner.py.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import anthropic
from mcp import ClientSession
from mcp.client.stdio import stdio_client

from agent._mcp import result_to_text, server_params
from agent.prompts import SYSTEM_PROMPT

MODEL = "claude-opus-4-8"
MAX_TOKENS = 16000
MAX_TURNS = 12


def _to_anthropic_tools(mcp_tools: Any) -> list[dict[str, Any]]:
    """Convert MCP tool definitions into the Anthropic tools schema."""
    tools = []
    for tool in mcp_tools:
        tools.append(
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
        )
    return tools


async def _run(question: str) -> str:
    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tools = _to_anthropic_tools(tools_result.tools)

            client = anthropic.AsyncAnthropic()
            messages: list[dict[str, Any]] = [
                {"role": "user", "content": question}
            ]

            for _ in range(MAX_TURNS):
                response = await client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=SYSTEM_PROMPT,
                    thinking={"type": "adaptive"},
                    output_config={"effort": "high"},
                    tools=tools,
                    messages=messages,
                )

                # Preserve the full assistant turn (incl. thinking/tool_use blocks).
                messages.append({"role": "assistant", "content": response.content})

                if response.stop_reason != "tool_use":
                    return _final_text(response)

                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    print(
                        f"[tool] {block.name}({block.input})",
                        file=sys.stderr,
                        flush=True,
                    )
                    try:
                        result = await session.call_tool(block.name, block.input)
                        content = result_to_text(result)
                        is_error = bool(getattr(result, "isError", False))
                    except Exception as exc:  # noqa: BLE001
                        content = f"Tool execution failed: {exc}"
                        is_error = True
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": content,
                            "is_error": is_error,
                        }
                    )

                messages.append({"role": "user", "content": tool_results})

            return "Reached the maximum number of reasoning turns without a final answer."


def _final_text(response: Any) -> str:
    parts = [block.text for block in response.content if block.type == "text"]
    return "\n".join(parts).strip() or "(no text response)"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print('Usage: python -m agent.runner "<your question>"', file=sys.stderr)
        return 2

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print(
            "Error: set ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) in your environment.",
            file=sys.stderr,
        )
        return 1

    question = " ".join(argv)
    try:
        answer = asyncio.run(_run(question))
    except anthropic.APIError as exc:
        print(f"Anthropic API error: {exc}", file=sys.stderr)
        return 1
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
