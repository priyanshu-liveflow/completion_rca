"""Run the selected tests in a local checkout, behind the sandbox Protocol.

Consumers type-hint :class:`sandbox.SandboxRunner`, never this class
(spine rule 3) — which is the entire point. ``DaytonaRunner`` proves a
*third-party* repo breaks under a new dependency version, and it must be
remote for that: we are not installing an untrusted release into our own
interpreter. Verifying a review finding on *this* repo is the opposite
situation. The code is already on this machine, already trusted, and already
has its dependencies installed, so a cloud round trip buys nothing and costs
a CPU quota, a network, and about forty seconds per run.

Same Protocol, so `core/` cannot tell the two apart. The swap is a
constructor argument, not a rewrite.

Node ids are validated against ``sandbox._NODE_ID`` before they reach a
command line, and the command is a fixed argv list — never a shell string —
so a finding whose file path contains a semicolon cannot become an
injection. No secrets are passed in either direction.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from .sandbox import _NODE_ID, RawRun, _validate

DEFAULT_TIMEOUT_S = 300

__all__ = ["LocalRunner"]


class LocalRunner:
    """SandboxRunner that shells out to pytest in a local working directory."""

    def __init__(
        self,
        workdir: str | Path,
        *,
        pytest_cmd: tuple[str, ...] | None = None,
    ) -> None:
        self._workdir = Path(workdir).resolve()
        if not self._workdir.is_dir():
            raise ValueError(f"workdir does not exist: {self._workdir}")
        # `sys.executable`, not "python". The interpreter running this process
        # is the one with pytest and the project's dependencies installed; a
        # bare "python" resolves against PATH and can easily be a different,
        # emptier environment — which fails as "0 tests collected" rather than
        # as a missing interpreter, and so reads like a real result.
        self._pytest = tuple(pytest_cmd or (sys.executable, "-m", "pytest"))

    @property
    def workdir(self) -> Path:
        """Where tests run. Surfaced so a caller can show it to a human."""
        return self._workdir

    def _run(self, args: list[str], timeout_s: int) -> RawRun:
        started = time.monotonic()
        try:
            proc = subprocess.run(
                args,
                cwd=self._workdir,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        except subprocess.TimeoutExpired as exc:
            return RawRun(
                exit_code=124,
                stdout=exc.stdout or "" if isinstance(exc.stdout, str) else "",
                stderr=f"timed out after {timeout_s}s",
                duration_s=time.monotonic() - started,
            )
        return RawRun(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_s=time.monotonic() - started,
        )

    def run_tests(
        self, node_ids: list[str], *, timeout_s: int = DEFAULT_TIMEOUT_S
    ) -> RawRun:
        """Run the graph-selected tests. No ids means the whole suite."""
        for node_id in node_ids:
            _validate(node_id, _NODE_ID, "pytest node id")
        # `-rA` prints a short-summary line per test, which is what
        # `core.testreport.parse_pytest` reads to build per-case outcomes.
        # `-q` suppresses the decorated totals line the parser needs, and the
        # failure mode is a silent `passed=0` on a run that actually passed.
        return self._run([*self._pytest, "-rA", *node_ids], timeout_s)

    def set_package_version(self, package: str, version: str) -> RawRun:
        """Not supported locally, and refused rather than faked.

        Installing a dependency release into the interpreter running this
        process would mutate the developer's own environment. That is what
        the remote sandbox is for; returning a fake success here would let a
        caller believe a version bump happened when it did not.
        """
        raise NotImplementedError(
            "LocalRunner will not mutate this machine's installed packages — "
            "use DaytonaRunner to test a dependency version bump"
        )

    def apply_patch(self, diff: str) -> RawRun:
        """Apply a unified diff to the local checkout via `git apply`."""
        started = time.monotonic()
        try:
            proc = subprocess.run(
                ["git", "apply", "-"],
                cwd=self._workdir,
                input=diff,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return RawRun(124, "", "git apply timed out", time.monotonic() - started)
        return RawRun(
            proc.returncode, proc.stdout, proc.stderr, time.monotonic() - started
        )

    def import_check(self, symbol: str, package: str) -> RawRun:
        """Is `symbol` still importable from `package` in this environment?"""
        _validate(symbol, _NODE_ID, "symbol")
        _validate(package, _NODE_ID, "package")
        return self._run(
            ["python", "-c", f"from {package} import {symbol}"],
            timeout_s=60,
        )
