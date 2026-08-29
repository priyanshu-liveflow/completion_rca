"""Graph-guided test selection. Pure, offline, FakeCodeGraph only.

The acceptance here is exact, not a superset: for `FastMCP` on the demo repo,
two of the five test modules are selected and the other three are not. Running
tests that were never at risk would make the impact table meaningless.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from src.main.agentradar.contracts.impact import ContactPoint
from src.main.agentradar.core.selection import (
    CodeGraph,
    is_test_node,
    module_matches,
    module_name_for,
    select_tests,
    select_tests_by_callers,
    select_tests_by_imports,
    select_tests_by_path,
    to_node_ids,
)
from tests.agentradar.fakes import (
    FakeCodeGraph,
    demo_fastmcp_graph,
    demo_selection_graph,
)

ROOT = Path(__file__).resolve().parents[2]
DEMO: dict[str, Any] = yaml.safe_load(
    (ROOT / "configs" / "demo.yaml").read_text(encoding="utf-8")
)["demo"]
REPO = str(DEMO["repo_key"])


def _point(fid: int, file_path: str, name: str = "<module>") -> ContactPoint:
    return ContactPoint(
        symbol="FastMCP", function_name=name, fid=fid, file_path=file_path, line=None
    )


def _files(selection_tests: list[str]) -> set[str]:
    """The module-level projection `configs/demo.yaml` states the acceptance in."""
    return {node_id.split("::")[0] for node_id in selection_tests}


# --- module_name_for ------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "root", "expected"),
    [
        ("src/pkg/api/client.py", "src", "pkg.api.client"),
        ("src/pkg/tools/__init__.py", "src", "pkg.tools"),
        ("src/pkg/__init__.py", "src", "pkg"),
        ("src/__init__.py", "src", ""),
        ("./src/pkg/x.py", "src", "pkg.x"),
        ("src\\pkg\\x.py", "src", "pkg.x"),
        ("src/main/pkg/x.py", "src/main", "pkg.x"),
        # A source root that does not prefix the path is left alone; test files
        # live outside it and still need a name for the walk.
        ("tests/test_server.py", "src", "tests.test_server"),
        ("pkg/x.py", "", "pkg.x"),
    ],
)
def test_module_name_for(path: str, root: str, expected: str) -> None:
    assert module_name_for(path, root) == expected


# --- module_matches -------------------------------------------------------


def test_prefix_matching_respects_dot_boundaries() -> None:
    assert module_matches("pkg.api", "pkg.api.client") is True
    assert module_matches("pkg.apiclient", "pkg.api.client") is False
    # The case the plain-`startswith` bug actually gets wrong. The pair above
    # is False under both implementations, so on its own it proves nothing.
    assert module_matches("pkg.api", "pkg.apiclient") is False


@pytest.mark.parametrize(
    ("imported", "target", "expected"),
    [
        ("pkg.api", "pkg.api", True),
        ("pkg", "pkg.api.client", True),
        # `startswith(imported)` with no boundary would call these True.
        ("pkg.api", "pkg.apiclient", False),
        ("pkg", "pkgtools.thing", False),
        # One-directional: importing a submodule of the target is not the
        # target being imported.
        ("pkg.api.client", "pkg.api", False),
        ("other.api", "pkg.api", False),
        ("", "pkg.api", False),
        ("pkg.api", "", False),
    ],
)
def test_module_matches(imported: str, target: str, expected: bool) -> None:
    assert module_matches(imported, target) is expected


# --- is_test_node / to_node_ids -------------------------------------------


@pytest.mark.parametrize(
    ("name", "path", "expected"),
    [
        ("test_server_starts", "tests/test_server.py", True),
        ("test_nested", "pkg/tests/test_a.py", True),
        # The graph indexes one <module> node per file. It is not runnable.
        ("<module>", "tests/test_server.py", False),
        ("helper", "tests/test_server.py", False),
        ("test_looks_like_one", "src/pkg/thing.py", False),
        ("test_no_path", "", False),
    ],
)
def test_is_test_node(name: str, path: str, expected: bool) -> None:
    assert is_test_node(name, path, "tests") is expected


def test_to_node_ids_drops_rows_pytest_could_not_run() -> None:
    rows: list[dict[str, Any]] = [
        {"name": "test_a", "file_path": "tests/test_a.py", "fid": 1},
        {"name": "test_b", "fid": 2},
        {"file_path": "tests/test_c.py", "fid": 3},
    ]
    assert to_node_ids(rows) == ["tests/test_a.py::test_a"]


# --- the callers walk -----------------------------------------------------


def _chain_graph() -> FakeCodeGraph:
    """contact point 1 <- 2 <- 3 <- a test at 4. Three hops up."""
    return FakeCodeGraph(
        callers={
            1: [{"name": "setup_api_client", "fid": 2, "file_path": "src/a.py"}],
            2: [{"name": "start_server", "fid": 3, "file_path": "src/b.py"}],
            3: [{"name": "test_boot", "fid": 4, "file_path": "tests/test_boot.py"}],
        }
    )


def test_callers_reaches_a_test_three_hops_up() -> None:
    selection = select_tests_by_callers(_chain_graph(), [_point(1, "src/x.py")], REPO)
    assert selection.tests == ["tests/test_boot.py::test_boot"]
    assert selection.strategy == "callers"


def test_callers_stops_at_max_depth() -> None:
    selection = select_tests_by_callers(
        _chain_graph(), [_point(1, "src/x.py")], REPO, max_depth=2
    )
    assert selection.tests == []


def test_callers_terminates_on_a_cycle() -> None:
    cyclic = FakeCodeGraph(
        callers={
            1: [{"name": "a", "fid": 2, "file_path": "src/a.py"}],
            2: [{"name": "b", "fid": 1, "file_path": "src/b.py"}],
        }
    )
    selection = select_tests_by_callers(
        cyclic, [_point(1, "src/x.py")], REPO, max_depth=99
    )
    assert selection.tests == []


def test_callers_without_a_path_are_not_claimed_as_tests() -> None:
    """`queries.get_callers` returns no path today. Guessing would be worse."""
    pathless = FakeCodeGraph(callers={1: [{"name": "test_boot", "fid": 2}]})
    assert select_tests_by_callers(pathless, [_point(1, "src/x.py")], REPO).tests == []


def test_callers_records_the_contact_point_it_started_from() -> None:
    selection = select_tests_by_callers(
        _chain_graph(), [_point(1, "src/x.py", name="mcp")], REPO
    )
    assert selection.reached_from == ["mcp"]


# --- the imports walk -----------------------------------------------------


def _demo_points() -> list[ContactPoint]:
    return list(demo_fastmcp_graph().points)


def test_imports_reaches_exactly_the_two_broken_modules() -> None:
    selection = select_tests_by_imports(demo_selection_graph(), _demo_points(), REPO)
    assert _files(selection.tests) == {
        "tests/test_server.py",
        "tests/test_make_intervals_request.py",
    }


def _boundary_graph() -> FakeCodeGraph:
    return FakeCodeGraph(
        imports=[
            {"file_path": "tests/test_api.py", "imported": "pkg.api"},
            {"file_path": "tests/test_apiclient.py", "imported": "pkg.apiclient"},
        ],
        functions={
            "tests/test_api.py": [
                {"name": "test_api", "fid": 1, "file_path": "tests/test_api.py"}
            ],
            "tests/test_apiclient.py": [
                {
                    "name": "test_apiclient",
                    "fid": 2,
                    "file_path": "tests/test_apiclient.py",
                }
            ],
        },
    )


def test_imports_reaches_through_a_package_boundary() -> None:
    """`pkg.api` reaches `pkg.api.client` — this is half the demo selection."""
    selection = select_tests_by_imports(
        _boundary_graph(), [_point(9, "src/pkg/api/client.py")], REPO
    )
    assert selection.tests == ["tests/test_api.py::test_api"]


def test_imports_does_not_reach_across_a_string_prefix() -> None:
    """`pkg.api` must not reach `pkg.apiclient`. Only a boundary check sees it."""
    selection = select_tests_by_imports(
        _boundary_graph(), [_point(9, "src/pkg/apiclient.py")], REPO
    )
    assert selection.tests == ["tests/test_apiclient.py::test_apiclient"]


def test_imports_walk_is_transitive() -> None:
    """A test importing a module that imports the contact point is reached."""
    graph = FakeCodeGraph(
        imports=[
            {"file_path": "src/pkg/middle.py", "imported": "pkg.api.client"},
            {"file_path": "tests/test_middle.py", "imported": "pkg.middle"},
        ],
        functions={
            "tests/test_middle.py": [
                {"name": "test_middle", "fid": 7, "file_path": "tests/test_middle.py"}
            ]
        },
    )
    selection = select_tests_by_imports(
        graph, [_point(9, "src/pkg/api/client.py")], REPO
    )
    assert selection.tests == ["tests/test_middle.py::test_middle"]
    assert (
        select_tests_by_imports(
            graph, [_point(9, "src/pkg/api/client.py")], REPO, max_depth=1
        ).tests
        == []
    )


class CountingGraph(FakeCodeGraph):
    """Records which files the walk asked the graph about."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.queried: list[str] = []

    def functions_in(self, file_path: str, repo: str) -> list[dict[str, Any]]:
        self.queried.append(file_path)
        return super().functions_in(file_path, repo)


