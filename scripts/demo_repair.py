"""Prove the repair loop end to end, on a repo built for the purpose.

    python scripts/demo_repair.py              # real model, needs OPENAI_API_KEY
    python scripts/demo_repair.py --canned     # no model, no network

Builds a throwaway package with one real defect and one test that catches it,
runs the same pipeline a reviewer's finding goes through, and shows the gate
open only after the failing test passes. Nothing is mocked: real files, a real
pytest subprocess, a real diff, a real `git apply`.

The temp repo exists because the loop needs a *confirmed* finding to act on,
and a confirmed finding needs a genuinely failing test. Manufacturing one on
this repo would mean committing a bug.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.main.agentradar.adapters.localrunner import LocalRunner
from src.main.agentradar.adapters.store import SqliteStore
from src.main.agentradar.contracts.evidence import TestSelection
from src.main.agentradar.contracts.finding import FindingStatus, ReviewFinding
from src.main.agentradar.contracts.impact import ContactPoint
from src.main.agentradar.contracts.review import (
    RepairRecord,
    ReviewEntry,
    ReviewRun,
)
from src.main.agentradar.core.finding import judge_finding
from src.main.agentradar.core.remediation import RemediationRequest
from src.main.agentradar.core.review_run import RunConfig, remediate
from src.main.agentradar.core.testreport import parse_pytest

# The defect: `discount` applies the percentage the wrong way round, so a 20%
# discount charges 20% of the price instead of taking 20% off.
BUGGY = '''\
def discount(price: float, percent: float) -> float:
    """Return `price` reduced by `percent`."""
    return price * (percent / 100)
'''

TEST = """\
from billing import discount


def test_twenty_percent_off_a_hundred_is_eighty():
    assert discount(100.0, 20.0) == 80.0


def test_no_discount_leaves_the_price_alone():
    assert discount(50.0, 0.0) == 50.0
"""

CANNED_DIFF = """\
diff --git a/billing.py b/billing.py
--- a/billing.py
+++ b/billing.py
@@ -1,3 +1,3 @@
 def discount(price: float, percent: float) -> float:
     \"\"\"Return `price` reduced by `percent`.\"\"\"
-    return price * (percent / 100)
+    return price * (1 - percent / 100)
"""


class _CannedWriter:
    """Stands in for a model so the loop can be shown with no key and no network."""

    def write_patch(self, request: RemediationRequest) -> str:
        return CANNED_DIFF


class _StaticGraph:
    """The graph's part is already known here; only `read_source` is called."""

    def __init__(self, source: str) -> None:
        self._source = source

    def read_source(self, fid: int, repo: str, max_chars: int = 1500) -> str:
        return self._source

    def callers_of(self, *a: object, **k: object) -> list[dict[str, object]]:
        return []

    def import_edges(self, repo: str) -> list[dict[str, object]]:
        return []

    def functions_in(self, *a: object, **k: object) -> list[dict[str, object]]:
        return []


def say(message: str) -> None:
    print(message, flush=True)


def build_repo(root: Path) -> None:
    (root / "billing.py").write_text(BUGGY)
    (root / "test_billing.py").write_text(TEST)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=d@e.f",
            "-c",
            "user.name=demo",
            "commit",
            "-qm",
            "initial",
        ],
        cwd=root,
        check=True,
    )


