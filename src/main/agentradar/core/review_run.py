"""The verify-a-review pipeline: locate, select, run, judge.

Pure orchestration over Protocols. Nothing here imports `adapters/` (rule 1)
or opens a socket: the graph arrives as the `CodeGraph` Protocol declared in
`core/selection.py`, and the runner as `TestRunner` below, which
`adapters.localrunner.LocalRunner` and `adapters.sandbox.DaytonaRunner` both
satisfy structurally.

This lives in the package rather than in `scripts/` so it can be tested, typed
under `mypy --strict`, and reused by an MCP tool or a webhook handler without
either of them shelling out to a CLI. The script is now argument parsing and
printing, which is all a script should be.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from ..contracts.evidence import TestReport
from ..contracts.finding import FindingStatus, FindingVerdict, ReviewFinding
from .finding import judge_finding, locate_finding
from .remediation import (
    PatchWriter,
    RemediationOutcome,
    build_request,
    judge_remediation,
    may_attempt,
    validate_written_patch,
)
from .selection import CodeGraph, select_tests
from .testreport import parse_pytest

__all__ = [
    "RunConfig",
    "TestRunner",
    "markdown_report",
    "remediate",
    "tally",
    "verify_finding",
    "verify_findings",
]


class RawRunLike(Protocol):
    """The part of a sandbox `RawRun` this module reads.

    Declared as read-only properties rather than plain attributes. `RawRun` is
    a frozen dataclass, so its fields cannot be assigned, and a Protocol whose
    members are writable attributes is not satisfied by a frozen one — the
    implementation would have to promise a mutability nothing here wants.
    """

    @property
    def exit_code(self) -> int: ...

    @property
    def stdout(self) -> str: ...

    @property
    def duration_s(self) -> float: ...


class TestRunner(Protocol):
    """Anything that can run pytest node ids and report what happened."""

    def run_tests(self, node_ids: list[str], *, timeout_s: int = 180) -> RawRunLike: ...


class PatchingRunner(TestRunner, Protocol):
    """A runner that can also apply a diff inside its own checkout."""

    def apply_patch(self, diff: str) -> RawRunLike: ...


class SourceGraph(CodeGraph, Protocol):
    """`CodeGraph` plus source reading, which only remediation needs.

    Widened here rather than in `core/selection.py`, whose Protocol is
    deliberately the narrow slice selection uses. A consumer asks for the
    capabilities it actually calls; `FalkorCodeGraph` satisfies both.
    """

    def read_source(self, fid: int, repo: str, max_chars: int = 1500) -> str: ...


@dataclass(frozen=True)
class RunConfig:
    """Everything the pipeline needs to know about the repo under review."""

    repo_key: str
    test_root: str = "tests"
    source_root: str = ""
    max_tests: int = 8


# Called with a short human-readable progress line. Defaults to discarding it,
# so the pipeline stays silent in a library and narrates in a CLI.
Narrator = Callable[[str], None]


def _silent(_: str) -> None:
    return None


def verify_finding(
    graph: CodeGraph,
    finding: ReviewFinding,
    config: RunConfig,
    runner: TestRunner | None = None,
    narrate: Narrator = _silent,
) -> FindingVerdict:
    """Put one finding through the whole pipeline and return its verdict.

    `runner=None` stops after selection, which is a real mode rather than a
    degraded one: it answers "is this claim even testable" in milliseconds,
    and every verdict it can reach (`unlocatable`, `uncovered`) is one that
    running tests would not have changed.
    """
    narrate(f"{finding.file_path}:{finding.line or '?'}")

    points = locate_finding(graph, finding, config.repo_key)
    if not points:
        narrate("  graph: no functions indexed for this file")
        return judge_finding(finding, [], None, None)
    narrate(f"  graph: {len(points)} function(s) — {points[0].function_name}")

    selection = select_tests(
        graph,
        points,
        config.repo_key,
        max_tests=config.max_tests,
        test_root=config.test_root,
        source_root=config.source_root,
    )
    if not selection.tests:
        narrate("  select: no test reaches this site")
        return judge_finding(finding, points, selection, None)
    narrate(f"  select: {len(selection.tests)} test(s) via {selection.strategy}")

    if runner is None:
        return judge_finding(finding, points, selection, None)

    narrate(f"  run:    pytest {len(selection.tests)} test(s) ...")
    raw = runner.run_tests(selection.tests)
    report: TestReport = parse_pytest(
        raw.stdout,
        package=config.repo_key,
        version="HEAD",
        report_id=f"finding-{finding.id}",
        duration_s=raw.duration_s,
        exit_code=raw.exit_code,
    )
    narrate(
        f"  run:    passed={report.passed} failed={report.failed} "
        f"errors={report.errors} in {report.duration_s:.1f}s"
    )
    return judge_finding(finding, points, selection, report)


def verify_findings(
    graph: CodeGraph,
    findings: Iterable[ReviewFinding],
    config: RunConfig,
    runner: TestRunner | None = None,
    narrate: Narrator = _silent,
) -> list[FindingVerdict]:
    """Verify every finding, in the order the reviewer left them."""
    return [
        verify_finding(graph, finding, config, runner, narrate) for finding in findings
    ]


def tally(verdicts: Sequence[FindingVerdict]) -> dict[FindingStatus, int]:
    """Count verdicts by status, with every status present even at zero."""
    counts = dict.fromkeys(FindingStatus, 0)
    for verdict in verdicts:
        counts[verdict.status] += 1
    return counts


_MARKDOWN_BADGE = {
    FindingStatus.CONFIRMED: "🔴 **confirmed**",
    FindingStatus.UNREPRODUCED: "🟢 unreproduced",
    FindingStatus.UNCOVERED: "🟡 uncovered",
    FindingStatus.INCONCLUSIVE: "🟣 inconclusive",
    FindingStatus.UNLOCATABLE: "⚪ unlocatable",
}


def markdown_report(verdicts: Sequence[FindingVerdict], config: RunConfig) -> str:
    """A pull-request comment. Leads with the count that should change a mind."""
    counts = tally(verdicts)
    lines = [
        "## AgentRadar verified this review",
        "",
        "Each finding was located in the code graph, the tests reaching it were "
        f"selected, and those tests were run against `{config.repo_key}`.",
        "",
        f"**{counts[FindingStatus.CONFIRMED]} confirmed** · "
        f"{counts[FindingStatus.UNREPRODUCED]} unreproduced · "
        f"{counts[FindingStatus.UNCOVERED]} uncovered · "
        f"{counts[FindingStatus.INCONCLUSIVE]} inconclusive · "
        f"{counts[FindingStatus.UNLOCATABLE]} unlocatable",
        "",
        "| verdict | finding | evidence |",
        "|---|---|---|",
    ]
    for verdict in verdicts:
        title = verdict.finding.title.replace("|", "\\|")
        why = verdict.why.replace("|", "\\|")
        lines.append(f"| {_MARKDOWN_BADGE[verdict.status]} | {title} | {why} |")
    lines += [
        "",
        "<sub>`uncovered` means located but no test reaches it. `inconclusive` "
        "means the run could not speak to the claim. `unlocatable` means the "
        "graph has not indexed that file. None of the three is a false "
        "positive.</sub>",
    ]
    return "\n".join(lines)


def remediate(
    verdict: FindingVerdict,
    graph: SourceGraph,
    runner: PatchingRunner,
    writer: PatchWriter,
    config: RunConfig,
    narrate: Narrator = _silent,
) -> RemediationOutcome:
    """Attempt a proven repair for one confirmed finding.

    The sequence is fixed and each step can only refuse, never widen:

    1. Refuse unless the finding is CONFIRMED — otherwise there is no failing
       test to prove anything against.
    2. Read the located function's source from the graph. That, the claim and
       the failure output are all the writer sees. No credentials.
    3. Validate the returned diff against the graph's blast radius and the
       no-editing-tests rule, re-deriving the file list from the diff text.
    4. Apply it, re-run *the same tests that failed*, and judge.

    A patch that fails to apply, or applies without turning the tests green,
    leaves `may_open_pr` false. The caller is responsible for reverting the
    checkout; this function does not mutate anything it was not handed.
    """
    allowed, why = may_attempt(verdict)
    if not allowed:
        narrate(f"  patch:  skipped — {why}")
        return judge_remediation(verdict, None, None)

    point = verdict.contact_points[0]
    source = graph.read_source(point.fid, config.repo_key)
    request = build_request(verdict, source)
    narrate(f"  patch:  writing for {point.function_name} ...")

    diff = writer.write_patch(request)
    patch, ok, reason = validate_written_patch(diff or "", verdict)
    if not ok:
        narrate(f"  patch:  rejected — {reason}")
        return judge_remediation(verdict, None, None)
    narrate(f"  patch:  {len(patch.files if patch else [])} file(s), validated")

    applied = runner.apply_patch(patch.diff if patch else "")
    if applied.exit_code != 0:
        narrate("  patch:  did not apply cleanly")
        return judge_remediation(verdict, None, None)

    selection = verdict.selection
    tests = list(selection.tests) if selection else []
    narrate(f"  verify: re-running {len(tests)} test(s) ...")
    raw = runner.run_tests(tests)
    after = parse_pytest(
        raw.stdout,
        package=config.repo_key,
        version="HEAD+patch",
        report_id=f"finding-{verdict.finding.id}-after",
        duration_s=raw.duration_s,
        exit_code=raw.exit_code,
    )
    outcome = judge_remediation(verdict, patch, after)
    narrate(f"  verify: {outcome.reason}")
    return outcome