def test_imports_walk_does_not_query_source_files_for_tests() -> None:
    """Reached source files are not test files; asking about them is N wasted
    round trips against a live FalkorDB."""
    base = demo_selection_graph()
    graph = CountingGraph(imports=base.imports, functions=base.functions)
    select_tests_by_imports(graph, _demo_points(), REPO)
    assert graph.queried == [
        "tests/test_make_intervals_request.py",
        "tests/test_server.py",
    ]


def test_imports_skips_module_nodes() -> None:
    selection = select_tests_by_imports(demo_selection_graph(), _demo_points(), REPO)
    assert all("<module>" not in node_id for node_id in selection.tests)


# --- select_tests ---------------------------------------------------------


def test_selection_is_exact_not_a_superset() -> None:
    """The acceptance from configs/demo.yaml, read from the file itself."""
    selection = select_tests(demo_selection_graph(), _demo_points(), REPO)
    assert _files(selection.tests) == set(DEMO["expected_test_selection"])
    assert _files(selection.tests).isdisjoint(DEMO["not_selected"])
    assert selection.strategy == DEMO["expected_selection_strategy"]
    assert selection.truncated is False


def test_callers_reaches_zero_for_this_break() -> None:
    """Measured, not assumed: nothing calls an import."""
    selection = select_tests_by_callers(demo_selection_graph(), _demo_points(), REPO)
    assert selection.tests == []


