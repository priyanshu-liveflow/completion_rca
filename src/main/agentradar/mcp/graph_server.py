"""MCP server over the code graph. Localhost only — no tunnel.

Tools: find_contact_points, get_callers, get_call_chain, read_function_source.
"""

from __future__ import annotations

from src.main.agentradar.adapters.graph import CodeGraph, FalkorCodeGraph
from src.main.agentradar.contracts.impact import (
    ContactPointList,
    FunctionSource,
    GraphNode,
    GraphNodeList,
)
from src.main.agentradar.mcp._server import serve, tool

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


def main() -> None:
    """Entry: `python -m src.main.agentradar.mcp.graph_server --port 8765`."""
    import argparse

    parser = argparse.ArgumentParser(description="AgentRadar code-graph MCP server")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve("mcp-graph", args.port)


if __name__ == "__main__":
    main()
