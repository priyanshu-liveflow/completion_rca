"""MCP server over Bright Data. Tools: web_search, scrape_page, run_collector."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.main.agentradar.adapters.brightdata import BdataClient, BdataError, WebClient
from src.main.agentradar.contracts.collector import CollectorRun, CollectorSpec
from src.main.agentradar.contracts.web import PageContent, SearchHit, SearchResults
from src.main.agentradar.core.health import evaluate
from src.main.agentradar.mcp._server import ToolError, serve, tool

COLLECTOR_DIR = Path(__file__).resolve().parents[4] / "collectors"

# A bare name. No separator means no way out of collectors/, and the leading
# class rules out `..` without a second check.
_COLLECTOR_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_client: WebClient | None = None


def set_client(client: WebClient) -> None:
    """Inject a WebClient. Tests pass a fixture-backed fake."""
    global _client
    _client = client


def get_client() -> WebClient:
    """Active client, defaulting to the Bright Data CLI adapter."""
    if _client is None:
        return BdataClient()
    return _client


def _hits_from(rows: list[dict[str, Any]]) -> list[SearchHit]:
    return [
        SearchHit(
            title=str(row.get("title") or ""),
            url=str(row.get("url") or ""),
            snippet=str(row.get("snippet") or ""),
        )
        for row in rows
    ]


@tool(
    "web_search",
    "Search the web through Bright Data SERP. Returns organic hits as SearchResults.",
    {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query, e.g. a package migration guide",
            },
            "limit": {
                "type": "integer",
                "description": "Max hits to return. Default 10.",
            },
        },
        "required": ["query"],
    },
)
def web_search(query: str, limit: int = 10) -> SearchResults:
    """SERP via the injected WebClient. Never returns a bare dict."""
    try:
        rows = get_client().search(query, limit=limit)
    except BdataError as exc:
        raise ToolError("bdata", str(exc)) from exc
    return SearchResults(query=query, hits=_hits_from(rows))


@tool(
    "scrape_page",
    "Fetch a URL through Bright Data Web Unlocker. Returns markdown PageContent.",
    {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Absolute URL to scrape (migration guides, changelogs)",
            },
        },
        "required": ["url"],
    },
)
def scrape_page(url: str) -> PageContent:
    """Web Unlocker via the injected WebClient. Feeds patch-writing in later PRs."""
    try:
        text = get_client().scrape(url)
    except BdataError as exc:
        raise ToolError("bdata", str(exc)) from exc
    return PageContent(url=url, text=text)


def _read_spec(path: Path) -> CollectorSpec:
    """Load one collector manifest.

    `CLAUDE.md` documents the on-disk shape with thresholds nested under a
    `health` block, while `CollectorSpec` -- frozen in PR1 and built against by
    four later PRs -- carries them flat. The manifests stay in the documented
    shape and the block is flattened here. Flat keys are also accepted, so a
    `CollectorSpec.model_dump()` round-trips back through this loader.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolError("invalid_collector", f"{path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ToolError("invalid_collector", f"{path.name} is not a JSON object")
    health = payload.get("health") or {}
    if not isinstance(health, dict):
        raise ToolError("invalid_collector", f"{path.name}: 'health' is not an object")
    flat = {key: value for key, value in payload.items() if key != "health"}
    try:
        return CollectorSpec.model_validate({**flat, **health})
    except ValidationError as exc:
        fields = ", ".join(
            ".".join(str(part) for part in err["loc"]) for err in exc.errors()
        )
        raise ToolError(
            "invalid_collector", f"{path.name}: bad fields: {fields}"
        ) from exc


def load_spec(collector: str) -> CollectorSpec:
    """Resolve a collector by manifest stem or by its `c_*` id."""
    if not _COLLECTOR_NAME.match(collector):
        raise ToolError(
            "invalid_input", f"collector {collector!r} is not a bare manifest name"
        )
    direct = COLLECTOR_DIR / f"{collector}.json"
    if direct.is_file():
        return _read_spec(direct)
    for path in sorted(COLLECTOR_DIR.glob("*.json")):
        spec = _read_spec(path)
        if spec.id == collector:
            return spec
    raise ToolError(
        "unknown_collector", f"no collector {collector!r} under {COLLECTOR_DIR.name}/"
    )


@tool(
    "run_collector",
    "Run a Bright Data collector, validate its coverage, and heal it if it degraded.",
    {
        "type": "object",
        "properties": {
            "collector": {
                "type": "string",
                "description": "Collector id (c_*) or manifest stem under collectors/",
            },
        },
        "required": ["collector"],
    },
)
def run_collector(collector: str) -> CollectorRun:
    """Run, evaluate, heal, re-run. Reports health before *and* after.

    Healing polls to completion inside the adapter: `bdata scraper heal` is
    invoked with `--auto-approve` under the collector timeout, so the call
    returns only once the repair has settled.

    A `BdataError` anywhere becomes a `ToolError` rather than a thin report --
    consistent with the other tools here, and it never dresses a dead CLI up as
    a collector that merely found nothing. Post-degradation messages carry the
    symptom so the failure is still diagnosable.
    """
    spec = load_spec(collector)
    client = get_client()
    try:
        rows = client.run_collector(spec)
    except BdataError as exc:
        raise ToolError("bdata", str(exc)) from exc

    health = evaluate(rows, spec)
    if health.healthy or health.symptom is None:
        return CollectorRun(spec_id=spec.id, rows=rows, health=health)

    # The id is the durable artifact: heal repairs the collector behind
    # `spec.id`, it never mints a new one.
    try:
        healed = client.heal_collector(spec.id, health.symptom, spec.url)
    except BdataError as exc:
        raise ToolError(
            "bdata", f"heal of {spec.id} failed: {exc} (symptom: {health.symptom})"
        ) from exc
    if not healed:
        return CollectorRun(spec_id=spec.id, rows=rows, health=health, healed=False)

    try:
        rows_after = client.run_collector(spec)
    except BdataError as exc:
        raise ToolError(
            "bdata",
            f"re-run of {spec.id} after heal failed: {exc} (symptom: {health.symptom})",
        ) from exc
    return CollectorRun(
        spec_id=spec.id,
        rows=rows_after,
        health=health,
        healed=True,
        health_after_heal=evaluate(rows_after, spec),
    )


def main() -> None:
    """Entry: `python -m src.main.agentradar.mcp.web_server --port 8766`."""
    import argparse

    parser = argparse.ArgumentParser(description="AgentRadar Bright Data MCP server")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    serve("mcp-web", args.port)


if __name__ == "__main__":
    main()