def test_selection_records_the_contact_points_it_came_from() -> None:
    """Function names, per the contract — the same namespace CALLS uses."""
    points = _demo_points()
    selection = select_tests(demo_selection_graph(), points, REPO)
    assert set(selection.reached_from) <= {p.function_name for p in points}
    # Both matching contact points are kept, not just the first to arrive.
    assert selection.reached_from == ["client", "tools_init"]


def test_every_contact_point_sharing_a_module_is_recorded() -> None:
    """Real graphs put several contact points in one file; all of them reached
    the tests, so reporting one would under-report provenance."""
    graph = FakeCodeGraph(
        imports=[{"file_path": "tests/test_a.py", "imported": "pkg.thing"}],
        functions={
            "tests/test_a.py": [
                {"name": "test_a", "fid": 1, "file_path": "tests/test_a.py"}
            ]
        },
    )
    points = [
        _point(10, "src/pkg/thing.py", name="<module>"),
        _point(11, "src/pkg/thing.py", name="start_server"),
    ]
    assert select_tests_by_imports(graph, points, REPO).reached_from == [
        "<module>",
        "start_server",
    ]


def test_empty_contact_points_return_an_empty_selection() -> None:
    selection = select_tests(demo_selection_graph(), [], REPO)
    assert selection.tests == []
    assert selection.truncated is False
    # The graph chose nothing, so it does not claim a walk succeeded.
    assert selection.strategy == "manual"


def test_max_tests_clips_and_says_so() -> None:
    selection = select_tests(demo_selection_graph(), _demo_points(), REPO, max_tests=2)
    assert len(selection.tests) == 2
    assert selection.truncated is True


def test_union_dedupes_and_reports_the_walk_that_contributed_most() -> None:
    graph = demo_selection_graph()
    # The same two tests are now also reachable up CALLS, plus one more.
    graph.callers = {
        1: [
            {
                "name": "test_server_starts",
                "fid": 101,
                "file_path": "tests/test_server.py",
            },
            {
                "name": "test_tools_registered",
                "fid": 102,
                "file_path": "tests/test_server.py",
            },
            {"name": "test_extra", "fid": 103, "file_path": "tests/test_extra.py"},
        ]
    }
    selection = select_tests(graph, _demo_points(), REPO)
    assert len(selection.tests) == len(set(selection.tests))
    assert "tests/test_extra.py::test_extra" in selection.tests
    assert selection.strategy == "callers"


