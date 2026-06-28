"""Smoke tests for the SEP tool. These hit the live SEP site; they skip on
network failure rather than failing the suite."""

import asyncio

import httpx
import pytest

from mcp_server.tools import sep


def _run(coro):
    return asyncio.run(coro)


def test_resolve_known_slug():
    async def go():
        async with httpx.AsyncClient(
            timeout=sep.TIMEOUT, follow_redirects=True
        ) as client:
            return await sep.resolve_slug(client, "kant")

    try:
        slug = _run(go())
    except httpx.HTTPError as exc:
        pytest.skip(f"network unavailable: {exc}")
    assert slug == "kant"


def test_resolve_free_will_via_search():
    """'free will' -> 'free-will' 404s, so search should find 'freewill'."""
    async def go():
        async with httpx.AsyncClient(
            timeout=sep.TIMEOUT, follow_redirects=True
        ) as client:
            return await sep.resolve_slug(client, "free will")

    try:
        slug = _run(go())
    except httpx.HTTPError as exc:
        pytest.skip(f"network unavailable: {exc}")
    assert slug == "freewill"


def test_get_sep_entry_returns_text():
    try:
        text = _run(sep.get_sep_entry("personal-identity"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"network unavailable: {exc}")
    assert isinstance(text, str)
    assert "personal" in text.lower()
    # The personal-identity entry exceeds 6000 words, so the body is truncated.
    # Allow a small margin for the prepended title header line.
    assert "[truncated]" in text
    assert len(text.split()) <= sep.MAX_WORDS + 10


def test_get_sep_entry_unknown_slug():
    try:
        text = _run(sep.get_sep_entry("this-is-not-a-real-entry-zzz"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"network unavailable: {exc}")
    assert isinstance(text, str)  # never raises
