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

from ..contracts.evidence import TestCase, TestReport, TestSelection
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


def _same_file(indexed: str, wanted: str) -> bool:
    """True when an indexed path is the file the finding names, not merely similar.

    The underlying query matches with `CONTAINS`, so asking for `core/patch.py`
    also returns `core/patch_helpers.py`, and asking for `store.py` returns
    every `*store.py` in the tree. Anchoring on a path-segment boundary keeps
    the substring query (it is what the index supports) while refusing its
    false positives.
    """
    if not indexed or not wanted:
        return False
    return indexed == wanted or indexed.endswith("/" + wanted.lstrip("/"))


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
    functions = [
        fn
        for fn in graph.functions_in(finding.file_path, repo)
        if _same_file(str(fn.get("file_path") or ""), finding.file_path)
    ]
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


def _split_by_site(
    report: TestReport, finding: ReviewFinding, contact_points: list[ContactPoint]
) -> tuple[list[TestCase], list[TestCase]]:
    """Partition failing cases into those touching the finding's site and the rest.

    The imports walk selects every test in a file that imports the changed
    module, which is deliberately wide — it is the only strategy that reaches
    an import-shaped break. The cost is that a selected test can fail for a
    reason with no bearing on the claim, and counting that as a confirmation
    would let any unrelated red in the same package vindicate any finding.

    A failure counts as related when the finding's file or one of its located
    function names appears in the test's node id or traceback. That is
    evidence of contact, not proof of causation, and it is the strongest link
    obtainable without instrumenting the run.
    """
    needles = {finding.file_path}
    module = finding.file_path.rsplit("/", 1)[-1].removesuffix(".py")
    if module:
        needles.add(module)
    needles.update(
        point.function_name
        for point in contact_points
        if point.function_name and point.function_name not in _SYNTHETIC_NAMES
    )

    related: list[TestCase] = []
    unrelated: list[TestCase] = []
    for case in report.cases:
        if case.outcome not in ("failed", "error"):
            continue
        haystack = f"{case.node_id}\n{case.traceback or ''}"
        (related if any(n in haystack for n in needles) else unrelated).append(case)
    return related, unrelated


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

    def verdict(status: FindingStatus, why: str) -> FindingVerdict:
        return FindingVerdict(
            finding=finding,
            contact_points=contact_points,
            selection=selection,
            report=report,
            status=status,
            why=why,
        )

    if report.is_execution_failure:
        return verdict(
            FindingStatus.INCONCLUSIVE,
            f"pytest exited {report.exit_code}, which is the runner reporting it "
            "could not do its job rather than a result about this code — "
            "a crashed run must not confirm a claim",
        )

    if report.ran_nothing:
        return verdict(
            FindingStatus.INCONCLUSIVE,
            f"{len(selection.tests)} test(s) were selected but none executed "
            "(all skipped or none collected), so nothing was observed either way",
        )

    if report.is_broken:
        related, unrelated = _split_by_site(report, finding, contact_points)
        if not related:
            return verdict(
                FindingStatus.INCONCLUSIVE,
                f"{len(unrelated)} test(s) failed, but none of them touch "
                f"{finding.file_path} — the failure is real and is not evidence "
                "about this claim",
            )
        shown = ", ".join(case.node_id for case in related[:3])
        return verdict(
            FindingStatus.CONFIRMED,
            f"{len(related)} failing test(s) reach {sites} — {shown}",
        )

    return verdict(
        FindingStatus.UNREPRODUCED,
        f"{report.passed} graph-selected test(s) reaching {sites} all passed — "
        "the claim did not reproduce here",
    )
