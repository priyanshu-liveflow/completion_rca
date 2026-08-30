"""A proven repair becomes a pull-request plan; an unproven one becomes nothing."""

from __future__ import annotations

import pytest

from src.main.agentradar.contracts.evidence import TestReport, TestSelection
from src.main.agentradar.contracts.finding import (
    FindingStatus,
    FindingVerdict,
    ReviewFinding,
)
from src.main.agentradar.contracts.patch import Patch, VerifyResult
from src.main.agentradar.core.publish import (
    branch_name,
    build_plan,
    commit_message,
    pr_title,
)
from src.main.agentradar.core.remediation import RemediationOutcome


def _report(*, passed: int, failed: int, rid: str) -> TestReport:
    return TestReport(
        id=rid,
        package="demo",
        version="HEAD",
        cases=[],
        passed=passed,
        failed=failed,
        errors=0,
        duration_s=0.1,
        raw_tail="",
        exit_code=0 if failed == 0 else 1,
    )


def _outcome(*, proven: bool) -> RemediationOutcome:
    finding = ReviewFinding(
        id="f1",
        title="Discount multiplies instead of subtracting",
        body="",
        file_path="billing.py",
        line=3,
        reviewer="qodo-code-review[bot]",
    )
    before = _report(passed=0, failed=2, rid="before")
    after = _report(passed=2, failed=0 if proven else 1, rid="after")
    verdict = FindingVerdict(
        finding=finding,
        status=FindingStatus.CONFIRMED,
        why="two failing tests reach it",
        contact_points=[],
        selection=TestSelection(
            tests=["tests/test_billing.py::test_eighty"],
            strategy="callers",
            reached_from=["discount"],
        ),
        report=before,
    )
    patch = Patch(
        diff="diff --git a/billing.py b/billing.py\n",
        files=["billing.py"],
        rationale="",
    )
    return RemediationOutcome(
        verdict=verdict,
        patch=patch,
        applied=True,
        after=after,
        result=VerifyResult(patch=patch, before=before, after=after),
        reason="the repair is proven" if proven else "still red",
    )


def test_branch_is_derived_from_the_finding_and_is_git_safe() -> None:
    name = branch_name(_outcome(proven=True))
    assert name == "fix/agentradar-discount-multiplies-instead-of-subtracting"
    assert " " not in name and name.islower()


def test_the_same_finding_always_reuses_one_branch() -> None:
    # Re-running must not litter the remote with near-duplicate branches.
    assert branch_name(_outcome(proven=True)) == branch_name(_outcome(proven=True))


def test_title_names_the_file_the_repair_touched() -> None:
    assert pr_title(_outcome(proven=True)).startswith("fix(billing): ")


def test_commit_message_carries_the_numbers_that_were_proven() -> None:
    text = commit_message(_outcome(proven=True))
    assert "before: 2 failing" in text
    assert "after:  2 passing" in text
    assert "tests/test_billing.py::test_eighty" in text


def test_a_proven_repair_produces_a_plan_that_still_requires_approval() -> None:
    plan = build_plan(_outcome(proven=True))
    assert plan is not None
    assert plan.target == "github_pr"
    assert plan.requires_approval is True
    assert plan.payload["branch"].startswith("fix/agentradar-")
    assert plan.payload["base"] == "main"


def test_an_unproven_repair_produces_no_plan_at_all() -> None:
    # None rather than a plan carrying a flag: a caller that forgets to check
    # gets a TypeError, not a quiet publish.
    assert build_plan(_outcome(proven=False)) is None


@pytest.mark.parametrize("title", ["", "///", "🐞🐞🐞"])
def test_a_title_with_nothing_usable_still_yields_a_valid_branch(title: str) -> None:
    outcome = _outcome(proven=True)
    renamed = outcome.verdict.finding.model_copy(update={"title": title})
    outcome = RemediationOutcome(
        verdict=outcome.verdict.model_copy(update={"finding": renamed}),
        patch=outcome.patch,
        applied=outcome.applied,
        after=outcome.after,
        result=outcome.result,
        reason=outcome.reason,
    )
    assert branch_name(outcome) == "fix/agentradar-finding"
