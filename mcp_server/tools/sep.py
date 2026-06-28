"""Stanford Encyclopedia of Philosophy (SEP) scraper tool.

Fetches the main content of an SEP entry, cleans it for LLM consumption, and
resolves human-friendly topics to SEP URL slugs (e.g. "free will" -> "freewill").

SEP has no single entry for some broad topics (e.g. "mind-body problem",
"philosophy of mind"), and its search can rank weak matches first. So when there
is no direct entry, this tool does NOT silently present the top hit as
authoritative: it returns the closest match clearly labeled as a fuzzy match,
plus other candidate slugs the agent can retry with.
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

SEP_BASE = "https://plato.stanford.edu"
SEARCH_URL = f"{SEP_BASE}/search/searcher.py"
TIMEOUT = 10.0
MAX_WORDS = 6000
MAX_CANDIDATES = 6
_USER_AGENT = "PhilosophyAgent/0.1 (educational; MCP tool)"

# Session-lived cache mapping a normalized topic/slug -> resolved SEP slug.
_slug_cache: dict[str, str] = {}

_FOOTNOTE_MARKER = re.compile(r"\[\d+\]")
_SLUG_FROM_HREF = re.compile(r"/entries/([^/#?]+)")


def _normalize(topic: str) -> str:
    """Lowercase a topic and turn spaces into hyphens (the obvious slug guess)."""
    return re.sub(r"\s+", "-", topic.strip().lower())


async def _entry_html(client: httpx.AsyncClient, slug: str) -> str | None:
    """Return the HTML of a SEP entry if it exists and has a main-text body."""
    try:
        resp = await client.get(f"{SEP_BASE}/entries/{slug}/")
    except httpx.HTTPError:
        return None
    if resp.status_code == 200 and 'id="main-text"' in resp.text:
        return resp.text
    return None


async def search_entries(client: httpx.AsyncClient, topic: str) -> list[tuple[str, str]]:
    """Return ranked (slug, title) pairs from SEP's search for a topic."""
    query = re.sub(r"[-_]+", " ", topic).strip()  # de-hyphenate slugs into words
    try:
        resp = await client.get(SEARCH_URL, params={"query": query})
        resp.raise_for_status()
    except httpx.HTTPError:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    results: list[tuple[str, str]] = []
    seen: set[str] = set()

    # SEP wraps each hit in div.result_listing with a div.result_title link.
    for listing in soup.select("div.result_listing"):
        link = listing.select_one(".result_title a[href]") or listing.find("a", href=True)
        if not link:
            continue
        match = _SLUG_FROM_HREF.search(link["href"])
        if not match:
            continue
        slug = match.group(1)
        if slug in seen:
            continue
        seen.add(slug)
        title = link.get_text(" ", strip=True)
        results.append((slug, title))

    # Fallback for any layout change: take entry links in document order.
    if not results:
        for link in soup.find_all("a", href=True):
            match = _SLUG_FROM_HREF.search(link["href"])
            if match and match.group(1) not in seen:
                seen.add(match.group(1))
                results.append((match.group(1), link.get_text(" ", strip=True)))
    return results


async def resolve_slug(client: httpx.AsyncClient, topic: str) -> str | None:
    """Resolve a topic or candidate slug to a real SEP entry slug.

    Tries the obvious transform first (lowercase, spaces -> hyphens), then falls
    back to the top SEP search result. Caches results for the session.
    """
    key = _normalize(topic)
    if not key:
        return None
    if key in _slug_cache:
        return _slug_cache[key]
    if await _entry_html(client, key):
        _slug_cache[key] = key
        return key
    results = await search_entries(client, topic)
    if results:
        _slug_cache[key] = results[0][0]
        return results[0][0]
    return None


def _clean_main_text(html: str) -> str | None:
    """Extract and clean the text of ``div#main-text`` from an SEP entry page."""
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("div", id="main-text")
    if main is None:
        return None

    # Drop scripts, styles, and navigation chrome.
    for tag in main.find_all(["script", "style", "nav"]):
        tag.decompose()

    # Drop footnote-marker anchors like [1], [2].
    for anchor in main.find_all("a"):
        if _FOOTNOTE_MARKER.fullmatch(anchor.get_text(strip=True)):
            anchor.decompose()

    text = main.get_text(separator=" ")
    # Remove any stray bracketed footnote markers and collapse whitespace.
    text = _FOOTNOTE_MARKER.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _truncate_words(text: str, max_words: int = MAX_WORDS) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " … [truncated]"


def _format_entry(slug: str, html: str) -> str | None:
    cleaned = _clean_main_text(html)
    if not cleaned:
        return None
    return f"# Stanford Encyclopedia of Philosophy: {slug}\n\n{_truncate_words(cleaned)}"


async def get_sep_entry(slug: str) -> str:
    """Fetch a cleaned SEP entry as plain text. Never raises; returns an error string.

    On a direct hit, returns the entry. When there is no exact entry, returns the
    closest search match clearly labeled as a fuzzy match, followed by other
    candidate slugs the caller can retry with.
    """
    headers = {"User-Agent": _USER_AGENT}
    key = _normalize(slug)
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=True, headers=headers
        ) as client:
            # 1. Direct hit (honor a cached resolution first).
            cached = _slug_cache.get(key)
            if cached:
                html = await _entry_html(client, cached)
                if html:
                    formatted = _format_entry(cached, html)
                    if formatted:
                        return formatted

            html = await _entry_html(client, key)
            if html:
                _slug_cache[key] = key
                formatted = _format_entry(key, html)
                if formatted:
                    return formatted

            # 2. No direct entry — search and surface candidates transparently.
            results = await search_entries(client, slug)
            if not results:
                return f"No SEP entry found for slug: {slug}"

            top_slug, top_title = results[0]
            html = await _entry_html(client, top_slug)
            if not html:
                return f"No SEP entry found for slug: {slug}"
            _slug_cache[key] = top_slug

            others = [s for s, _ in results[1:MAX_CANDIDATES]]
            note = (
                f"NOTE: No exact SEP entry for '{slug}'. Showing the closest search "
                f'match: "{top_title}" (slug: {top_slug}). If this is not the right '
                "entry, call get_sep_entry again with a more specific slug"
            )
            if others:
                note += f" — other candidate slugs: {', '.join(others)}"
            note += ".\n\n"

            formatted = _format_entry(top_slug, html)
            return note + formatted if formatted else f"No SEP entry found for slug: {slug}"
    except httpx.HTTPError as exc:
        return f"Error fetching SEP entry for '{slug}': {type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 - tools must never raise
        return f"Unexpected error fetching SEP entry for '{slug}': {type(exc).__name__}: {exc}"
