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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.main.agentradar.adapters.graph import FalkorCodeGraph
from src.main.agentradar.adapters.localrunner import LocalRunner
from src.main.agentradar.adapters.patchwriter import LlmPatchWriter
from src.main.agentradar.adapters.review import DEFAULT_REVIEWERS, GhReviewSource
from src.main.agentradar.adapters.sandbox import SandboxRunner
from src.main.agentradar.contracts.finding import FindingStatus
from src.main.agentradar.core.review_run import (
    RunConfig,
    markdown_report,
    remediate,
    tally,
    verify_findings,
)

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
        "--fix",
        action="store_true",
        help=(
            "for each CONFIRMED finding, write a patch, apply it, and re-run the "
            "same tests. A pull request is only reachable on a proven red-to-green"
        ),
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = RunConfig(
        repo_key=args.repo_key,
        test_root=args.test_root,
        source_root=args.source_root,
        max_tests=args.max_tests,
    )

    say(f"\033[1mVerifying {args.repo} PR #{args.pr}\033[0m")
    say(f"  graph repo key : {config.repo_key}")
    say(f"  workdir        : {args.workdir}")
    say(f"  run tests      : {'no' if args.no_run else 'yes'}")

    reviewers = tuple(args.reviewer) if args.reviewer else DEFAULT_REVIEWERS
    findings = GhReviewSource(args.repo, reviewers=reviewers).findings(args.pr)
    say(f"\n{len(findings)} finding(s) from the reviewer.")
    if not findings:
        say("Nothing to verify. Either the review is clean or it has not run yet.")
        return 0

    graph = FalkorCodeGraph()
    runner: SandboxRunner | None = None if args.no_run else LocalRunner(args.workdir)

    def narrate(line: str) -> None:
        say(f"  {line}" if line.startswith(" ") else f"\n  \033[1m{line}\033[0m")

    verdicts = verify_findings(graph, findings, config, runner, narrate)

    if args.fix:
        confirmed = [v for v in verdicts if v.status is FindingStatus.CONFIRMED]
        say(f"\n\033[1mRepairing {len(confirmed)} confirmed finding(s)\033[0m")
        if runner is None:
            say("  --fix needs a runner; drop --no-run")
        else:
            writer = LlmPatchWriter()
            for verdict in confirmed:
                say(f"\n  \033[1m{verdict.finding.title}\033[0m")
                outcome = remediate(verdict, graph, runner, writer, config, narrate)
                gate = "OPEN" if outcome.may_open_pr else "SHUT"
                say(f"    gate: {gate} — {outcome.reason}")

    if args.markdown:
        print(markdown_report(verdicts, config))
        return 0

    say("\n\033[1mVerdicts\033[0m")
    for verdict in verdicts:
        say(f"  {BADGE[verdict.status]}  {verdict.finding.title}")
        say(f"      {verdict.why}")

    counts = tally(verdicts)
    say("\n  " + "  ".join(f"{s.value}={n}" for s, n in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
