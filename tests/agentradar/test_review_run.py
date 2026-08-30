"""Tests for the verify-a-review pipeline. Fake graph, fake runner, no I/O."""

from __future__ import annotations

from dataclasses import dataclass

from src.main.agentradar.contracts.finding import FindingStatus, ReviewFinding
from src.main.agentradar.core.review_run import (
    RunConfig,
    markdown_report,
    tally,
    verify_finding,
    verify_findings,
)

CONFIG = RunConfig(repo_key="repo", test_root="tests", source_root="", max_tests=8)

# Real `pytest -rA` shape. The parser reads the `short test summary info`
# block, so an approximation of it parses to zero cases and every assertion
# below would pass for the wrong reason.
_PASSING = """\
tests/test_a.py .                                                        [100%]

=========================== short test summary info ============================
PASSED tests/test_a.py::test_one
============================== 1 passed in 0.10s ===============================
"""

_FAILING = """\
tests/test_a.py F                                                        [100%]

=================================== FAILURES ===================================
__________________________________ test_one ____________________________________

    def test_one():
>       assert target() == 1
E       AssertionError

src/a.py:11: AssertionError
=========================== short test summary info ============================
FAILED tests/test_a.py::test_one - AssertionError
============================== 1 failed in 0.10s ===============================
"""


class _Graph:
    """Enough of `CodeGraph` for the pipeline: locate, then the imports walk."""

    def __init__(
        self,
        functions: list[dict[str, object]] | None = None,
        importers: list[dict[str, object]] | None = None,
    ) -> None:
        self._functions = functions if functions is not None else []
        self._importers = importers if importers is not None else []

    def functions_in(self, file_path: str, repo: str) -> list[dict[str, object]]:
        if file_path.startswith("tests/"):
            return self._importers
        return self._functions

    def import_edges(self, repo: str) -> list[dict[str, object]]:
        return [
            {"file_path": "tests/test_a.py", "imported": "src.a"},
        ]

    def callers_of(self, fid: int, repo: str, limit: int = 25) -> list[object]:
        return []

    def call_chain(self, *a: object, **k: object) -> list[object]:
        return []

    def read_source(self, *a: object, **k: object) -> str:
        return ""


@dataclass
class _Raw:
    exit_code: int
    stdout: str
    duration_s: float = 0.1


class _Runner:
    """Records what it was asked to run, so selection can be asserted on."""

    def __init__(self, raw: _Raw) -> None:
        self.raw = raw
        self.called_with: list[str] | None = None

    def run_tests(self, node_ids: list[str], *, timeout_s: int = 180) -> _Raw:
        self.called_with = list(node_ids)
        return self.raw


def _finding(path: str = "src/a.py", line: int | None = 20) -> ReviewFinding:
    return ReviewFinding(
        id="1", reviewer="qodo", file_path=path, line=line, title="claim", body="body"
    )


def _fn(name: str, fid: int, start: int, end: int, path: str) -> dict[str, object]:
    return {
        "name": name,
        "fid": fid,
        "file_path": path,
        "start_line": start,
        "end_line": end,
    }


def _located() -> _Graph:
    return _Graph(
        functions=[_fn("target", 1, 10, 30, "src/a.py")],
        importers=[_fn("test_one", 2, 1, 5, "tests/test_a.py")],
    )


def test_unindexed_file_is_unlocatable_without_running_anything() -> None:
    runner = _Runner(_Raw(0, "1 passed"))
    verdict = verify_finding(_Graph(), _finding(), CONFIG, runner)  # type: ignore[arg-type]
    assert verdict.status is FindingStatus.UNLOCATABLE
    assert runner.called_with is None


def test_located_but_untested_site_is_uncovered_without_running() -> None:
    """No selection means nothing to run — the runner must not be invoked."""
    graph = _Graph(functions=[_fn("target", 1, 10, 30, "src/a.py")], importers=[])
    runner = _Runner(_Raw(0, "1 passed"))
    verdict = verify_finding(graph, _finding(), CONFIG, runner)  # type: ignore[arg-type]
    assert verdict.status is FindingStatus.UNCOVERED
    assert runner.called_with is None


def test_no_runner_stops_after_selection_and_says_so() -> None:
    """`--no-run` must not report a covered site as unreproduced."""
    verdict = verify_finding(_located(), _finding(), CONFIG, None)  # type: ignore[arg-type]
    assert verdict.status is FindingStatus.UNCOVERED
    assert "never run" in verdict.why
    assert verdict.selection is not None and verdict.selection.tests


def test_passing_tests_give_unreproduced() -> None:
    runner = _Runner(_Raw(0, _PASSING))
    verdict = verify_finding(_located(), _finding(), CONFIG, runner)  # type: ignore[arg-type]
    assert verdict.status is FindingStatus.UNREPRODUCED
    assert runner.called_with == ["tests/test_a.py::test_one"]


def test_a_correlated_failure_confirms() -> None:
    runner = _Runner(_Raw(1, _FAILING))
    verdict = verify_finding(_located(), _finding(), CONFIG, runner)  # type: ignore[arg-type]
    assert verdict.status is FindingStatus.CONFIRMED


def test_a_crashed_runner_never_confirms() -> None:
    """Exit 4 is a pytest usage error, not evidence about the reviewer's claim."""
    runner = _Runner(_Raw(4, "ERROR: file or directory not found"))
    verdict = verify_finding(_located(), _finding(), CONFIG, runner)  # type: ignore[arg-type]
    assert verdict.status is FindingStatus.INCONCLUSIVE


def test_narrator_receives_each_step() -> None:
    lines: list[str] = []
    runner = _Runner(_Raw(0, _PASSING))
    verify_finding(_located(), _finding(), CONFIG, runner, lines.append)  # type: ignore[arg-type]
    joined = "\n".join(lines)
    assert "graph:" in joined
    assert "select:" in joined
    assert "run:" in joined


def test_narrator_is_optional_and_silent_by_default() -> None:
    verify_finding(_located(), _finding(), CONFIG, None)  # type: ignore[arg-type]


def test_verify_findings_preserves_reviewer_order() -> None:
    findings = [_finding(path="src/a.py"), _finding(path="src/zzz.py")]
    verdicts = verify_findings(_located(), findings, CONFIG, None)  # type: ignore[arg-type]
    assert [v.finding.file_path for v in verdicts] == ["src/a.py", "src/zzz.py"]


def test_tally_reports_every_status_even_at_zero() -> None:
    verdicts = verify_findings(_located(), [_finding()], CONFIG, None)  # type: ignore[arg-type]
    counts = tally(verdicts)
    assert set(counts) == set(FindingStatus)
    assert counts[FindingStatus.CONFIRMED] == 0
    assert counts[FindingStatus.UNCOVERED] == 1


def test_markdown_leads_with_the_confirmed_count() -> None:
    verdicts = verify_findings(_located(), [_finding()], CONFIG, None)  # type: ignore[arg-type]
    body = markdown_report(verdicts, CONFIG)
    assert body.startswith("## AgentRadar verified this review")
    assert "**0 confirmed**" in body
    assert "| verdict | finding | evidence |" in body


def test_markdown_escapes_pipes_so_the_table_survives() -> None:
    finding = ReviewFinding(
        id="1",
        reviewer="qodo",
        file_path="src/a.py",
        line=20,
        title="a | b",
        body="x",
    )
    verdicts = verify_findings(_located(), [finding], CONFIG, None)  # type: ignore[arg-type]
    row = [ln for ln in markdown_report(verdicts, CONFIG).splitlines() if "a " in ln]
    assert any("a \\| b" in ln for ln in row)
