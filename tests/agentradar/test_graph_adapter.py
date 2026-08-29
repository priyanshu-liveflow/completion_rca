"""Graph adapter and MCP graph-server dispatch, offline via FakeCodeGraph."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.main.agentradar.adapters.graph import FalkorCodeGraph, _path_from_read
from src.main.agentradar.contracts.impact import ContactPoint
from src.main.agentradar.mcp import graph_server
from src.main.agentradar.mcp._server import (
    dispatch,
    format_tool_result,
    is_error_envelope,
)
from src.main.code_tools import queries
from tests.agentradar.fakes import demo_fastmcp_graph

_SOCK = Path.home() / ".codegraphcontext" / "global" / "db" / "falkordb.sock"


@pytest.fixture(autouse=True)
def _inject_fake() -> Iterator[None]:
    graph_server.set_graph(demo_fastmcp_graph())
    yield
    graph_server.set_graph(demo_fastmcp_graph())


def test_fake_find_contact_points_matches_demo_files() -> None:
    graph = demo_fastmcp_graph()
    points = graph.find_contact_points("FastMCP", "intervals-mcp-server")
    paths = {p.file_path for p in points}
    assert "src/intervals_mcp_server/mcp_instance.py" in paths
    assert "src/intervals_mcp_server/api/client.py" in paths
    assert len(points) == 4


def test_dispatch_find_contact_points() -> None:
    result = dispatch(
        "find_contact_points",
        {"symbol": "FastMCP", "repo": "intervals-mcp-server"},
    )
    assert "contact_points" in result
    assert result["contact_points"][0]["symbol"] == "FastMCP"
    assert result["contact_points"][0]["fid"] == 1
    assert not is_error_envelope(result)


def test_dispatch_rejects_missing_required() -> None:
    result = dispatch("find_contact_points", {"symbol": "FastMCP"})
    assert result["error"]["type"] == "invalid_input"
    assert "repo" in result["error"]["message"]
    assert format_tool_result(result).isError is True


def test_dispatch_rejects_unknown_tool() -> None:
    result = dispatch("not_a_tool", {})
    assert result["error"]["type"] == "unknown_tool"
    assert format_tool_result(result).isError is True


def test_dispatch_rejects_bool_fid() -> None:
    result = dispatch("get_callers", {"fid": True, "repo": "intervals-mcp-server"})
    assert result["error"]["type"] == "invalid_input"
    assert "integer" in result["error"]["message"]


def test_dispatch_rejects_negative_max_chars() -> None:
    result = dispatch(
        "read_function_source",
        {"fid": 1, "repo": "intervals-mcp-server", "max_chars": -1},
    )
    assert result["error"]["type"] == "invalid_input"
    assert "max_chars" in result["error"]["message"]


def test_dispatch_get_callers() -> None:
    result = dispatch("get_callers", {"fid": 1, "repo": "intervals-mcp-server"})
    assert result == {"nodes": [{"name": "make_app", "fid": 10}]}


def test_dispatch_call_chain() -> None:
    result = dispatch(
        "get_call_chain",
        {
            "from_function": "make_app",
            "to_function": "mcp",
            "repo": "intervals-mcp-server",
        },
    )
    assert result["nodes"][0]["name"] == "make_app"
    assert result["nodes"][-1]["name"] == "mcp"


def test_dispatch_read_function_source() -> None:
    result = dispatch(
        "read_function_source", {"fid": 1, "repo": "intervals-mcp-server"}
    )
    assert "FastMCP" in result["source"]


def test_path_from_read_header() -> None:
    blob = "File: src/foo.py | fid=9 | Total: 12 chars\n\ndef foo():\n    pass\n"
    assert _path_from_read(blob) == "src/foo.py"


def test_find_by_pattern_unions_name_and_source_hits() -> None:
    graph = MagicMock()
    name_result = MagicMock(result_set=[("name_hit", 1)])
    source_result = MagicMock(result_set=[("source_hit", 2)])
    graph.query.side_effect = [name_result, source_result]

    with patch("src.main.code_tools.queries.get_graph", return_value=graph):
        rows = queries.find_by_pattern("FastMCP", "intervals-mcp-server", limit=5)

    assert rows == [{"name": "name_hit", "fid": 1}, {"name": "source_hit", "fid": 2}]
    assert graph.query.call_count == 2


def test_falkor_maps_pattern_rows_without_cypher() -> None:
    rows = [{"name": "mcp", "fid": 42}]
    source = (
        "File: src/intervals_mcp_server/mcp_instance.py | fid=42 | Total: 1 chars\n\n"
    )
    with (
        patch(
            "src.main.agentradar.adapters.graph.queries.find_by_pattern",
            return_value=rows,
        ),
        patch(
            "src.main.agentradar.adapters.graph.queries.read_source",
            return_value=source,
        ),
    ):
        points = FalkorCodeGraph().find_contact_points(
            "FastMCP", "intervals-mcp-server"
        )
    assert points == [
        ContactPoint(
            symbol="FastMCP",
            function_name="mcp",
            fid=42,
            file_path="src/intervals_mcp_server/mcp_instance.py",
            line=None,
        )
    ]


@pytest.mark.skipif(not _SOCK.exists(), reason="FalkorDB socket not present")
def test_live_fastmcp_contact_points() -> None:
    graph_server.set_graph(FalkorCodeGraph())
    points = FalkorCodeGraph().find_contact_points(
        "FastMCP", "intervals-mcp-server", limit=15
    )
    joined = " ".join(p.file_path for p in points)
    assert "mcp_instance.py" in joined
    assert "client.py" in joined
