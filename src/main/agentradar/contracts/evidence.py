"""Graph-selected tests and the reports produced by running them."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class TestSelection(BaseModel):
    """The tests chosen to exercise a set of contact points."""

    model_config = ConfigDict(frozen=True)

    tests: list[str]
    strategy: Literal["callers", "imports", "path", "manual"]
    reached_from: list[str]
    truncated: bool = False


class TestCase(BaseModel):
    """One pytest node and its outcome."""

    model_config = ConfigDict(frozen=True)

    node_id: str
    outcome: Literal["passed", "failed", "error", "skipped"]
    duration_s: float
    traceback: str | None


class TestReport(BaseModel):
    """Parsed result of one sandbox test run against a package version."""

    model_config = ConfigDict(frozen=True)

    id: str
    package: str
    version: str
    cases: list[TestCase]
    passed: int
    failed: int
    errors: int = 0
    duration_s: float
    raw_tail: str

    @property
    def is_green(self) -> bool:
        """True only when something ran and nothing failed or errored."""
        return (
            self.failed == 0
            and self.errors == 0
            and self.passed > 0
            and not any(case.outcome == "error" for case in self.cases)
        )

    @property
    def is_broken(self) -> bool:
        """True when the run proved damage.

        Failures or modules that would not import both count.
        """
        return (
            self.failed > 0
            or self.errors > 0
            or any(case.outcome == "error" for case in self.cases)
        )
