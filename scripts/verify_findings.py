"""Verify a code reviewer's findings against our own indexed pipeline.

    python scripts/verify_findings.py --pr 20
    python scripts/verify_findings.py --pr 20 --no-run     # locate only, instant

Qodo reviews the code; this verifies Qodo. Each finding is put through the
same machinery a dependency mission uses — locate the site in the FalkorDB
graph, select the tests that reach it, run them for real — and comes back
with one of four verdicts. `uncovered` is the honest one most tools skip:
located, but no test reaches it, so we decline to call it either way.

Every connection is configurable, by flag or environment variable, so this
runs on a machine that is not the one it was written on.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.main.agentradar.adapters.graph import FalkorCodeGraph
from src.main.agentradar.adapters.localrunner import LocalRunner
from src.main.agentradar.adapters.review import DEFAULT_REVIEWERS, GhReviewSource
from src.main.agentradar.adapters.sandbox import SandboxRunner
from src.main.agentradar.contracts.finding import FindingStatus, FindingVerdict
from src.main.agentradar.core.finding import judge_finding, locate_finding
from src.main.agentradar.core.selection import select_tests
from src.main.agentradar.core.testreport import parse_pytest

BADGE = {
    FindingStatus.CONFIRMED: "\033[31mCONFIRMED\033[0m",
    FindingStatus.UNREPRODUCED: "\033[32mUNREPRODUCED\033[0m",
    FindingStatus.UNCOVERED: "\033[33mUNCOVERED\033[0m",
    FindingStatus.UNLOCATABLE: "\033[90mUNLOCATABLE\033[0m",
    FindingStatus.INCONCLUSIVE: "\033[35mINCONCLUSIVE\033[0m",
}


def say(message: str) -> None:
    """Narrate a step as it happens, unbuffered.

    The pipeline spends real seconds in the graph and in pytest. Printing
    only at the end makes a working run look like a hung one, on a recording
    as much as in a terminal.

    Goes to stderr so it still shows in a terminal while leaving stdout clean
    enough to pipe — `--markdown | gh pr comment --body-file -` would
    otherwise post the progress log along with the table.
    """
    print(message, file=sys.stderr, flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pr", type=int, required=True, help="pull request number")
    p.add_argument(
        "--repo",
        default=os.getenv("AGENTRADAR_REPO", "priyanshu-liveflow/completion_rca"),
        help="owner/name for `gh api` [env: AGENTRADAR_REPO]",
    )
    p.add_argument(
        "--repo-key",
        default=os.getenv("AGENTRADAR_REPO_KEY", "research-agents"),
        help="graph repo key, the last path segment [env: AGENTRADAR_REPO_KEY]",
    )
    p.add_argument(
        "--workdir",
        default=os.getenv("AGENTRADAR_WORKDIR", str(Path(__file__).parent.parent)),
        help="checkout the tests run in [env: AGENTRADAR_WORKDIR]",
    )
    p.add_argument(
        "--source-root",
        default=os.getenv("AGENTRADAR_SOURCE_ROOT", ""),
        help=(
            "package prefix stripped from a module path before matching imports. "
            "Empty for this repo, whose own tests import `src.main.agentradar...` "
            "with the `src.` still on the front [env: AGENTRADAR_SOURCE_ROOT]"
        ),
    )
    p.add_argument(
        "--test-root",
        default=os.getenv("AGENTRADAR_TEST_ROOT", "tests"),
        help="[env: AGENTRADAR_TEST_ROOT]",
    )
    p.add_argument(
        "--reviewer",
        action="append",
        default=None,
        help="reviewer login to accept findings from; repeatable",
    )
    p.add_argument(
        "--max-tests", type=int, default=8, help="cap tests selected per finding"
    )
    p.add_argument(
        "--markdown",
        action="store_true",
        help="emit a markdown table on stdout, for posting back to the PR",
    )
    p.add_argument(
        "--no-run",
        action="store_true",
        help="locate and select only; do not run tests",
    )
    return p


def verify_one(
    finding: object,
    graph: FalkorCodeGraph,
    runner: SandboxRunner | None,
    args: argparse.Namespace,
) -> FindingVerdict:
    """Locate -> select -> run -> judge, for one finding."""
    from src.main.agentradar.contracts.finding import ReviewFinding

    assert isinstance(finding, ReviewFinding)
    where = f"{finding.file_path}:{finding.line or '?'}"
    say(f"\n  \033[1m{finding.title}\033[0m\n    {where}")

    points = locate_finding(graph, finding, args.repo_key)
    if not points:
        say("    graph: no functions indexed for this file")
        return judge_finding(finding, [], None, None)
    say(f"    graph: {len(points)} function(s) — {points[0].function_name}")

    selection = select_tests(
        graph,
        points,
        args.repo_key,
        max_tests=args.max_tests,
        test_root=args.test_root,
        source_root=args.source_root,
    )
    if not selection.tests:
        say("    select: no test reaches this site")
        return judge_finding(finding, points, selection, None)
    say(f"    select: {len(selection.tests)} test(s) via {selection.strategy}")

    if runner is None:
        return judge_finding(finding, points, selection, None)

    say(f"    run:    pytest {len(selection.tests)} test(s) ...")
    started = time.monotonic()
    raw = runner.run_tests(selection.tests)
    report = parse_pytest(
        raw.stdout,
        package=args.repo_key,
        version="HEAD",
        report_id=f"finding-{finding.id}",
        duration_s=raw.duration_s,
        exit_code=raw.exit_code,
    )
    say(
        f"    run:    passed={report.passed} failed={report.failed} "
        f"errors={report.errors} in {time.monotonic() - started:.1f}s"
    )
    return judge_finding(finding, points, selection, report)


MARKDOWN_BADGE = {
    FindingStatus.CONFIRMED: "🔴 **confirmed**",
    FindingStatus.UNREPRODUCED: "🟢 unreproduced",
    FindingStatus.UNCOVERED: "🟡 uncovered",
    FindingStatus.UNLOCATABLE: "⚪ unlocatable",
    FindingStatus.INCONCLUSIVE: "🟣 inconclusive",
}


def render_markdown(verdicts: list[FindingVerdict], args: argparse.Namespace) -> str:
    """A PR comment. Leads with the count that should change someone's mind."""
    tally = {status: 0 for status in FindingStatus}
    for verdict in verdicts:
        tally[verdict.status] += 1

    lines = [
        "## AgentRadar verified this review",
        "",
        f"Each finding was located in the code graph, the tests reaching it were "
        f"selected, and those tests were run against `{args.repo_key}`.",
        "",
        f"**{tally[FindingStatus.CONFIRMED]} confirmed** · "
        f"{tally[FindingStatus.UNREPRODUCED]} unreproduced · "
        f"{tally[FindingStatus.UNCOVERED]} uncovered · "
        f"{tally[FindingStatus.INCONCLUSIVE]} inconclusive · "
        f"{tally[FindingStatus.UNLOCATABLE]} unlocatable",
        "",
        "| verdict | finding | evidence |",
        "|---|---|---|",
    ]
    for verdict in verdicts:
        title = verdict.finding.title.replace("|", "\\|")
        why = verdict.why.replace("|", "\\|")
        lines.append(f"| {MARKDOWN_BADGE[verdict.status]} | {title} | {why} |")

    lines += [
        "",
        "<sub>`uncovered` means located but no test reaches it — neither proven "
        "nor refuted. `unlocatable` means the graph has not indexed that file. "
        "Neither is a false positive.</sub>",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    say(f"\033[1mVerifying {args.repo} PR #{args.pr}\033[0m")
    say(f"  graph repo key : {args.repo_key}")
    say(f"  workdir        : {args.workdir}")
    say(f"  run tests      : {'no' if args.no_run else 'yes'}")

    reviewers = tuple(args.reviewer) if args.reviewer else DEFAULT_REVIEWERS
    source = GhReviewSource(args.repo, reviewers=reviewers)
    findings = source.findings(args.pr)
    say(f"\n{len(findings)} finding(s) from the reviewer.")
    if not findings:
        say("Nothing to verify. Either the review is clean or it has not run yet.")
        return 0

    graph = FalkorCodeGraph()
    runner: SandboxRunner | None = None if args.no_run else LocalRunner(args.workdir)

    verdicts = [verify_one(f, graph, runner, args) for f in findings]

    if args.markdown:
        print(render_markdown(verdicts, args))
        return 0

    say("\n\033[1mVerdicts\033[0m")
    for verdict in verdicts:
        say(f"  {BADGE[verdict.status]}  {verdict.finding.title}")
        say(f"      {verdict.why}")

    tally = {status: 0 for status in FindingStatus}
    for verdict in verdicts:
        tally[verdict.status] += 1
    say(
        "\n  " + "  ".join(f"{status.value}={count}" for status, count in tally.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
