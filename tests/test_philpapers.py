"""Smoke tests for the PhilPapers tool. Hits the live API; always returns a list
(never raises), so these assert shape and graceful degradation."""

import asyncio

from mcp_server.tools import philpapers


def _run(coro):
    return asyncio.run(coro)


def test_search_returns_list():
    results = _run(philpapers.search_philpapers("personal identity", limit=3))
    assert isinstance(results, list)
    assert len(results) >= 1
    # Each item is a normalized record or an {"error": ...} fallback.
    for item in results:
        assert isinstance(item, dict)


def test_limit_is_capped():
    results = _run(philpapers.search_philpapers("free will", limit=100))
    assert isinstance(results, list)
    assert len(results) <= philpapers.MAX_LIMIT


def test_normalize_truncates_abstract():
    record = {"title": "T", "abstract": "x" * 500}
    norm = philpapers._normalize(record)
    assert len(norm["abstract"]) <= philpapers.ABSTRACT_MAX_CHARS + 1  # +1 for ellipsis


def test_normalize_omits_missing_abstract():
    norm = philpapers._normalize({"title": "T"})
    assert "abstract" not in norm
    assert norm["title"] == "T"
    assert norm["authors"] == []
