"""Tests for proven repair. The gate is the point: no red-to-green, no PR."""

from __future__ import annotations

from dataclasses import dataclass

from src.main.agentradar.contracts.evidence import (
    TestCase,
    TestReport,
    TestSelection,
)
from src.main.agentradar.contracts.finding import (
    FindingStatus,
    FindingVerdict,
    ReviewFinding,
)
from src.main.agentradar.contracts.impact import ContactPoint
from src.main.agentradar.core.remediation import (
    RemediationRequest,
    allowed_files_for,
    build_request,
    judge_remediation,
    may_attempt,
    validate_written_patch,
)
from src.main.agentradar.core.review_run import RunConfig, remediate

CONFIG = RunConfig(repo_key="repo", source_root="")

GOOD_DIFF = """\
diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1,3 +1,3 @@
-    return None
+    return 1
"""

TEST_EDIT_DIFF = """\
diff --git a/tests/test_a.py b/tests/test_a.py
--- a/tests/test_a.py
+++ b/tests/test_a.py
@@ -1,3 +1,3 @@
-    assert target() == 1
+    assert True
"""

OUTSIDE_DIFF = """\
diff --git a/src/elsewhere.py b/src/elsewhere.py
--- a/src/elsewhere.py
+++ b/src/elsewhere.py
@@ -1,3 +1,3 @@
-    x = 1
+    x = 2
"""

RED = """\
=========================== short test summary info ============================
FAILED tests/test_a.py::test_one - AssertionError
============================== 1 failed in 0.10s ===============================
"""

GREEN = """\
=========================== short test summary info ============================
PASSED tests/test_a.py::test_one
============================== 1 passed in 0.10s ===============================
"""


def _point() -> ContactPoint:
    return ContactPoint(
        symbol="claim", function_name="target", fid=7, file_path="src/a.py", line=10
    )


def _verdict(
    status: FindingStatus = FindingStatus.CONFIRMED,
    report: TestReport | None = None,
) -> FindingVerdict:
    if report is None and status is FindingStatus.CONFIRMED:
        report = TestReport(
            id="before",
            package="repo",
            version="HEAD",
            cases=[
                TestCase(
                    node_id="tests/test_a.py::test_one",
                    outcome="failed",
                    duration_s=0.0,
                    traceback="src/a.py:11",
                )
            ],
            passed=0,
            failed=1,
            errors=0,
            duration_s=0.1,
            raw_tail=RED,
            exit_code=1,
        )
    return FindingVerdict(
        finding=ReviewFinding(
            id="1",
            reviewer="qodo",
            file_path="src/a.py",
            line=11,
            title="target returns None",
            body="detail",
        ),
        contact_points=[_point()],
        selection=TestSelection(
            tests=["tests/test_a.py::test_one"],
            strategy="imports",
            reached_from=["target"],
        ),
        report=report,
        status=status,
        why="because",
    )


@dataclass
class _Raw:
    exit_code: int
    stdout: str = ""
    duration_s: float = 0.1


class _Graph:
    def read_source(self, fid: int, repo: str, max_chars: int = 1500) -> str:
        return "def target():\n    return None\n"

    def callers_of(self, *a: object, **k: object) -> list[object]:
        return []

    def import_edges(self, repo: str) -> list[object]:
        return []

    def functions_in(self, *a: object, **k: object) -> list[object]:
        return []


class _Runner:
    """Applies a patch, then returns the next queued run result."""

    def __init__(self, apply_code: int = 0, after: str = GREEN) -> None:
        self.apply_code = apply_code
        self.after = after
        self.applied: str | None = None
        self.ran: list[str] | None = None

    def apply_patch(self, diff: str) -> _Raw:
        self.applied = diff
        return _Raw(self.apply_code)

    def run_tests(self, node_ids: list[str], *, timeout_s: int = 180) -> _Raw:
        self.ran = list(node_ids)
        return _Raw(0 if "passed" in self.after else 1, self.after)


class _Writer:
    def __init__(self, diff: str | None) -> None:
        self.diff = diff
        self.seen: RemediationRequest | None = None

    def write_patch(self, request: RemediationRequest) -> str | None:
        self.seen = request
        return self.diff


# --- what may be attempted -------------------------------------------------


def test_only_a_confirmed_finding_earns_a_patch() -> None:
    for status in (
        FindingStatus.UNCOVERED,
        FindingStatus.UNREPRODUCED,
        FindingStatus.UNLOCATABLE,
        FindingStatus.INCONCLUSIVE,
    ):
        ok, why = may_attempt(_verdict(status, report=None))
        assert not ok, status
        assert "not confirmed" in why


