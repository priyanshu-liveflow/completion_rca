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

from ..core.diffnorm import normalize_hunk_headers
from .sandbox import _NODE_ID, RawRun, _validate

DEFAULT_TIMEOUT_S = 300

# The only environment variables a pytest run is given. CLAUDE.md is
# unconditional — "Secrets never enter the sandbox. Never pass an API key,
# token, or connection string into sandbox execution" — and `os.environ` on a
# developer machine holds exactly those. Copying it wholesale handed every
# key in `.env` to whatever the tests happen to execute, which is the same
# hole whether the code is trusted or not.
#
# An allowlist, not a denylist: a denylist has to predict every secret's name
# and silently leaks the one it did not think of.
_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SYSTEMROOT",  # Windows: subprocess creation fails without it
    "COMSPEC",
    "VIRTUAL_ENV",
    "PYTHONPATH",
)


def _safe_env() -> dict[str, str]:
    """The allowlisted subset of this process's environment, plus test hygiene."""
    env = {name: os.environ[name] for name in _ENV_ALLOWLIST if name in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


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
                env=_safe_env(),
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

    def _sources_for(self, diff: str) -> dict[str, str]:
        """Current contents of the files a diff names, for header normalisation."""
        sources: dict[str, str] = {}
        for line in diff.splitlines():
            if not line.startswith("+++ "):
                continue
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            if path == "/dev/null":
                continue
            candidate = self._workdir / path
            try:
                sources[path] = candidate.read_text()
            except OSError:
                # A new file, or one outside the checkout. Leaving it out means
                # its hunks pass through unchanged, which is the safe default.
                continue
        return sources

    def apply_patch(self, diff: str) -> RawRun:
        """Apply a unified diff to the local checkout via `git apply`.

        Hunk headers are normalised first. A model cannot know what line a
        function starts on — nothing in its prompt says — so it emits a bare
        `@@` or a guessed offset, and `git apply` rejects both. We do know,
        because the file is right here.
        """
        diff = normalize_hunk_headers(diff, self._sources_for(diff))
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
