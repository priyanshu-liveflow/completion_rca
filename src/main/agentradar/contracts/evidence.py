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
    exit_code: int | None = None
    """pytest's own exit status, when the runner reported one.

    Kept so a caller can tell *the tests failed* from *the run never happened*.
    Both leave `passed == 0`, and only this field separates them.
    """

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
    def is_execution_failure(self) -> bool:
        """True when pytest itself failed, rather than the code under test.

        pytest exits 0 when everything passed and 1 when tests failed; every
        other status is the harness reporting that it could not do its job —
        2 interrupted, 3 internal error, 4 usage error, 5 nothing collected,
        and 124 for the timeout the runners synthesise.

        This matters because `parse_pytest` turns an unexplained nonzero exit
        into `errors = 1` so nothing silently reads as green. That is right
        for a dependency mission, where an import-time explosion *is* the
        damage. It is wrong as evidence about a specific claim: a plugin
        crash or a bad node id says nothing about whether the reviewer was
        correct, and must not be allowed to confirm anything.
        """
        return self.exit_code is not None and self.exit_code not in (0, 1)

    @property
    def ran_nothing(self) -> bool:
        """True when no test actually executed — all skipped, or none collected.

        A run with no failures is not evidence of correctness if nothing ran.
        """
        return self.passed == 0 and self.failed == 0 and self.errors == 0

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
