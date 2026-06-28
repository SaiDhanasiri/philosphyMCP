"""Wikidata philosopher-profile tool.

Resolves a philosopher's name to a Wikidata entity (via the lightweight entity
search API), then runs a fast, QID-keyed SPARQL query for structured
biographical and philosophical data. Querying by QID keeps us well within the
10s timeout — matching on a lowercased label instead forces a full-dataset scan
and times out.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
ENTITY_SEARCH = "https://www.wikidata.org/w/api.php"
TIMEOUT = 10.0
MAX_WORKS = 5
_USER_AGENT = "PhilosophyAgent/0.1 (educational; MCP tool)"

# Properties:
#   P2348 = era / period
#   P135  = movement, P140 = religion/worldview  -> "schools of thought"
#   P737  = influenced by
#   P800  = notable work
#   P569  = date of birth, P570 = date of death
_QUERY_TEMPLATE = """
SELECT ?item
  (SAMPLE(?label) AS ?name)
  (SAMPLE(?desc) AS ?description)
  (GROUP_CONCAT(DISTINCT ?eraLabel; separator="|") AS ?eras)
  (GROUP_CONCAT(DISTINCT ?schoolLabel; separator="|") AS ?schools)
  (GROUP_CONCAT(DISTINCT ?influenceLabel; separator="|") AS ?influences)
  (GROUP_CONCAT(DISTINCT ?workLabel; separator="|") AS ?works)
  (SAMPLE(?birth) AS ?born)
  (SAMPLE(?death) AS ?died)
WHERE {{
  VALUES ?item {{ wd:{qid} }}
  OPTIONAL {{ ?item rdfs:label ?label . FILTER(LANG(?label) = "en") }}
  OPTIONAL {{ ?item schema:description ?desc . FILTER(LANG(?desc) = "en") }}
  OPTIONAL {{ ?item wdt:P2348 ?era . ?era rdfs:label ?eraLabel . FILTER(LANG(?eraLabel) = "en") }}
  OPTIONAL {{
    {{ ?item wdt:P135 ?school . }} UNION {{ ?item wdt:P140 ?school . }}
    ?school rdfs:label ?schoolLabel . FILTER(LANG(?schoolLabel) = "en")
  }}
  OPTIONAL {{ ?item wdt:P737 ?influence . ?influence rdfs:label ?influenceLabel . FILTER(LANG(?influenceLabel) = "en") }}
  OPTIONAL {{ ?item wdt:P800 ?work . ?work rdfs:label ?workLabel . FILTER(LANG(?workLabel) = "en") }}
  OPTIONAL {{ ?item wdt:P569 ?birth . }}
  OPTIONAL {{ ?item wdt:P570 ?death . }}
}}
GROUP BY ?item
LIMIT 1
"""

_YEAR = re.compile(r"^(-?)(\d{1,4})")
_QID = re.compile(r"^Q\d+$")


def _year(iso: str) -> str:
    """Turn a Wikidata dateTime ('1724-04-22T00:00:00Z', '-0384-...Z') into a year."""
    if not iso:
        return ""
    match = _YEAR.match(iso)
    if not match:
        return iso
    sign, digits = match.groups()
    year = str(int(digits))
    return f"{year} BCE" if sign == "-" else year


def _split(concat: str) -> list[str]:
    return [part for part in concat.split("|") if part] if concat else []


def _value(binding: dict[str, Any], key: str) -> str:
    field = binding.get(key)
    return field["value"] if field and field.get("value") else ""


async def _resolve_qid(client: httpx.AsyncClient, name: str) -> str | None:
    """Resolve a philosopher's name to a Wikidata QID via wbsearchentities.

    Prefers an entity whose description mentions a philosopher/thinker so we don't
    pick, say, a band or a film named after the person.
    """
    params = {
        "action": "wbsearchentities",
        "search": name,
        "language": "en",
        "uselang": "en",
        "type": "item",
        "format": "json",
        "limit": 7,
    }
    resp = await client.get(ENTITY_SEARCH, params=params)
    resp.raise_for_status()
    results = resp.json().get("search", [])
    if not results:
        return None
    for item in results:
        desc = (item.get("description") or "").lower()
        if any(word in desc for word in ("philosoph", "thinker", "logician")):
            return item.get("id")
    return results[0].get("id")


async def get_philosopher_profile(name: str) -> dict[str, Any]:
    """Fetch structured Wikidata data for a philosopher. Never raises."""
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/sparql-results+json",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers) as client:
            qid = await _resolve_qid(client, name)
            if not qid or not _QID.match(qid):
                return {"name": name, "error": "Not found in Wikidata"}

            query = _QUERY_TEMPLATE.format(qid=qid)
            resp = await client.post(
                SPARQL_ENDPOINT, data={"query": query, "format": "json"}
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        return {"name": name, "error": f"Wikidata request failed: {type(exc).__name__}: {exc}"}
    except Exception as exc:  # noqa: BLE001 - tools must never raise
        return {"name": name, "error": f"Unexpected Wikidata error: {type(exc).__name__}: {exc}"}

    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        return {"name": name, "error": "Not found in Wikidata"}

    row = bindings[0]
    return {
        "name": _value(row, "name") or name,
        "description": _value(row, "description"),
        "era": "; ".join(_split(_value(row, "eras"))),
        "schools": _split(_value(row, "schools")),
        "influences": _split(_value(row, "influences")),
        "works": _split(_value(row, "works"))[:MAX_WORKS],
        "born": _year(_value(row, "born")),
        "died": _year(_value(row, "died")),
    }
