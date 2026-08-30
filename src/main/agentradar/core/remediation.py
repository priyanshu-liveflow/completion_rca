"""Turn a confirmed review finding into a patch that is proven, or nothing.

Pure. No I/O, no network, no subprocess, no clock. Patch *writing* is a
Protocol and patch *application* happens in a runner; this module owns the
decisions that must not be delegated to whichever model wrote the diff:

1. What may the patch touch? Derived from the contact points the graph
   located, never from the diff or the model's own claim about it.
2. Did it work? Only a real red-to-green transition counts, computed by
   `core.patch.build_verify_result`, whose `verified` field is a computed
   property that cannot be supplied.

The ordering matters and is the whole safety argument. A finding must already
be CONFIRMED before anything is written, which means a test was observed
failing at the named site. That failing test becomes the acceptance criterion
for the patch, so "the model said it fixed it" is never part of the chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..contracts.evidence import TestReport
from ..contracts.finding import FindingStatus, FindingVerdict
from ..contracts.patch import Patch, VerifyResult
from .patch import build_verify_result, can_act, parse_diff, validate_patch

__all__ = [
    "PatchWriter",
    "RemediationOutcome",
    "RemediationRequest",
    "allowed_files_for",
    "build_request",
    "judge_remediation",
    "may_attempt",
]


@dataclass(frozen=True)
class RemediationRequest:
    """Everything a patch writer is allowed to see. No credentials, ever."""

    finding_title: str
    finding_body: str
    file_path: str
    function_name: str
    source: str
    failing_tests: list[str]
    failure_excerpt: str
    allowed_files: list[str]


class PatchWriter(Protocol):
    """Writes a unified diff for a request, or returns None if it cannot."""

    def write_patch(self, request: RemediationRequest) -> str | None: ...


@dataclass(frozen=True)
class RemediationOutcome:
    """What happened, with every step's evidence kept rather than summarised."""

    verdict: FindingVerdict
    patch: Patch | None
    applied: bool
    after: TestReport | None
    result: VerifyResult | None
    reason: str

    @property
    def may_open_pr(self) -> bool:
        """The gate. A PR is unreachable without a proven red-to-green."""
        return can_act(self.result)


def may_attempt(verdict: FindingVerdict) -> tuple[bool, str]:
    """Only a confirmed finding earns a patch attempt.

    Every other status means we do not have a failing test at the named site,
    and without one there is nothing to prove a patch against. Writing a diff
    for an `uncovered` finding would produce a change whose only justification
    is that a model agreed with a reviewer — which is precisely the guessing
    this product exists to replace.
    """
    if verdict.status is not FindingStatus.CONFIRMED:
        return False, (
            f"finding is {verdict.status.value}, not confirmed — there is no "
            "failing test to prove a patch against"
        )
    if verdict.report is None or not verdict.selection:
        return False, "confirmed without a report or selection, which cannot happen"
    return True, "a failing test at the named site is available as acceptance criteria"


def allowed_files_for(verdict: FindingVerdict) -> list[str]:
    """The blast radius, from the graph's contact points rather than the diff.

    The list a patch is checked against must not come from the same place the
    patch did. These are the files the graph located for this finding, so a
    model can widen its diff but cannot widen its permission.
    """
    seen: set[str] = set()
    files: list[str] = []
    for point in verdict.contact_points:
        path = (
            point.contact_point_path
            if hasattr(point, "contact_point_path")
            else point.file_path
        )
        if path and path not in seen:
            seen.add(path)
            files.append(path)
    return sorted(files)


def build_request(verdict: FindingVerdict, source: str) -> RemediationRequest:
    """Assemble what the patch writer sees. Deliberately narrow.

    It gets the claim, the source of the located function, the tests that
    failed, and the tail of the failure output. It does not get the repository,
    the environment, or any credential — the harness holds those, and a patch
    writer that needs them is doing something other than editing code.
    """
    failing = [
        case.node_id
        for case in (verdict.report.cases if verdict.report else [])
        if case.outcome in ("failed", "error")
    ]
    excerpt = verdict.report.raw_tail if verdict.report else ""
    point = verdict.contact_points[0] if verdict.contact_points else None
    return RemediationRequest(
        finding_title=verdict.finding.title,
        finding_body=verdict.finding.body,
        file_path=verdict.finding.file_path,
        function_name=point.function_name if point else "",
        source=source,
        failing_tests=failing,
        failure_excerpt=excerpt,
        allowed_files=allowed_files_for(verdict),
    )


def validate_written_patch(
    diff: str, verdict: FindingVerdict
) -> tuple[Patch | None, bool, str]:
    """Parse and check a written diff against the graph-derived blast radius.

    The file list is re-derived from the diff text; whatever the writer said
    it touched is discarded. `git apply` and this check must share one view of
    the patch, and the diff is the only view `git apply` has.
    """
    if not diff.strip():
        return None, False, "the patch writer produced nothing"
    patch = parse_diff(diff)
    ok, reason = validate_patch(patch, allowed_files_for(verdict))
    return patch, ok, reason


def judge_remediation(
    verdict: FindingVerdict,
    patch: Patch | None,
    after: TestReport | None,
) -> RemediationOutcome:
    """Assemble the outcome and compute whether a PR may open.

    `before` is the report that confirmed the finding — the same run, not a
    fresh one. Re-deriving it here would let a flaky re-run turn a real repair
    into an unproven one, or worse, the reverse.
    """
    if patch is None or after is None or verdict.report is None:
        return RemediationOutcome(
            verdict=verdict,
            patch=patch,
            applied=False,
            after=after,
            result=None,
            reason="no patch was applied and re-run, so nothing was proven",
        )

    result = build_verify_result(patch, verdict.report, after)
    if result.verified:
        reason = (
            f"{verdict.report.failed + verdict.report.errors} failing test(s) now "
            f"pass ({after.passed} passed) — the repair is proven"
        )
    else:
        reason = (
            f"after the patch: passed={after.passed} failed={after.failed} "
            f"errors={after.errors} — not a red-to-green transition, so no PR"
        )
    return RemediationOutcome(
        verdict=verdict,
        patch=patch,
        applied=True,
        after=after,
        result=result,
        reason=reason,
    )
