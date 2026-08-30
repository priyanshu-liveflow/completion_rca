"""A code-review finding, and what our own evidence says about it.

A reviewer — Qodo, or any bot that comments on a pull request — asserts that
a specific file and line is wrong. That assertion is a *hypothesis*, exactly
like a graph hit is a hypothesis in `impact.py`. This module models the
hypothesis and the verdict our pipeline reaches about it, so the two never
get conflated: `ReviewFinding` is what the reviewer claimed, `FindingVerdict`
is what we proved.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from .evidence import TestReport, TestSelection
from .impact import ContactPoint


class ReviewFinding(BaseModel):
    """One reviewer comment, reduced to the claim it makes about the code."""

    model_config = ConfigDict(frozen=True)

    id: str
    reviewer: str
    file_path: str
    line: int | None
    title: str
    body: str
    url: str | None = None


class FindingStatus(StrEnum):
    """What our pipeline could prove about a reviewer's claim.

    Deliberately four values, not two. "Not confirmed" collapses three very
    different situations — we ran tests and they passed, no test reaches the
    code at all, and we could not even find the code — and a reviewer that
    reports all three as "false positive" is lying twice out of three times.
    """

    CONFIRMED = "confirmed"
    """A graph-selected test failed at the site the finding names."""

    UNREPRODUCED = "unreproduced"
    """Tests reached the site and passed. The claim is not proven here."""

    UNCOVERED = "uncovered"
    """Located in the graph, but no test reaches it. We cannot say either way."""

    UNLOCATABLE = "unlocatable"
    """The file and line map to nothing the graph indexed."""

    INCONCLUSIVE = "inconclusive"
    """Tests ran, but what came back cannot speak to this claim.

    Three situations land here, and none of them is a statement about the
    reviewer being right or wrong: pytest itself failed (a timeout, a usage
    error, a plugin crash), nothing actually executed because every selected
    test skipped, or tests failed somewhere with no connection to the site
    the finding names. Reporting any of these as `confirmed` would let broken
    infrastructure vindicate an arbitrary claim.
    """


class FindingVerdict(BaseModel):
    """A finding plus the evidence trail that judged it.

    `status` is never supplied by the reviewer and never inferred from the
    comment text — it is derived in `core/finding.py` from what the graph
    located and what the sandbox ran.
    """

    model_config = ConfigDict(frozen=True)

    finding: ReviewFinding
    contact_points: list[ContactPoint] = []
    selection: TestSelection | None = None
    report: TestReport | None = None
    status: FindingStatus
    why: str
