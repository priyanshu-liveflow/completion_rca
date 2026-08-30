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
from .selection import CodeGraph, select_tests
from .testreport import parse_pytest

__all__ = [
    "RunConfig",
    "TestRunner",
    "markdown_report",
    "tally",
    "verify_finding",
    "verify_findings",
]


class RawRunLike(Protocol):
    """The part of a sandbox `RawRun` this module reads."""

    exit_code: int
    stdout: str
    duration_s: float


class TestRunner(Protocol):
    """Anything that can run pytest node ids and report what happened."""

    def run_tests(self, node_ids: list[str], *, timeout_s: int = 180) -> RawRunLike: ...


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
