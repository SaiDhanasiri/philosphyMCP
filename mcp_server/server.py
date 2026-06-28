"""Philosophy MCP server.

Exposes three tools over stdio:
  - get_sep_entry          (Stanford Encyclopedia of Philosophy)
  - search_philpapers      (PhilPapers REST API)
  - get_philosopher_profile (Wikidata SPARQL)

Run directly for stdio transport:
    python -m mcp_server.server
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server.tools import philpapers, sep, wikidata

mcp = FastMCP("philosophy")


@mcp.tool()
async def get_sep_entry(slug: str) -> str:
    """Fetch the main content of a Stanford Encyclopedia of Philosophy entry by slug.

    Returns cleaned plain text suitable for LLM consumption. The slug is the SEP
    URL slug, e.g. "freewill", "kant", "personal-identity". A human-friendly topic
    (e.g. "free will") is resolved to the correct slug automatically.
    """
    return await sep.get_sep_entry(slug)


@mcp.tool()
async def search_philpapers(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search PhilPapers for academic papers on a philosophy topic.

    Returns a list of paper records with title, authors, abstract, url, and year.
    `query` is a natural language search query; `limit` is the max number of
    results (default 5, max 10).
    """
    return await philpapers.search_philpapers(query, limit)


@mcp.tool()
async def get_philosopher_profile(name: str) -> dict[str, Any]:
    """Fetch structured biographical and philosophical data for a named philosopher.

    Sourced from Wikidata. Returns era, school(s) of thought, influences, major
    works, and birth/death years. `name` is the philosopher's name, e.g.
    "Immanuel Kant", "David Hume".
    """
    return await wikidata.get_philosopher_profile(name)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