def test_a_confirmed_finding_may_be_attempted() -> None:
    ok, _ = may_attempt(_verdict())
    assert ok


# --- the blast radius ------------------------------------------------------


def test_allowed_files_come_from_the_graph_not_the_diff() -> None:
    assert allowed_files_for(_verdict()) == ["src/a.py"]


def test_a_patch_editing_a_test_is_rejected() -> None:
    """Fixing a failing test by editing the test defeats the whole product."""
    _, ok, reason = validate_written_patch(TEST_EDIT_DIFF, _verdict())
    assert not ok
    assert "test" in reason


def test_a_patch_outside_the_blast_radius_is_rejected() -> None:
    _, ok, reason = validate_written_patch(OUTSIDE_DIFF, _verdict())
    assert not ok
    assert "outside the blast radius" in reason


def test_an_empty_patch_is_rejected() -> None:
    _, ok, reason = validate_written_patch("   ", _verdict())
    assert not ok
    assert "produced nothing" in reason


def test_a_patch_inside_the_blast_radius_is_accepted() -> None:
    patch, ok, _ = validate_written_patch(GOOD_DIFF, _verdict())
    assert ok
    assert patch is not None and patch.files == ["src/a.py"]


# --- the request the writer sees -------------------------------------------


def test_the_request_carries_the_failing_tests_and_no_secrets() -> None:
    request = build_request(_verdict(), "def target(): ...")
    assert request.failing_tests == ["tests/test_a.py::test_one"]
    assert request.allowed_files == ["src/a.py"]
    assert request.function_name == "target"
    assert not hasattr(request, "env")


# --- the gate --------------------------------------------------------------


def test_red_to_green_opens_the_gate() -> None:
    runner = _Runner(after=GREEN)
    outcome = remediate(_verdict(), _Graph(), runner, _Writer(GOOD_DIFF), CONFIG)  # type: ignore[arg-type]
    assert outcome.applied
    assert outcome.may_open_pr
    assert runner.ran == ["tests/test_a.py::test_one"]


def test_still_red_keeps_the_gate_shut() -> None:
    runner = _Runner(after=RED)
    outcome = remediate(_verdict(), _Graph(), runner, _Writer(GOOD_DIFF), CONFIG)  # type: ignore[arg-type]
    assert not outcome.may_open_pr
    assert "not a red-to-green" in outcome.reason


def test_a_rejected_patch_never_reaches_the_runner() -> None:
    runner = _Runner()
    outcome = remediate(_verdict(), _Graph(), runner, _Writer(TEST_EDIT_DIFF), CONFIG)  # type: ignore[arg-type]
    assert runner.applied is None
    assert not outcome.may_open_pr


def test_a_patch_that_does_not_apply_keeps_the_gate_shut() -> None:
    runner = _Runner(apply_code=1)
    outcome = remediate(_verdict(), _Graph(), runner, _Writer(GOOD_DIFF), CONFIG)  # type: ignore[arg-type]
    assert runner.ran is None
    assert not outcome.may_open_pr


def test_an_unconfirmed_finding_never_reaches_the_writer() -> None:
    writer = _Writer(GOOD_DIFF)
    runner = _Runner()
    outcome = remediate(
        _verdict(FindingStatus.UNCOVERED, report=None),
        _Graph(),  # type: ignore[arg-type]
        runner,  # type: ignore[arg-type]
        writer,
        CONFIG,
    )
    assert writer.seen is None
    assert runner.applied is None
    assert not outcome.may_open_pr


def test_a_writer_that_returns_nothing_keeps_the_gate_shut() -> None:
    outcome = remediate(_verdict(), _Graph(), _Runner(), _Writer(None), CONFIG)  # type: ignore[arg-type]
    assert not outcome.may_open_pr


def test_judge_uses_the_confirming_run_as_before_not_a_fresh_one() -> None:
    verdict = _verdict()
    after = TestReport(
        id="after",
        package="repo",
        version="HEAD+patch",
        cases=[],
        passed=1,
        failed=0,
        errors=0,
        duration_s=0.1,
        raw_tail=GREEN,
        exit_code=0,
    )
    patch, _, _ = validate_written_patch(GOOD_DIFF, verdict)
    outcome = judge_remediation(verdict, patch, after)
    assert outcome.result is not None
    assert outcome.result.before is verdict.report
    assert outcome.may_open_pr
