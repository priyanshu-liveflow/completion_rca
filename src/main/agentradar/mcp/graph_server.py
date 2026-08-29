"""MCP server over the code graph. Localhost only — no tunnel.

Tools: find_contact_points, select_tests, get_callers, get_call_chain,
read_function_source.
"""

from __future__ import annotations

from src.main.agentradar.adapters.graph import CodeGraph, FalkorCodeGraph
from src.main.agentradar.contracts.evidence import TestSelection
from src.main.agentradar.contracts.impact import (
    ContactPointList,
    FunctionSource,
    GraphNode,
    GraphNodeList,
)
from src.main.agentradar.core.selection import select_tests as _select_tests
from src.main.agentradar.mcp._server import ToolError, serve, tool

_graph: CodeGraph | None = None


def set_graph(graph: CodeGraph) -> None:
    """Inject a graph implementation. Tests pass FakeCodeGraph."""
    global _graph
    _graph = graph


def get_graph() -> CodeGraph:
    """Active graph, defaulting to the FalkorDB adapter."""
    if _graph is None:
        return FalkorCodeGraph()
    return _graph


@tool(
    "find_contact_points",
    "Search function names or source text for a dependency symbol. "
    "Returns contact points with fid, file, and function name.",
    {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Substring to search in names or source (e.g. FastMCP)",
            },
            "repo": {
                "type": "string",
                "description": "Last path segment of the indexed repo",
            },
            "limit": {
                "type": "integer",
                "description": "Max hits. Default 15.",
                "minimum": 1,
                "maximum": 100,
            },
        },
        "required": ["symbol", "repo"],
    },
)
def find_contact_points(symbol: str, repo: str, limit: int = 15) -> ContactPointList:
    """Locate call sites that reference `symbol`."""
    points = get_graph().find_contact_points(symbol, repo, limit)
    return ContactPointList(contact_points=points)


@tool(
    "get_callers",
    "Functions that call this fid. Returns [{name, fid}, ...].",
    {
        "type": "object",
        "properties": {
            "fid": {
                "type": "integer",
                "description": "Function ID from a prior find_contact_points hit",
                "minimum": 1,
            },
            "repo": {
                "type": "string",
                "description": "Last path segment of the indexed repo",
            },
            "limit": {
                "type": "integer",
                "description": "Max callers. Default 25.",
                "minimum": 1,
                "maximum": 100,
            },
        },
        "required": ["fid", "repo"],
    },
)
def get_callers(fid: int, repo: str, limit: int = 25) -> GraphNodeList:
    """Blast-radius step: who calls this contact point."""
    rows = get_graph().callers_of(fid, repo, limit)
    return GraphNodeList(
        nodes=[GraphNode(name=str(row["name"]), fid=int(row["fid"])) for row in rows]
    )


@tool(
    "get_call_chain",
    "Shortest CALLS path from one function to another. Returns [{name, fid}, ...].",
    {
        "type": "object",
        "properties": {
            "from_function": {"type": "string"},
            "to_function": {"type": "string"},
            "repo": {
                "type": "string",
                "description": "Last path segment of the indexed repo",
            },
            "max_hops": {
                "type": "integer",
                "description": "Max depth. Default 4.",
                "minimum": 1,
                "maximum": 6,
            },
        },
        "required": ["from_function", "to_function", "repo"],
    },
)
def get_call_chain(
    from_function: str, to_function: str, repo: str, max_hops: int = 4
) -> GraphNodeList:
    """How deep a site sits in the call graph."""
    rows = get_graph().call_chain(from_function, to_function, repo, max_hops)
    return GraphNodeList(
        nodes=[GraphNode(name=str(row["name"]), fid=int(row["fid"])) for row in rows]
    )


@tool(
    "read_function_source",
    "Read function source by fid. Unambiguous; prefer fid over name.",
    {
        "type": "object",
        "properties": {
            "fid": {
                "type": "integer",
                "description": "Function ID (preferred).",
                "minimum": 1,
            },
            "repo": {
                "type": "string",
                "description": "Last path segment of the indexed repo",
            },
            "max_chars": {
                "type": "integer",
                "description": "Max characters to return. Default 1500.",
                "minimum": 1,
                "maximum": 20000,
            },
        },
        "required": ["fid", "repo"],
    },
)
def read_function_source(fid: int, repo: str, max_chars: int = 1500) -> FunctionSource:
    """Source context for patch-writing."""
    source = get_graph().read_source(fid, repo, max_chars)
    return FunctionSource(source=source)


@tool(
    "select_tests",
    "Find which tests exercise a dependency symbol, so only those need running. "
    "Unions two graph walks: CALLS (callers of a contact point) and IMPORTS "
    "(modules that transitively import a touched file). Returns pytest node ids "
    "plus the strategy that found them. Prefer this over walking get_callers "
    "yourself - a raw caller walk finds nothing for import-level breaks, because "
    "nothing calls an import.",
    {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Dependency symbol to locate (e.g. FastMCP)",
            },
            "repo": {
                "type": "string",
                "description": "Last path segment of the indexed repo",
            },
            "test_root": {
                "type": "string",
                "description": "Directory holding tests. Default 'tests'.",
            },
            "source_root": {
                "type": "string",
                "description": "Directory holding importable packages. Default 'src'.",
            },
            "max_tests": {
                "type": "integer",
                "description": "Cap on selected tests. Default 12.",
                "minimum": 1,
                "maximum": 200,
            },
            "limit": {
                "type": "integer",
                "description": "Max contact points to walk from. Default 15.",
                "minimum": 1,
                "maximum": 100,
            },
        },
        "required": ["symbol", "repo"],
    },
)
def select_tests(
    symbol: str,
    repo: str,
    test_root: str = "tests",
    source_root: str = "src",
    max_tests: int = 12,
    limit: int = 15,
) -> TestSelection:
    """Locate the symbol, then walk the graph to the tests that reach it.

    One call rather than two so the agent cannot skip the walk and guess. An
    empty `tests` list is a real answer meaning nothing covers these sites -
    report UNCOVERED and fall back to an import check, never assume safe.

    A blank `symbol` is rejected rather than answered. The graph search is a
    substring match, so `""` matches every function name and every source
    body: the tool would return a confident-looking selection of arbitrary
    tests instead of saying it was asked nothing. Same for `repo`, which
    scopes the traversal to one indexed checkout.
    """
    if not symbol.strip():
        raise ToolError("invalid_input", "'symbol' must not be blank")
    if not repo.strip():
        raise ToolError("invalid_input", "'repo' must not be blank")
    graph = get_graph()
    points = graph.find_contact_points(symbol, repo, limit)
    return _select_tests(
        graph,
        points,
        repo,
        max_tests=max_tests,
        test_root=test_root,
        source_root=source_root,
    )


def main() -> None:
    """Entry: `python -m src.main.agentradar.mcp.graph_server --port 8768`."""
    import argparse

    parser = argparse.ArgumentParser(description="AgentRadar code-graph MCP server")
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    serve("mcp-graph", args.port)


if __name__ == "__main__":
    main()
