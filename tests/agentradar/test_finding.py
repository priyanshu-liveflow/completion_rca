"""Tests for judging a reviewer's finding. Pure — a fake graph, no FalkorDB."""

from __future__ import annotations

from src.main.agentradar.contracts.evidence import TestCase, TestReport, TestSelection
from src.main.agentradar.contracts.finding import FindingStatus, ReviewFinding
from src.main.agentradar.contracts.impact import ContactPoint
from src.main.agentradar.core.finding import judge_finding, locate_finding


class _FakeGraph:
    """Only `functions_in` is exercised; the rest of the Protocol is unused here."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def functions_in(self, file_path: str, repo: str) -> list[dict[str, object]]:
        return self.rows

    def __getattr__(self, name: str) -> object:  # pragma: no cover - unused
        raise AttributeError(name)


def _finding(path: str = "src/a.py", line: int | None = 20) -> ReviewFinding:
    return ReviewFinding(
        id="1", reviewer="qodo", file_path=path, line=line, title="claim", body="body"
    )


def _point(name: str = "target", fid: int = 1) -> ContactPoint:
    return ContactPoint(
        symbol="claim", function_name=name, fid=fid, file_path="src/a.py", line=10
    )


def _selection(*tests: str) -> TestSelection:
    return TestSelection(
        tests=list(tests) or ["tests/test_a.py::test_one"],
        strategy="imports",
        reached_from=["target"],
    )


def _report(
    *,
    passed: int = 0,
    failed: int = 0,
    errors: int = 0,
    cases: list[TestCase] | None = None,
    exit_code: int | None = 0,
) -> TestReport:
    return TestReport(
        id="r1",
        package="pkg",
        version="HEAD",
        cases=cases or [],
        passed=passed,
        failed=failed,
        errors=errors,
        duration_s=0.1,
        raw_tail="",
        exit_code=exit_code,
    )


def _case(
    node_id: str, outcome: str = "failed", traceback: str | None = None
) -> TestCase:
    return TestCase(
        node_id=node_id, outcome=outcome, duration_s=0.0, traceback=traceback
    )


def _fn(
    name: str, fid: int, start: int | None, end: int | None, path: str = "src/a.py"
) -> dict[str, object]:
    return {
        "name": name,
        "fid": fid,
        "file_path": path,
        "start_line": start,
        "end_line": end,
    }


# --- locate ---------------------------------------------------------------


def test_line_resolves_to_the_enclosing_function() -> None:
    graph = _FakeGraph([_fn("outer", 1, 1, 100), _fn("inner", 2, 15, 30)])
    points = locate_finding(graph, _finding(line=20), "repo")  # type: ignore[arg-type]
    assert [p.function_name for p in points] == ["inner"]


def test_synthetic_module_node_never_wins_over_a_real_function() -> None:
    """`<module>` starts at line 1 with no end and would otherwise swallow the file."""
    graph = _FakeGraph([_fn("<module>", 1, 1, None), _fn("real", 2, 15, 30)])
    points = locate_finding(graph, _finding(line=20), "repo")  # type: ignore[arg-type]
    assert [p.function_name for p in points] == ["real"]


def test_a_line_in_no_function_falls_back_to_the_whole_file() -> None:
    graph = _FakeGraph([_fn("f", 1, 50, 60)])
    points = locate_finding(graph, _finding(line=5), "repo")  # type: ignore[arg-type]
    assert [p.function_name for p in points] == ["f"]


def test_a_similar_path_is_not_the_same_file() -> None:
    """`CONTAINS` matching returns `patch_helpers.py` when asked for `patch.py`."""
    graph = _FakeGraph([_fn("f", 1, 1, 9, path="src/a_helpers.py")])
    found = locate_finding(graph, _finding(path="src/a.py"), "repo")  # type: ignore[arg-type]
    assert found == []


def test_unindexed_file_locates_nothing() -> None:
    assert locate_finding(_FakeGraph([]), _finding(), "repo") == []  # type: ignore[arg-type]


# --- judge ----------------------------------------------------------------


def test_unlocatable_when_nothing_was_found() -> None:
    v = judge_finding(_finding(), [], None, None)
    assert v.status is FindingStatus.UNLOCATABLE


def test_uncovered_when_no_test_reaches_the_site() -> None:
    v = judge_finding(_finding(), [_point()], _selection(), None)
    assert v.status is FindingStatus.UNCOVERED
    # an empty selection, not a missing one
    v2 = judge_finding(
        _finding(),
        [_point()],
        TestSelection(tests=[], strategy="manual", reached_from=[]),
        None,
    )
    assert v2.status is FindingStatus.UNCOVERED


def test_uncovered_when_selected_tests_were_never_run() -> None:
    v = judge_finding(_finding(), [_point()], _selection(), None)
    assert v.status is FindingStatus.UNCOVERED


def test_confirmed_when_a_failing_test_touches_the_site() -> None:
    report = _report(
        failed=1,
        exit_code=1,
        cases=[
            _case("tests/test_a.py::test_target", traceback="src/a.py:11 in target")
        ],
    )
    v = judge_finding(_finding(), [_point()], _selection(), report)
    assert v.status is FindingStatus.CONFIRMED


def test_unrelated_failure_does_not_confirm() -> None:
    """The imports walk selects widely; a failure elsewhere proves nothing here."""
    report = _report(
        failed=1,
        exit_code=1,
        cases=[_case("tests/test_z.py::test_other", traceback="src/z.py:3 in other")],
    )
    v = judge_finding(_finding(), [_point()], _selection(), report)
    assert v.status is FindingStatus.INCONCLUSIVE
    assert "not evidence" in v.why


def test_runner_crash_does_not_confirm() -> None:
    """pytest exit 4 is a usage error — infrastructure, not a verdict."""
    report = _report(errors=1, exit_code=4)
    v = judge_finding(_finding(), [_point()], _selection(), report)
    assert v.status is FindingStatus.INCONCLUSIVE
    assert "could not do its job" in v.why


def test_timeout_does_not_confirm() -> None:
    report = _report(errors=1, exit_code=124)
    v = judge_finding(_finding(), [_point()], _selection(), report)
    assert v.status is FindingStatus.INCONCLUSIVE


def test_all_skipped_is_not_unreproduced() -> None:
    """No failures, but nothing ran — that is not a clean bill of health."""
    report = _report(passed=0, failed=0, errors=0, exit_code=0)
    v = judge_finding(_finding(), [_point()], _selection(), report)
    assert v.status is FindingStatus.INCONCLUSIVE
    assert "none executed" in v.why


def test_unreproduced_when_the_tests_pass() -> None:
    report = _report(passed=3, exit_code=0)
    v = judge_finding(_finding(), [_point()], _selection(), report)
    assert v.status is FindingStatus.UNREPRODUCED


def test_verdict_carries_its_evidence() -> None:
    report = _report(passed=3, exit_code=0)
    selection = _selection("tests/test_a.py::test_one")
    v = judge_finding(_finding(), [_point()], selection, report)
    assert v.report is report
    assert v.selection is selection
    assert v.contact_points[0].function_name == "target"
