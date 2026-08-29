"""Parse pytest output into a :class:`TestReport`.

Pure. No subprocess, no filesystem, no clock — it takes a string, so the same
parser reads output from the Daytona sandbox, from a local run, or from a
committed fixture, unchanged.

The failure mode this module exists to prevent: our demo's red case is a
*collection* error, not a test failure. Both test modules never import, so
pytest emits zero per-test node ids and exits 2. A parser that only looks for
``FAILED`` lines calls that green and the product lies on stage. Every count
here is therefore taken as the *worst* of the per-case evidence and the summary
counts line, never the more optimistic of the two.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal

from ..contracts.evidence import TestCase, TestReport

__all__ = [
    "RAW_TAIL_CHARS",
    "parse_pytest",
    "strip_ansi",
]

#: How much trailing output a report carries for a human to read.
RAW_TAIL_CHARS = 2000

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

# `====== title ======` and `______ title ______` rules pytest draws.
_EQ_RULE = re.compile(r"^=+ (.+?) =+$")
_US_RULE = re.compile(r"^_+ (.+?) _+$")

_SUMMARY_HEADER = "short test summary info"
_END_OF_SUMMARY = re.compile(r"^(=|!){5,}")

# Lines inside the `-rA` short summary block.
_SUMMARY_ENTRY = re.compile(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b[ \t]*(.*)$")
# `SKIPPED [1] tests/test_x.py:12: needs network`
_SKIP_COUNT = re.compile(r"^\[\d+\]\s*")
# The same line's location, which is a file and line — never a pytest node id.
_SKIP_LOCATION = re.compile(r"^(?P<path>\S+\.py):\d+:")

# `0.24s call     tests/test_server.py::test_get_activities`
_DURATION = re.compile(r"^(\d+(?:\.\d+)?)s\s+(call|setup|teardown)\s+(\S+)$")

# `============ 61 passed in 0.50s ============`
_COUNT_PAIR = re.compile(
    r"(\d+)\s+(passed|failed|error|errors|skipped|xfailed|xpassed)"
)
_WALL_TIME = re.compile(r"\bin\s+(\d+(?:\.\d+)?)s\b")
_INTERRUPTED = re.compile(r"Interrupted:\s*(\d+)\s+error", re.IGNORECASE)

_Outcome = Literal["passed", "failed", "error", "skipped"]

_OUTCOMES: dict[str, _Outcome] = {
    "PASSED": "passed",
    "FAILED": "failed",
    "ERROR": "error",
    "SKIPPED": "skipped",
    "XFAIL": "skipped",
    "XPASS": "passed",
}


def strip_ansi(text: str) -> str:
    """Remove ANSI colour escapes so sandbox output parses like a fixture."""
    return _ANSI.sub("", text)


def _sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """Return ``(title, body_start, body_end)`` for each ``=== title ===`` rule."""
    marks = [
        (match.group(1).strip(), index)
        for index, line in enumerate(lines)
        if (match := _EQ_RULE.match(line.rstrip()))
    ]
    return [
        (
            title,
            start + 1,
            marks[position + 1][1] if position + 1 < len(marks) else len(lines),
        )
        for position, (title, start) in enumerate(marks)
    ]


def _section_body(lines: list[str], predicate: Callable[[str], bool]) -> list[str]:
    """Body of the first section whose title satisfies ``predicate``."""
    for title, start, end in _sections(lines):
        if predicate(title):
            return lines[start:end]
    return []


def _blocks(body: list[str]) -> list[tuple[str, str]]:
    """Split a section body on ``___ title ___`` rules into ``(title, text)``."""
    found: list[tuple[str, int]] = [
        (match.group(1).strip(), index)
        for index, line in enumerate(body)
        if (match := _US_RULE.match(line.rstrip()))
    ]
    out: list[tuple[str, str]] = []
    for position, (title, start) in enumerate(found):
        end = found[position + 1][1] if position + 1 < len(found) else len(body)
        out.append((title, "\n".join(body[start + 1 : end]).strip()))
    return out


def _summary_entries(lines: list[str]) -> list[tuple[_Outcome, str]]:
    """Parse the ``-rA`` short summary block into ``(outcome, node_id)`` pairs."""
    start = next(
        (
            index + 1
            for index, line in enumerate(lines)
            if (match := _EQ_RULE.match(line.rstrip()))
            and match.group(1).strip() == _SUMMARY_HEADER
        ),
        None,
    )
    if start is None:
        return []

    entries: list[tuple[_Outcome, str]] = []
    for line in lines[start:]:
        stripped = line.rstrip()
        if not stripped:
            continue
        if _END_OF_SUMMARY.match(stripped):
            break
        match = _SUMMARY_ENTRY.match(stripped)
        if match is None:
            continue
        outcome = _OUTCOMES[match.group(1)]
        rest = _SKIP_COUNT.sub("", match.group(2).strip())
        if not rest:
            continue
        # `FAILED tests/x.py::test_a - AssertionError: ...` — keep only the node id.
        node_id = rest.split(" - ", 1)[0].strip()
        # `SKIPPED [1] tests/x.py:12: needs network` has no node id at all.
        # Report the module rather than a string no consumer can select with.
        location = _SKIP_LOCATION.match(node_id)
        if location is not None:
            node_id = location.group("path")
        if node_id:
            entries.append((outcome, node_id))
    return entries


def _durations(lines: list[str]) -> dict[str, float]:
    """Sum per-phase ``--durations`` timings per node id."""
    body = _section_body(lines, lambda title: title.endswith("durations"))
    totals: dict[str, float] = {}
    for line in body:
        match = _DURATION.match(line.strip())
        if match is not None:
            totals[match.group(3)] = totals.get(match.group(3), 0.0) + float(
                match.group(1)
            )
    return totals


def _tracebacks(lines: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(by_node_id, by_test_name)`` traceback text.

    Collection errors are titled by file path (``ERROR collecting tests/x.py``);
    failures are titled by bare test name, which only later resolves to a node id.
    """
    by_node: dict[str, str] = {}
    by_name: dict[str, str] = {}

    for title, text in _blocks(_section_body(lines, lambda t: t == "ERRORS")):
        if not text:
            continue
        words = title.split()
        # `ERROR collecting tests/x.py` / `ERROR at setup of tests/x.py::test_a`
        key = words[-1] if words else title
        by_node.setdefault(key, text)
        by_name.setdefault(key.split("::")[-1], text)

    for title, text in _blocks(_section_body(lines, lambda t: t == "FAILURES")):
        if text:
            by_name.setdefault(title.split("::")[-1].strip(), text)

    return by_node, by_name


