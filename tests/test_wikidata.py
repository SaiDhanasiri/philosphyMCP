"""Smoke tests for the Wikidata tool. Hits the live SPARQL endpoint; skips on
network failure."""

import asyncio

import pytest

from mcp_server.tools import wikidata


def _run(coro):
    return asyncio.run(coro)


def test_year_helper():
    assert wikidata._year("1724-04-22T00:00:00Z") == "1724"
    assert wikidata._year("-0384-01-01T00:00:00Z") == "384 BCE"
    assert wikidata._year("") == ""


def test_kant_profile():
    profile = _run(wikidata.get_philosopher_profile("Immanuel Kant"))
    if profile.get("error"):
        pytest.skip(f"wikidata unavailable: {profile['error']}")
    assert profile["name"] == "Immanuel Kant"
    assert profile["born"] == "1724"
    assert profile["died"] == "1804"
    assert isinstance(profile["works"], list)
    assert len(profile["works"]) <= wikidata.MAX_WORKS


def test_unknown_philosopher_returns_error_dict():
    profile = _run(
        wikidata.get_philosopher_profile("Zzzqqq Notaphilosopher Xyz")
    )
    assert "name" in profile
    # Either a clean "Not found" error or a network-skip.
    if "error" not in profile:
        pytest.fail("expected an error for an unknown name")
