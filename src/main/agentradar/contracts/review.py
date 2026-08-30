"""A persisted review verification, with whatever repair it led to.

A run that only printed to a terminal did not happen, for the same reason a
mission that only exists in a chat transcript did not happen: nobody can go
back and look at it. This is the record the dashboard renders and the PR
comment is generated from.
"""

from pydantic import BaseModel, ConfigDict

from .finding import FindingStatus, FindingVerdict


class RepairRecord(BaseModel):
    """What was attempted for one confirmed finding, and whether it held."""

    model_config = ConfigDict(frozen=True)

    diff: str
    files: list[str]
    applied: bool
    proven: bool
    """`can_act` — a real red-to-green. Never the model's own claim."""

    before_failed: int
    after_passed: int
    reason: str
    pr_url: str | None = None


class ReviewEntry(BaseModel):
    """One finding: what was claimed, what was proven, what was repaired."""

    model_config = ConfigDict(frozen=True)

    verdict: FindingVerdict
    repair: RepairRecord | None = None


class ReviewRun(BaseModel):
    """Every finding on one pull request, verified in one pass."""

    model_config = ConfigDict(frozen=True)

    id: str
    repo: str
    pr: int
    created_at: str
    repo_key: str
    entries: list[ReviewEntry] = []

    @property
    def counts(self) -> dict[str, int]:
        """Verdict tally, with every status present even at zero."""
        counts = {status.value: 0 for status in FindingStatus}
        for entry in self.entries:
            counts[entry.verdict.status.value] += 1
        return counts

    @property
    def proven_repairs(self) -> int:
        """Repairs that turned a failing test green. The number that matters."""
        return sum(1 for e in self.entries if e.repair and e.repair.proven)