def test_rows_are_ordered_by_fid_not_by_arrival() -> None:
    """Reproducible on stage means one order, and the graph does not pick it."""
    graph = FakeCodeGraph(
        imports=[{"file_path": "tests/test_a.py", "imported": "pkg.thing"}],
        functions={
            "tests/test_a.py": [
                {"name": "test_z", "fid": 9, "file_path": "tests/test_a.py"},
                {"name": "test_a", "fid": 2, "file_path": "tests/test_a.py"},
                {"name": "test_m", "fid": 5, "file_path": "tests/test_a.py"},
            ]
        },
    )
    selection = select_tests(graph, [_point(1, "src/pkg/thing.py")], REPO)
    assert selection.tests == [
        "tests/test_a.py::test_a",
        "tests/test_a.py::test_m",
        "tests/test_a.py::test_z",
    ]


def test_ordering_is_stable_across_runs() -> None:
    points = _demo_points()
    first = select_tests(demo_selection_graph(), points, REPO)
    second = select_tests(demo_selection_graph(), list(reversed(points)), REPO)
    assert first.tests == second.tests


def test_fake_satisfies_the_protocol() -> None:
    assert isinstance(demo_selection_graph(), CodeGraph)


# --- select_tests_by_path -------------------------------------------------


def test_class_based_tests_get_a_runnable_node_id() -> None:
    """The graph stores method names bare and hangs the class off a separate
    edge, so `path::test_method` would not resolve in the sandbox."""
    graph = FakeCodeGraph(
        imports=[{"file_path": "tests/test_a.py", "imported": "pkg.thing"}],
        functions={
            "tests/test_a.py": [
                {
                    "name": "test_method",
                    "fid": 1,
                    "file_path": "tests/test_a.py",
                    "class_name": "TestThing",
                },
                {"name": "test_plain", "fid": 2, "file_path": "tests/test_a.py"},
            ]
        },
    )
    selection = select_tests(graph, [_point(9, "src/pkg/thing.py")], REPO)
    assert selection.tests == [
        "tests/test_a.py::TestThing::test_method",
        "tests/test_a.py::test_plain",
    ]


def test_to_node_ids_qualifies_only_class_owned_rows() -> None:
    rows: list[dict[str, Any]] = [
        {"name": "test_a", "file_path": "tests/t.py", "class_name": None},
        {"name": "test_b", "file_path": "tests/t.py", "class_name": "TestB"},
        {"name": "test_c", "file_path": "tests/t.py", "class_name": ""},
    ]
    assert to_node_ids(rows) == [
        "tests/t.py::test_a",
        "tests/t.py::TestB::test_b",
        "tests/t.py::test_c",
    ]


@pytest.mark.parametrize("limit", [-1, -5])
def test_a_negative_limit_selects_nothing(limit: int) -> None:
    """`rows[:-1]` would return almost everything and call it truncated."""
    selection = select_tests(
        demo_selection_graph(), _demo_points(), REPO, max_tests=limit
    )
    assert selection.tests == []
    assert selection.truncated is True


def test_zero_limit_selects_nothing() -> None:
    selection = select_tests(demo_selection_graph(), _demo_points(), REPO, max_tests=0)
    assert selection.tests == []
    assert selection.truncated is True


def test_path_strategy_matches_the_test_file_mirror() -> None:
    selection = select_tests_by_path(
        [_point(1, "src/pkg/server.py")],
        ["tests/test_server.py", "tests/test_other.py", "src/pkg/server.py"],
        "tests",
    )
    assert selection.tests == ["tests/test_server.py"]
    assert selection.strategy == "path"


def test_path_strategy_matches_a_shared_package() -> None:
    selection = select_tests_by_path(
        [_point(1, "src/pkg/api/client.py")],
        ["tests/api/test_thing.py", "tests/other/test_thing.py"],
        "tests",
    )
    assert selection.tests == ["tests/api/test_thing.py"]


def test_path_strategy_finds_nothing_for_a_flat_unmirrored_suite() -> None:
    """It is the last resort, and it says so by returning nothing."""
    selection = select_tests_by_path(
        _demo_points(),
        ["tests/test_server.py", "tests/test_value.py"],
        "tests",
    )
    assert selection.tests == []
