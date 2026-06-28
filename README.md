# Philosophy Agent

A philosophy agent with an MCP server backend. Ask a natural-language question
about a philosophical topic and the agent surfaces multiple philosophers'
perspectives, grounded in real data from the Stanford Encyclopedia of Philosophy
(SEP), PhilPapers, and Wikidata.

The agent:

1. Identifies the philosophers most relevant to your question.
2. Fetches real content about them and their positions via MCP tools.
3. Synthesizes a response representing each philosopher's view in their own
   conceptual framework.
4. Notes where they agree, diverge, or directly contradict each other.

## Architecture

```
agent/runner.py  ──(stdio)──►  mcp_server/server.py
      │                              │
      ▼                              ├─ get_sep_entry          (SEP scrape)
  Claude (Anthropic API)            ├─ search_philpapers      (PhilPapers API)
   ReAct tool loop                  └─ get_philosopher_profile (Wikidata SPARQL)
```

The runner connects to the MCP server as a local stdio subprocess, lists its
tools, and runs a ReAct loop: the model requests tool calls, the runner executes
them against the MCP server, and the results are fed back until the model
produces a final answer.

### Model-agnostic by design

The **MCP server is not tied to any model** — it's a standard Model Context
Protocol server exposing three tools. Any MCP client can use it (Claude Desktop,
Cursor, your own client, etc.). Only the *runner* (the MCP client that drives an
LLM) is model-specific. Two runners ship here:

- `agent/runner.py` — drives **Claude** (Anthropic SDK). The original spec target.
- `agent/gemini_runner.py` — drives **Google Gemini** (`google-genai` SDK).

Both talk to the same unchanged MCP server. Swapping the model means swapping the
runner, not the server.

## Install

Requires Python 3.11+.

```bash
# With uv (recommended)
uv venv
uv pip install -e .            # core (Claude runner)
uv pip install -e ".[gemini]"  # add the Gemini runner
uv pip install -e ".[dev]"     # add pytest

# Or with pip
python -m venv .venv && source .venv/bin/activate
pip install -e ".[gemini,dev]"
```

## Configure

Set the API key for whichever runner you use.

```bash
# Claude runner (agent/runner.py)
export ANTHROPIC_API_KEY="sk-ant-..."   # from console.anthropic.com

# Gemini runner (agent/gemini_runner.py)
export GEMINI_API_KEY="..."             # from aistudio.google.com/apikey
export GEMINI_MODEL="gemini-2.5-pro"    # optional; default gemini-2.5-flash
```

The MCP server itself needs no credentials for SEP and Wikidata. PhilPapers'
live API now rejects keyless requests (HTTP 403); if you have a PhilPapers API
key, set `PHILPAPERS_API_KEY` to enable `search_philpapers`. Without it, that one
tool degrades gracefully (returns an error item) and the agent works from SEP and
Wikidata, which need no key.

## Run

```bash
# Claude
python -m agent.runner "What do empiricists say about personal identity?"

# Gemini (same question, same MCP server, different model)
python -m agent.gemini_runner "What do empiricists say about personal identity?"
```

Tool activity is logged to stderr; the final synthesized answer is printed to
stdout.

Examples:

```bash
python -m agent.runner "What is the mind-body problem?"
python -m agent.runner "How do Kant and Hume differ on causation?"
python -m agent.runner "What are the recent debates about free will?"
```

## MCP tools

| Tool | Source | Input |
|------|--------|-------|
| `get_sep_entry` | SEP (`plato.stanford.edu`) | `slug` (or a topic; auto-resolved) |
| `search_philpapers` | PhilPapers API | `query`, `limit` (default 5, max 10) |
| `get_philosopher_profile` | Wikidata SPARQL | `name` |

All tools catch their own errors and return error strings/dicts rather than
raising, and all HTTP calls use a 10-second timeout.

You can also run the MCP server on its own (for use with any MCP client):

```bash
python -m mcp_server.server
```

## Tests

The tests are live smoke tests against the three data sources; they skip
gracefully when the network is unavailable.

```bash
uv pip install -e ".[dev]"
pytest
```

## Constraints

- SEP content is truncated to ~6000 words before returning to the model.
- PhilPapers abstracts are truncated to 300 characters.
- Wikidata notable works are capped at 5 items.
- The agent uses only what the tools return — it does not invent positions.
