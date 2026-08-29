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
        imports: list[dict[str, Any]] | None = None,
        functions: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.points = points or []
        self.callers = callers or {}
        self.chains = chains or {}
        self.sources = sources or {}
        self.imports = imports or []
        self.functions = functions or {}

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

    def import_edges(self, repo: str) -> list[dict[str, Any]]:
        return [dict(edge) for edge in self.imports]

    def functions_in(self, file_path: str, repo: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.functions.get(file_path, [])]


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


# The measured shape of the indexed demo repo, from docs/demo-repo.md. Five test
# modules, their real IMPORTS edges, and the four files that touch FastMCP.
# `select_tests` must reach exactly two of the five from this data.
_TEST_IMPORTS = {
    "tests/test_server.py": "intervals_mcp_server.tools",
    "tests/test_make_intervals_request.py": "intervals_mcp_server.api",
    "tests/test_formatting.py": "utils.formatting",
    "tests/test_validation.py": "utils.validation",
    "tests/test_value.py": "utils.types",
}

_TEST_FUNCTIONS = {
    "tests/test_server.py": [
        {"name": "<module>", "fid": 100},
        {"name": "test_server_starts", "fid": 101},
        {"name": "test_tools_registered", "fid": 102},
    ],
    "tests/test_make_intervals_request.py": [
        {"name": "<module>", "fid": 110},
        {"name": "test_make_intervals_request", "fid": 111},
    ],
    "tests/test_formatting.py": [
        {"name": "<module>", "fid": 120},
        {"name": "test_format_activity", "fid": 121},
    ],
    "tests/test_validation.py": [
        {"name": "<module>", "fid": 130},
        {"name": "test_validate_date", "fid": 131},
    ],
    "tests/test_value.py": [
        {"name": "<module>", "fid": 140},
        {"name": "test_value_roundtrip", "fid": 141},
    ],
}


def demo_selection_graph() -> FakeCodeGraph:
    """The FastMCP graph plus the IMPORTS edges and test nodes PR4 walks."""
    graph = demo_fastmcp_graph()
    graph.imports = [
        {"file_path": path, "imported": module}
        for path, module in _TEST_IMPORTS.items()
    ] + [
        # A source-to-source edge, so the walk has a second hop to take.
        {
            "file_path": "src/intervals_mcp_server/server_setup.py",
            "imported": "intervals_mcp_server.mcp_instance",
        },
    ]
    graph.functions = {
        path: [dict(row, file_path=path) for row in rows]
        for path, rows in _TEST_FUNCTIONS.items()
    }
    return graph