def _persist(verdict: object, outcome: object, emit: object) -> None:
    """Store the run so the dashboard can show it.

    The demo repo is thrown away when this exits; the evidence should not be.
    A repair nobody can look at afterwards is the same problem as a mission
    that only ever existed in a terminal.
    """
    record = RepairRecord(
        diff=outcome.patch.diff if outcome.patch else "",  # type: ignore[attr-defined]
        files=list(outcome.patch.files) if outcome.patch else [],  # type: ignore[attr-defined]
        applied=outcome.applied,  # type: ignore[attr-defined]
        proven=outcome.may_open_pr,  # type: ignore[attr-defined]
        before_failed=(
            verdict.report.failed + verdict.report.errors  # type: ignore[attr-defined]
            if verdict.report  # type: ignore[attr-defined]
            else 0
        ),
        after_passed=outcome.after.passed if outcome.after else 0,  # type: ignore[attr-defined]
        reason=outcome.reason,  # type: ignore[attr-defined]
    )
    run = ReviewRun(
        id=str(uuid.uuid4()),
        repo="agentradar/demo-billing",
        pr=0,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        repo_key="billing",
        entries=[ReviewEntry(verdict=verdict, repair=record)],  # type: ignore[arg-type]
    )
    store = SqliteStore()
    store.save_review_run(run)

    export = Path(
        os.getenv("AGENTRADAR_REVIEW_EXPORT", "apps/web/public/review-runs.json")
    )
    export.parent.mkdir(parents=True, exist_ok=True)
    runs = store.list_review_runs()
    payload = [r.model_dump(mode="json") for r in runs]
    for item, rec in zip(payload, runs, strict=True):
        item["counts"] = rec.counts
        item["proven_repairs"] = rec.proven_repairs
    export.write_text(json.dumps(payload, indent=2))
    emit(f"\n   saved to the store and exported to {export}")  # type: ignore[operator]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="do not persist this run to the store or the dashboard export",
    )
    parser.add_argument(
        "--canned",
        action="store_true",
        help="use a fixed patch instead of a model (no key, no network)",
    )
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_repo(root)
        say(f"\033[1mA repo with one real defect\033[0m\n  {root}/billing.py")
        say("  discount(100, 20) should be 80.0 — it returns 20.0\n")

        runner = LocalRunner(root)
        selection = TestSelection(
            tests=["test_billing.py"], strategy="manual", reached_from=["discount"]
        )
        point = ContactPoint(
            symbol="discount",
            function_name="discount",
            fid=1,
            file_path="billing.py",
            line=1,
        )
        finding = ReviewFinding(
            id="demo",
            reviewer="qodo-code-review[bot]",
            file_path="billing.py",
            line=3,
            title="discount multiplies by the percentage instead of subtracting it",
            body="`discount(100, 20)` returns 20.0. It should return 80.0.",
        )

        say("\033[1m1. Run the tests that reach the site\033[0m")
        raw = runner.run_tests(selection.tests)
        before = parse_pytest(
            raw.stdout,
            package="billing",
            version="HEAD",
            report_id="before",
            duration_s=raw.duration_s,
            exit_code=raw.exit_code,
        )
        say(f"   passed={before.passed} failed={before.failed} exit={raw.exit_code}")

        verdict = judge_finding(finding, [point], selection, before)
        colour = "31" if verdict.status is FindingStatus.CONFIRMED else "33"
        say("\n\033[1m2. Verdict\033[0m")
        say(f"   \033[{colour}m{verdict.status.value.upper()}\033[0m")
        say(f"   {verdict.why}")

        if verdict.status is not FindingStatus.CONFIRMED:
            say("\n   Not confirmed, so no patch is attempted. That is the gate.")
            return 1

        writer: object
        if args.canned:
            writer = _CannedWriter()
            say("\n\033[1m3. Write a patch\033[0m\n   canned (no model)")
        else:
            from src.main.agentradar.adapters.patchwriter import LlmPatchWriter

            key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
            if not key:
                say("\n   No LLM_API_KEY or OPENAI_API_KEY. Re-run with --canned.")
                return 2
            os.environ.setdefault("LLM_API_KEY", key)
            os.environ.setdefault("LLM_BASE_URL", "https://api.openai.com/v1")
            os.environ.setdefault("LLM_MODEL", "gpt-5.4-mini")
            writer = LlmPatchWriter()
            say(f"\n\033[1m3. Write a patch\033[0m\n   {os.environ['LLM_MODEL']}")

        outcome = remediate(
            verdict,
            _StaticGraph(BUGGY),  # type: ignore[arg-type]
            runner,  # type: ignore[arg-type]
            writer,  # type: ignore[arg-type]
            RunConfig(repo_key="billing"),
            lambda line: say(f"   {line.strip()}"),
        )

        if outcome.patch is not None:
            say("\n\033[1m4. The patch\033[0m")
            for line in outcome.patch.diff.splitlines():
                mark = (
                    "32"
                    if line.startswith("+")
                    else "31"
                    if line.startswith("-")
                    else "90"
                )
                say(f"   \033[{mark}m{line}\033[0m")

        if not args.no_save:
            _persist(verdict, outcome, say)

        gate = "OPEN" if outcome.may_open_pr else "SHUT"
        colour = "32" if outcome.may_open_pr else "31"
        say(f"\n\033[1m5. Gate: \033[{colour}m{gate}\033[0m")
        say(f"   {outcome.reason}")
        if outcome.may_open_pr:
            # Precise wording on purpose. `can_act` authorises the PR tool; it
            # does not call it, and this demo repo is a temp directory with no
            # remote to open one against. Saying "a PR was opened" would be the
            # exact kind of unproven claim this whole product exists to refuse.
            say("\n   The PR tool is now reachable. It was not before.")
            say("   (Authorised, not opened — this repo is a temp directory.)")
        return 0 if outcome.may_open_pr else 1


if __name__ == "__main__":
    raise SystemExit(main())
