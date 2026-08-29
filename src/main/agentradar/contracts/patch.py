"""A candidate fix and the red-to-green verification that gates a PR."""

from pydantic import BaseModel, ConfigDict, computed_field

from .evidence import TestReport


class Patch(BaseModel):
    """Unified diff the agent authored against the sandbox working tree."""

    model_config = ConfigDict(frozen=True)

    diff: str
    files: list[str]
    rationale: str


class VerifyResult(BaseModel):
    """Before/after test reports for a patch.

    `verified` is the PR gate and is DERIVED, never supplied. It must be
    `before.is_broken and after.is_green`; do not use `before.failed > 0`,
    because a collection error is broken with failed=0.

    It is a `computed_field` rather than a plain `bool` on purpose. The one
    caller that reaches this model with untrusted input is
    `mcp/store_server.py::save_verify`, which does
    `VerifyResult.model_validate(result)` on a dict the *agent* wrote. If
    `verified` were an ordinary field, an agent could post
    `{"verified": true}` beside a red `after` report and `core.patch.can_act`
    would open the PR on evidence that never went green. Deriving it means the
    gate is computed from the two test reports every time it is read, whether
    the model came from `build_verify_result`, from agent JSON, or from a row
    reloaded out of SQLite.
    """

    model_config = ConfigDict(frozen=True)

    patch: Patch
    before: TestReport
    after: TestReport

    @computed_field  # type: ignore[prop-decorator]
    @property
    def verified(self) -> bool:
        """True only for a proven red-to-green transition."""
        return self.before.is_broken and self.after.is_green
