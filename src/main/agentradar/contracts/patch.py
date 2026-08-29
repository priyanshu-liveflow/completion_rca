"""A candidate fix and the red-to-green verification that gates a PR."""

from pydantic import BaseModel, ConfigDict

from .evidence import TestReport


class Patch(BaseModel):
    """Unified diff the agent authored against the sandbox working tree."""

    model_config = ConfigDict(frozen=True)

    diff: str
    files: list[str]
    rationale: str


class VerifyResult(BaseModel):
    """Before/after test reports for a patch.

    `verified` is the PR gate and must be `before.is_broken and after.is_green`.
    Do not use `before.failed > 0`: a collection error is broken with failed=0.
    """

    model_config = ConfigDict(frozen=True)

    patch: Patch
    before: TestReport
    after: TestReport
    verified: bool