def _counts(lines: list[str]) -> tuple[dict[str, int], float]:
    """Counts and wall time from pytest's final ``=== N passed in Ts ===`` rule."""
    counts: dict[str, int] = {}
    wall = 0.0
    for title, _, _ in _sections(lines):
        pairs = _COUNT_PAIR.findall(title)
        if not pairs:
            continue
        counts = {}
        for number, word in pairs:
            key = "errors" if word.startswith("error") else word
            counts[key] = counts.get(key, 0) + int(number)
        match = _WALL_TIME.search(title)
        wall = float(match.group(1)) if match else 0.0
    return counts, wall


def parse_pytest(
    stdout: str,
    package: str,
    version: str,
    report_id: str,
    *,
    duration_s: float = 0.0,
    exit_code: int | None = None,
) -> TestReport:
    """Parse ``stdout`` from a pytest run into a :class:`TestReport`.

    ``duration_s`` is the wall time measured by the caller; when it is ``0.0``
    the time pytest printed on its summary line is used instead.

    ``exit_code`` is pytest's own exit status, straight off
    :attr:`~agentradar.adapters.sandbox.RawRun.exit_code`. Pass it whenever you
    have it. A run can exit nonzero for reasons no summary line explains — a
    usage error, an internal error, a plugin crash, ``-x`` cutting the run
    short — and the output may still contain nothing but passes. Counting that
    as green would let the verification gate approve a patch on a run that
    never finished.

    A collection error yields cases whose ``node_id`` is the *module* that would
    not import, because no per-test node id exists in that run.
    """
    text = strip_ansi(stdout)
    lines = text.splitlines()

    entries = _summary_entries(lines)
    durations = _durations(lines)
    tb_by_node, tb_by_name = _tracebacks(lines)

    cases: list[TestCase] = []
    seen: set[tuple[str, str]] = set()
    for outcome, node_id in entries:
        if (outcome, node_id) in seen:
            continue
        seen.add((outcome, node_id))
        traceback = None
        if outcome in ("failed", "error"):
            traceback = tb_by_node.get(node_id) or tb_by_name.get(
                node_id.split("::")[-1]
            )
        cases.append(
            TestCase(
                node_id=node_id,
                outcome=outcome,
                duration_s=durations.get(node_id, 0.0),
                traceback=traceback,
            )
        )

    counts, wall = _counts(lines)
    interrupted = _INTERRUPTED.search(text)

    from_cases = {
        "passed": sum(1 for case in cases if case.outcome == "passed"),
        "failed": sum(1 for case in cases if case.outcome == "failed"),
        "errors": sum(1 for case in cases if case.outcome == "error"),
    }

    # Take the worst evidence available. Under-reporting damage is the one
    # error this parser must never make.
    failed = max(from_cases["failed"], counts.get("failed", 0))
    errors = max(
        from_cases["errors"],
        counts.get("errors", 0),
        int(interrupted.group(1)) if interrupted else 0,
    )
    # The short summary lists only what `-r` was asked for; with `-rf` it holds
    # failures alone while the counts line still knows how many passed.
    passed = max(from_cases["passed"], counts.get("passed", 0))

    # Nothing in the output accounted for a nonzero exit. Refusing to call that
    # green is the entire job of this parser.
    if exit_code is not None and exit_code != 0 and failed == 0 and errors == 0:
        errors = 1

    return TestReport(
        id=report_id,
        package=package,
        version=version,
        cases=cases,
        passed=passed,
        failed=failed,
        errors=errors,
        duration_s=duration_s or wall,
        raw_tail=text[-RAW_TAIL_CHARS:],
    )
