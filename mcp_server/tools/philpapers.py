from __future__ import annotations

import os
from typing import Any

import httpx

PHILPAPERS_SEARCH = "https://philpapers.org/api/search.pl"
TIMEOUT = 10.0
DEFAULT_LIMIT = 5
MAX_LIMIT = 10
ABSTRACT_MAX_CHARS = 300
_USER_AGENT = "PhilosophyAgent/0.1 (educational; MCP tool)"


def _coerce_records(data: Any) -> list[dict[str, Any]]:
    """PhilPapers' shape varies; defensively find the list of result records."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("docs", "results", "items", "entries", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if record.get(key):
            return record[key]
    return None


def _authors(record: dict[str, Any]) -> list[str]:
    raw = _first(record, "authors", "author", "creators")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        names: list[str] = []
        for item in raw:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                name = _first(item, "name", "fullname", "label")
                if name:
                    names.append(str(name))
        return names
    return []


def _normalize(record: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "title": _first(record, "title", "name") or "(untitled)",
        "authors": _authors(record),
        "url": _first(record, "url", "link", "pub_url") or "",
        "year": _first(record, "year", "date", "pub_year") or "",
    }
    abstract = _first(record, "abstract", "summary", "description")
    if abstract:
        abstract = str(abstract).strip()
        if len(abstract) > ABSTRACT_MAX_CHARS:
            abstract = abstract[:ABSTRACT_MAX_CHARS].rstrip() + "…"
        result["abstract"] = abstract
    return result


async def search_philpapers(query: str, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """Search PhilPapers and return normalized records. Never raises.

    On error, returns a single-item list containing an ``{"error": ...}`` dict so
    the caller always receives a list.
    """
    capped = max(1, min(int(limit) if limit else DEFAULT_LIMIT, MAX_LIMIT))
    # The spec specifies no API key for basic search; the live API now rejects
    # keyless requests with 403, so allow an optional key via env without
    # changing the default (empty) behavior.
    api_key = os.environ.get("PHILPAPERS_API_KEY", "")
    params = {"apiKey": api_key, "format": "json", "limit": capped, "q": query}
    headers = {"User-Agent": _USER_AGENT}
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=True, headers=headers
        ) as client:
            resp = await client.get(PHILPAPERS_SEARCH, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        return [{"error": f"PhilPapers request failed: {type(exc).__name__}: {exc}"}]
    except ValueError as exc:  # non-JSON body
        return [{"error": f"PhilPapers returned a non-JSON response: {type(exc).__name__}: {exc}"}]
    except Exception as exc:  # noqa: BLE001 - tools must never raise
        return [{"error": f"Unexpected PhilPapers error: {type(exc).__name__}: {exc}"}]

    records = _coerce_records(data)
    if not records:
        return [{"error": f"No PhilPapers results for query: {query}"}]
    return [_normalize(r) for r in records[:capped]]
