"""GitHub CLI adapter. The only module that shells out to `gh`.

Consumers type-hint :class:`CodeHost`, never :class:`GhClient` (spine rule 3).

Writes are irreversible. A non-zero exit, a timeout, or empty stdout raises a
typed error — never a silent empty string, and never a URL invented to look
like success. Copy of the error discipline in `adapters/brightdata.py`.

The PR tool is a separate concern from the CLI. :func:`pr_writer` returns the
``open_pr`` callable only when :func:`core.patch.can_act` is true, so a red
verification makes the write *unreachable*, not merely discouraged. Do not
reimplement that gate; it already keys on the computed ``VerifyResult.verified``
field (``before.is_broken and after.is_green``).
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from src.main.agentradar.contracts.mission import ActionPlan
from src.main.agentradar.contracts.patch import VerifyResult
from src.main.agentradar.core.patch import can_act
from src.main.agentradar.core.policy import PolicyError, pr_body

DEFAULT_TIMEOUT_S = 60.0
DEFAULT_BASE = "main"

_PR_TOOL = "github_pr"
_ISSUE_TOOL = "github_issue"


class GhError(Exception):
    """Typed failure from a `gh` invocation. Never swallowed into ''."""

    def __init__(
        self, message: str, *, exit_code: int | None = None, stderr: str = ""
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


class ActionDenied(Exception):
    """Human denied approval. No write was attempted."""


class GateClosed(Exception):
    """``can_act`` is false. The PR tool does not exist for this evidence."""


class CompletedCli(Protocol):
    """Subset of `subprocess.CompletedProcess` the adapter reads."""

    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    """Injectable process runner. Tests pass a fixture-backed fake."""

    def run(self, args: Sequence[str], *, timeout_s: float) -> CompletedCli: ...


class CodeHost(Protocol):
    """GitHub writes. The one irreversible thing this system does."""

    def open_pr(self, branch: str, title: str, body: str, diff: str) -> str: ...

    def open_issue(self, title: str, body: str) -> str: ...

    def changed_files(self, base: str, head: str) -> list[str]:
        """Files `head` changes relative to `base`, on the remote. Sorted."""
        ...


class SubprocessRunner:
    """Shell out to a binary. Timeouts and output capture are explicit."""

    def run(self, args: Sequence[str], *, timeout_s: float) -> CompletedCli:
        return subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )


class GhClient:
    """CodeHost that shells out to `gh`. Auth is whatever `gh auth` already has."""

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        binary: str = "gh",
    ) -> None:
        self._runner: CommandRunner = (
            runner if runner is not None else SubprocessRunner()
        )
        self._timeout_s = timeout_s
        self._binary = binary

    def open_pr(self, branch: str, title: str, body: str, diff: str) -> str:
        """Open a pull request from `branch`. Returns the PR URL.

        The working tree / remote branch is the caller's problem — this method
        does not `git apply`. `diff` is required so a body that somehow arrived
        without the patch still carries it.
        """
        stdout = self._invoke(
            [
                "pr",
                "create",
                "--head",
                branch,
                "--title",
                title,
                "--body",
                _body_with_diff(body, diff),
            ]
        )
        return _require_url(stdout, what="pull request")

    def open_issue(self, title: str, body: str) -> str:
        """File an issue. Returns the issue URL."""
        stdout = self._invoke(["issue", "create", "--title", title, "--body", body])
        return _require_url(stdout, what="issue")

    def changed_files(self, base: str, head: str) -> list[str]:
        """Files `head` changes relative to `base`, read from the remote.

        The *remote* branch, deliberately: `gh pr create --head <branch>`
        opens whatever GitHub has on that ref, not whatever is in the local
        working tree. Comparing anything else would check a different artifact
        from the one the PR ships.
        """
        stdout = self._invoke(
            [
                "api",
                f"repos/{{owner}}/{{repo}}/compare/{base}...{head}",
                "--paginate",
                "--jq",
                ".files[].filename",
            ]
        )
        return sorted({line.strip() for line in stdout.splitlines() if line.strip()})

    def _invoke(self, argv: list[str], *, timeout_s: float | None = None) -> str:
        limit = self._timeout_s if timeout_s is None else timeout_s
        args = [self._binary, *argv]
        try:
            proc = self._runner.run(args, timeout_s=limit)
        except subprocess.TimeoutExpired as exc:
            raise GhError(
                f"gh timed out after {limit:.0f}s: {' '.join(argv[:3])}",
                stderr=str(exc),
            ) from exc
        except FileNotFoundError as exc:
            raise GhError(
                f"{self._binary!r} not found on PATH",
                stderr=str(exc),
            ) from exc
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise GhError(
                f"gh exited {proc.returncode}: {err or ' '.join(argv[:3])}",
                exit_code=proc.returncode,
                stderr=proc.stderr,
            )
        return proc.stdout


def pr_writer(
    host: CodeHost, verify: VerifyResult | None
) -> Callable[[str, str, str, str], str] | None:
    """The ``open_pr`` callable, or ``None`` if the gate is closed.

    ``None`` means the PR tool is *unreachable* — there is nothing to call.
    A comment saying "only call this when tests are green" is not a gate.
    """
    if not can_act(verify):
        return None
    return host.open_pr


def reachable_tools(verify: VerifyResult | None) -> list[str]:
    """GitHub MCP tool names that exist for this evidence. Sorted."""
    names = [_ISSUE_TOOL]
    if can_act(verify):
        names.append(_PR_TOOL)
    return sorted(names)


def execute(
    host: CodeHost,
    plan: ActionPlan,
    *,
    approved: bool,
    verify: VerifyResult | None = None,
) -> str:
    """Perform a GitHub write, or raise without calling `host`.

    Deny (``requires_approval and not approved``) records zero writes.
    A closed gate makes ``github_pr`` unreachable even after approval.
    """
    if plan.requires_approval and not approved:
        raise ActionDenied("approval denied; no GitHub write was attempted")

    if plan.target == _PR_TOOL:
        writer = pr_writer(host, verify)
        if writer is None or verify is None:
            raise GateClosed(
                "github_pr is unreachable without a proven red-to-green transition"
            )
        supplied = _optional_str(plan.payload, "diff")
        if supplied and supplied != verify.patch.diff:
            raise GateClosed("github_pr diff does not match the verified patch")
        branch = _need(plan.payload, "branch")
        title = _need(plan.payload, "title")
        base = _optional_str(plan.payload, "base") or DEFAULT_BASE
        _assert_branch_carries_patch(host, base, branch, verify)
        return writer(branch, title, pr_body(plan.summary, verify), verify.patch.diff)

    if plan.target == _ISSUE_TOOL:
        return host.open_issue(
            _need(plan.payload, "title"), _need(plan.payload, "body")
        )

    raise PolicyError(f"no GitHub write for target {plan.target!r}")


def _assert_branch_carries_patch(
    host: CodeHost, base: str, branch: str, verify: VerifyResult
) -> None:
    """Refuse to open a PR from a branch that is not the verified patch.

    ``can_act`` proves that *a* patch went red to green. It says nothing about
    what is on the branch ``gh pr create --head`` will ship: the diff argument
    is body text, while the commits come from the ref. Without this check a
    caller can verify patch A and open a PR from branch B, and the PR renders
    A as its evidence while containing B — the one outcome the whole gate
    exists to prevent, reached without forging anything.

    Compared by file set rather than by diff text. The verified patch is what
    the agent wrote against the sandbox tree; the branch has been committed and
    pushed, so whitespace, context lines and hunk offsets all legitimately
    differ. Which files are touched does not.
    """
    declared = sorted(set(verify.patch.files))
    if not declared:
        raise GateClosed(
            "github_pr: the verified patch names no files, so no branch can match it"
        )
    actual = sorted(set(host.changed_files(base, branch)))
    if actual != declared:
        raise GateClosed(
            f"github_pr: branch {branch!r} does not carry the verified patch — "
            f"it changes {actual or ['nothing']} against {base!r}, "
            f"but the proven patch touches {declared}"
        )


def _need(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise GhError(f"action payload missing {key!r}")
    return value


def _optional_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def _body_with_diff(body: str, diff: str) -> str:
    text = diff.strip()
    if not text or text in body:
        return body
    return f"{body.rstrip()}\n\n```diff\n{text}\n```\n"


def _require_url(stdout: str, *, what: str) -> str:
    """Return the first URL in `stdout`, or raise. Never returns ''."""
    text = stdout.strip()
    if not text:
        raise GhError(f"gh returned empty stdout creating a {what}")
    for line in text.splitlines():
        candidate = line.strip().rstrip(").,")
        if candidate.startswith("https://") or candidate.startswith("http://"):
            return candidate
    raise GhError(f"gh returned no {what} URL")
