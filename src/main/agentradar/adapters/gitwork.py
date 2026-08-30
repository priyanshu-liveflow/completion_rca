"""Git working-tree writes. The only module that runs `git` against a checkout.

`adapters/github.py` talks to GitHub through `gh` and deliberately does not
touch the working tree — its docstring says the branch is the caller's
problem. This is that caller. Split rather than merged because they fail in
different ways and at different times: a push that is rejected is recoverable
and local, while an opened pull request is not.

Consumers type-hint :class:`GitWorkspace`, never :class:`LocalGit`
(spine rule 3).
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

__all__ = ["GitError", "GitWorkspace", "LocalGit"]

DEFAULT_TIMEOUT_S = 120.0


class GitError(Exception):
    """A `git` invocation failed. Never swallowed into a False return."""

    def __init__(self, message: str, *, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


class GitWorkspace(Protocol):
    """Publish a set of already-written files as a branch on the remote."""

    def publish(self, branch: str, message: str, files: Sequence[str]) -> str: ...

    def restore(self, files: Sequence[str]) -> None: ...


class LocalGit:
    """`GitWorkspace` over a real checkout, by shelling out to `git`.

    The patch is expected to be applied in the working tree already — that is
    what `SandboxRunner.apply_patch` did, and re-applying it here would either
    conflict or double it.
    """

    def __init__(
        self,
        workdir: str | Path,
        *,
        remote: str = "origin",
        base: str = "main",
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._workdir = Path(workdir)
        self._remote = remote
        self._base = base
        self._timeout_s = timeout_s

    def publish(self, branch: str, message: str, files: Sequence[str]) -> str:
        """Branch from the current HEAD, commit exactly `files`, push. Returns `branch`.

        Only the named files are staged. The blast radius the graph derived is
        what the gate checked and what `_assert_branch_carries_patch` will
        compare the remote against, so staging anything else — an editor
        artifact, an unrelated edit already in the tree — would make the
        pushed branch disagree with the proven patch and be refused one step
        later, after the push.
        """
        if not files:
            raise GitError("refusing to publish a branch with no files")
        # `-B` so a re-run of the same finding reuses its branch instead of
        # failing on "already exists". The branch is derived from the finding,
        # so the same name means the same repair.
        self._git(["checkout", "-B", branch])
        self._git(["add", "--", *files])
        staged = self._git(["diff", "--cached", "--name-only"]).split()
        if not staged:
            raise GitError(
                f"nothing staged for {branch!r} — the patch is not in the working tree"
            )
        self._git(["commit", "-m", message])
        self._git(["push", "--force-with-lease", "-u", self._remote, branch])
        return branch

    def restore(self, files: Sequence[str]) -> None:
        """Put `files` back to HEAD. Used to leave the checkout as it was found."""
        if files:
            self._git(["checkout", "--", *files])

    def current_branch(self) -> str:
        """The checked-out branch name."""
        return self._git(["rev-parse", "--abbrev-ref", "HEAD"]).strip()

    def _git(self, argv: list[str]) -> str:
        try:
            proc = subprocess.run(  # noqa: S603
                ["git", *argv],
                cwd=self._workdir,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitError(
                f"git timed out: {' '.join(argv[:2])}", stderr=str(exc)
            ) from exc
        except FileNotFoundError as exc:
            raise GitError("'git' not found on PATH", stderr=str(exc)) from exc
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise GitError(
                f"git {' '.join(argv[:2])} exited {proc.returncode}: {err}",
                stderr=proc.stderr,
            )
        return proc.stdout
