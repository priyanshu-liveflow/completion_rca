"""In-memory doubles. Downstream tests type-hint CodeGraph and pass these."""

from __future__ import annotations

from typing import Any

from src.main.agentradar.contracts.impact import ContactPoint


class FakeCodeGraph:
    """Canned graph. No FalkorDB, no socket."""

    def __init__(
        self,
        *,
        points: list[ContactPoint] | None = None,
        callers: dict[int, list[dict[str, Any]]] | None = None,
        chains: dict[tuple[str, str], list[dict[str, Any]]] | None = None,
        sources: dict[int, str] | None = None,
    ) -> None:
        self.points = points or []
        self.callers = callers or {}
        self.chains = chains or {}
        self.sources = sources or {}

    def find_contact_points(
        self, symbol: str, repo: str, limit: int = 15
    ) -> list[ContactPoint]:
        matched = [p for p in self.points if p.symbol == symbol]
        return matched[:limit]

    def callers_of(self, fid: int, repo: str, limit: int = 25) -> list[dict[str, Any]]:
        return list(self.callers.get(fid, [])[:limit])

    def call_chain(
        self, frm: str, to: str, repo: str, max_hops: int = 4
    ) -> list[dict[str, Any]]:
        return list(self.chains.get((frm, to), []))

    def read_source(self, fid: int, repo: str, max_chars: int = 1500) -> str:
        text = self.sources.get(fid, "")
        return text[:max_chars]


def demo_fastmcp_graph() -> FakeCodeGraph:
    """Contact points that match configs/demo.yaml expected_contact_points."""
    symbol = "FastMCP"
    points = [
        ContactPoint(
            symbol=symbol,
            function_name="mcp",
            fid=1,
            file_path="src/intervals_mcp_server/mcp_instance.py",
            line=17,
        ),
        ContactPoint(
            symbol=symbol,
            function_name="client",
            fid=2,
            file_path="src/intervals_mcp_server/api/client.py",
            line=17,
        ),
        ContactPoint(
            symbol=symbol,
            function_name="setup",
            fid=3,
            file_path="src/intervals_mcp_server/server_setup.py",
            line=1,
        ),
        ContactPoint(
            symbol=symbol,
            function_name="tools_init",
            fid=4,
            file_path="src/intervals_mcp_server/tools/__init__.py",
            line=1,
        ),
    ]
    return FakeCodeGraph(
        points=points,
        callers={1: [{"name": "make_app", "fid": 10}]},
        chains={
            ("make_app", "mcp"): [
                {"name": "make_app", "fid": 10},
                {"name": "mcp", "fid": 1},
            ]
        },
        sources={1: "from mcp.server.fastmcp import FastMCP\n"},
    )
