"""Turn a proven repair into the plan for a pull request. Pure.

Nothing here opens anything. It names a branch, writes a title and a commit
message, and builds the :class:`ActionPlan` that ``adapters.github.execute``
will refuse unless :func:`core.patch.can_act` is true. Keeping this in
``core/`` means the wording of a pull request is unit-testable without a
network, and means the *decision* to publish is expressed as data that the
gate inspects rather than as a call site the gate has to trust.
"""

from __future__ import annotations

import re

from ..contracts.mission import ActionPlan
from .remediation import RemediationOutcome

__all__ = ["branch_name", "build_plan", "commit_message", "pr_title"]

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_MAX_SLUG = 48


def _slug(text: str) -> str:
    """A branch-safe fragment of a finding title, or ``finding`` if nothing survives."""
    cleaned = _SLUG_STRIP.sub("-", text.lower()).strip("-")
    return cleaned[:_MAX_SLUG].strip("-") or "finding"


def branch_name(outcome: RemediationOutcome, *, prefix: str = "fix") -> str:
    """A deterministic branch for this finding.

    Deterministic on purpose: re-running the pipeline for the same finding
    must reuse the branch rather than litter the remote with near-duplicates,
    and a reader looking at the branch list should be able to tell which
    finding produced it without opening the pull request.
    """
    finding = outcome.verdict.finding
    return f"{prefix}/agentradar-{_slug(finding.title)}"


def pr_title(outcome: RemediationOutcome) -> str:
    """Conventional-commit title naming the file the repair touched."""
    files = outcome.patch.files if outcome.patch else []
    scope = files[0].rsplit("/", 1)[-1].removesuffix(".py") if files else "repair"
    return f"fix({scope}): {outcome.verdict.finding.title}"


def commit_message(outcome: RemediationOutcome) -> str:
    """Commit body carrying the evidence, not just the claim.

    The numbers come from the two test reports the gate already read, so the
    commit says what was proven rather than what was intended. A reader who
    never opens the pull request still sees the red-to-green.
    """
    before = outcome.verdict.report
    after = outcome.after
    failed = (before.failed + before.errors) if before else 0
    passed = after.passed if after else 0
    tests = list(outcome.verdict.selection.tests) if outcome.verdict.selection else []
    body = [
        pr_title(outcome),
        "",
        "A reviewer reported this and a test run confirmed it. The patch below",
        "was written against the failing tests and re-run against the same ones.",
        "",
        f"before: {failed} failing",
        f"after:  {passed} passing",
        "",
        "tests that decided it:",
        *[f"  {node}" for node in tests],
    ]
    return "\n".join(body)


def build_plan(
    outcome: RemediationOutcome, *, base: str = "main", prefix: str = "fix"
) -> ActionPlan | None:
    """The pull-request plan, or ``None`` when the repair was not proven.

    ``None`` rather than a plan with a flag: a caller that forgets to check
    gets a ``TypeError`` at the next line instead of quietly publishing. The
    gate in ``adapters.github.execute`` is still the authority — this is the
    earlier of two refusals, not a replacement for it.
    """
    if not outcome.may_open_pr or outcome.patch is None:
        return None
    return ActionPlan(
        target="github_pr",
        summary=outcome.reason,
        payload={
            "branch": branch_name(outcome, prefix=prefix),
            "title": pr_title(outcome),
            "base": base,
            "diff": outcome.patch.diff,
        },
        requires_approval=True,
    )
