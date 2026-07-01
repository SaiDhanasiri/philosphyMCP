from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from agent._mcp import result_to_text, server_params
from agent.prompts import SYSTEM_PROMPT

try:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types
except ImportError as exc:  # pragma: no cover - import guard
    genai = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc

DEFAULT_MODEL = "gemini-2.5-flash"
MAX_TURNS = 12


def _load_dotenv() -> None:
    """Populate os.environ from a project-local .env file (dependency-free).

    Walks up from this file to the project root looking for a `.env`. Existing
    environment variables win, so an explicit `export FOO=...` in the shell is
    never clobbered.
    """
    for parent in [Path(__file__).resolve().parent, *Path(__file__).resolve().parents]:
        env_path = parent / ".env"
        if env_path.is_file():
            break
    else:
        return

    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _model() -> str:
    return os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)


def _api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _to_gemini_tool(mcp_tools: Any) -> "types.Tool":
    """Convert MCP tool definitions into a single Gemini Tool.

    `parameters_json_schema` accepts a standard JSON Schema dict, so the MCP
    tools' `inputSchema` passes through almost verbatim (no lossy conversion).
    """
    declarations = [
        types.FunctionDeclaration(
            name=tool.name,
            description=tool.description or "",
            parameters_json_schema=tool.inputSchema,
        )
        for tool in mcp_tools
    ]
    return types.Tool(function_declarations=declarations)


def _final_text(content: Any) -> str:
    parts = getattr(content, "parts", None) or []
    texts = [p.text for p in parts if getattr(p, "text", None)]
    return "\n".join(texts).strip() or "(no text response)"


async def _run(question: str) -> str:
    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tool = _to_gemini_tool(tools_result.tools)

            client = genai.Client(api_key=_api_key())
            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[tool],
                # We route tool calls to the MCP server ourselves, so disable the
                # SDK's automatic (in-process) function calling.
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            )

            contents: list[Any] = [
                types.Content(role="user", parts=[types.Part.from_text(text=question)])
            ]

            for _ in range(MAX_TURNS):
                response = await client.aio.models.generate_content(
                    model=_model(), contents=contents, config=config
                )

                if not response.candidates:
                    return "Gemini returned no candidates (the request may have been blocked)."

                content = response.candidates[0].content
                contents.append(content)  # preserve the model turn

                parts = getattr(content, "parts", None) or []
                calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
                if not calls:
                    return _final_text(content)

                response_parts = []
                for call in calls:
                    args = dict(call.args) if call.args else {}
                    print(f"[tool] {call.name}({args})", file=sys.stderr, flush=True)
                    try:
                        result = await session.call_tool(call.name, args)
                        output = result_to_text(result)
                    except Exception as exc:  # noqa: BLE001
                        output = f"Tool execution failed: {exc}"
                    response_parts.append(
                        types.Part.from_function_response(
                            name=call.name, response={"result": output}
                        )
                    )

                contents.append(types.Content(role="user", parts=response_parts))

            return "Reached the maximum number of reasoning turns without a final answer."


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print('Usage: python -m agent.gemini_runner "<your question>"', file=sys.stderr)
        return 2

    if genai is None:
        print(
            "Error: the Gemini SDK is not installed. Run: uv pip install -e \".[gemini]\"\n"
            f"({_IMPORT_ERROR})",
            file=sys.stderr,
        )
        return 1

    if not _api_key():
        print(
            "Error: set GEMINI_API_KEY (or GOOGLE_API_KEY) in your environment.",
            file=sys.stderr,
        )
        return 1

    question = " ".join(argv)
    try:
        answer = asyncio.run(_run(question))
    except genai_errors.APIError as exc:
        print(f"Gemini API error: {exc}", file=sys.stderr)
        return 1
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
