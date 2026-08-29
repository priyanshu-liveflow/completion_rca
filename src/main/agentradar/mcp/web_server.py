"""MCP server over Bright Data. Tools: web_search, scrape_page."""

from __future__ import annotations

from typing import Any

from src.main.agentradar.adapters.brightdata import BdataClient, BdataError, WebClient
from src.main.agentradar.contracts.web import PageContent, SearchHit, SearchResults
from src.main.agentradar.mcp._server import ToolError, serve, tool

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


def main() -> None:
    """Entry: `python -m src.main.agentradar.mcp.web_server --port 8766`."""
    import argparse

    parser = argparse.ArgumentParser(description="AgentRadar Bright Data MCP server")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    serve("mcp-web", args.port)


if __name__ == "__main__":
    main()
