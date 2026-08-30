"""Judge a reviewer's finding against the graph and a real test run.

Pure: no I/O, no network, no subprocess, no clock. The `CodeGraph` argument
is a Protocol, so this module unit-tests against `FakeCodeGraph` with no
FalkorDB running — the same trick `core/selection.py` uses. `CodeGraph` is
imported from `core.selection`, where it is declared, rather than from
`adapters/`, which rule 1 forbids.

The pipeline this implements is one sentence: *a reviewer says line N of file
F is wrong; find the function that contains line N, select the tests that
reach it, and report what running them actually showed.* The reviewer's
confidence never enters the calculation. Only the graph and the test counts
do.
"""

from __future__ import annotations

from ..contracts.evidence import TestReport, TestSelection
from ..contracts.finding import FindingStatus, FindingVerdict, ReviewFinding
from ..contracts.impact import ContactPoint
from .selection import CodeGraph

__all__ = ["judge_finding", "locate_finding"]


# The indexer emits a synthetic whole-file node named `<module>` alongside the
# real functions. It starts at line 1 and carries no end, so a naive
# containment test matches it for *every* line in the file and reports
# module scope as the enclosing site. It is never the answer we want when a
# real function also contains the line.
_SYNTHETIC_NAMES = frozenset({"<module>", "<lambda>"})


def _span(function: dict[str, object]) -> tuple[int, int] | None:
    """The node's line span, or None when it cannot be trusted for containment.

    A node needs both ends to bound a region. One with only a start could be
    a one-line function or could run to the end of the file, and guessing
    between those is how `<module>` came to swallow whole files.
    """
    start = function.get("start_line")
    end = function.get("end_line")
    if isinstance(start, int) and isinstance(end, int) and end >= start:
        return start, end
    return None


def _encloses(function: dict[str, object], line: int) -> bool:
    """True if `line` falls inside this function node's bounded span."""
    if str(function.get("name") or "") in _SYNTHETIC_NAMES:
        return False
    span = _span(function)
    return span is not None and span[0] <= line <= span[1]


def locate_finding(
    graph: CodeGraph, finding: ReviewFinding, repo: str
) -> list[ContactPoint]:
    """Map a finding's file and line onto function nodes the graph knows.

    Returns the enclosing function when the line lands inside one. When the
    finding carries no line, or no function's span contains it, every
    function in the file is returned instead — a whole-file blast radius is
    a weaker answer than a single site, but it is still evidence, whereas
    returning nothing would be indistinguishable from "this file is not
    indexed".

    An empty list therefore means exactly one thing: the graph has never
    seen this file.
    """
    functions = graph.functions_in(finding.file_path, repo)
    if not functions:
        return []

    if finding.line is not None:
        enclosing = [fn for fn in functions if _encloses(fn, finding.line)]
        if enclosing:
            # Nested definitions both contain the line; the innermost is the
            # site the reviewer actually commented on, so keep the tightest
            # span and drop the enclosing ones.
            tightest = min(
                span[1] - span[0] for fn in enclosing if (span := _span(fn)) is not None
            )
            functions = [
                fn
                for fn in enclosing
                if (span := _span(fn)) is not None and span[1] - span[0] == tightest
            ]

    points = [
        ContactPoint(
            symbol=finding.title,
            function_name=str(fn.get("name") or ""),
            fid=int(fn.get("fid") or 0),
            file_path=str(fn.get("file_path") or finding.file_path),
            line=start if isinstance(start := fn.get("start_line"), int) else None,
        )
        for fn in functions
    ]
    return sorted(points, key=lambda p: p.fid)


def judge_finding(
    finding: ReviewFinding,
    contact_points: list[ContactPoint],
    selection: TestSelection | None,
    report: TestReport | None,
) -> FindingVerdict:
    """Derive a status from evidence, in strict order of what is knowable.

    The order matters and is not arbitrary. We cannot claim a finding is
    unreproduced if we never located it, and we cannot claim it is uncovered
    if we never looked for tests. Each rung of the ladder is only reachable
    once the one below it succeeded, so a `CONFIRMED` verdict at the top
    carries every step beneath it.
    """
    if not contact_points:
        return FindingVerdict(
            finding=finding,
            contact_points=[],
            selection=selection,
            report=report,
            status=FindingStatus.UNLOCATABLE,
            why=(
                f"the graph has no functions indexed for {finding.file_path!r}, "
                "so this claim could not be checked against the codebase"
            ),
        )

    sites = ", ".join(point.function_name for point in contact_points) or "the file"

    if selection is None or not selection.tests:
        return FindingVerdict(
            finding=finding,
            contact_points=contact_points,
            selection=selection,
            report=report,
            status=FindingStatus.UNCOVERED,
            why=(
                f"located at {sites}, but no test in the graph reaches it — "
                "the claim is neither proven nor refuted"
            ),
        )

    if report is None:
        return FindingVerdict(
            finding=finding,
            contact_points=contact_points,
            selection=selection,
            report=None,
            status=FindingStatus.UNCOVERED,
            why=(
                f"located at {sites} and {len(selection.tests)} test(s) selected, "
                "but they were never run"
            ),
        )

    if report.is_broken:
        return FindingVerdict(
            finding=finding,
            contact_points=contact_points,
            selection=selection,
            report=report,
            status=FindingStatus.CONFIRMED,
            why=(
                f"{report.failed} failed and {report.errors} errored across "
                f"{len(selection.tests)} graph-selected test(s) reaching {sites}"
            ),
        )

    return FindingVerdict(
        finding=finding,
        contact_points=contact_points,
        selection=selection,
        report=report,
        status=FindingStatus.UNREPRODUCED,
        why=(
            f"{report.passed} graph-selected test(s) reaching {sites} all passed — "
            "the claim did not reproduce here"
        ),
    )
