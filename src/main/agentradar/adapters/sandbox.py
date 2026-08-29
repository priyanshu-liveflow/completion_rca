"""Run commands in a disposable sandbox.

The harness holds credentials; the sandbox gets code, files and a shell. No
API key, token or connection string is ever passed into sandbox execution —
this module never reads ``os.environ`` and never passes ``env`` to ``exec``.
``tests/agentradar/test_sandbox_adapter.py`` asserts both properties against
this file's AST, so the guarantee survives edits.

The demo path is Daytona. Measured at H0 with ``sandbox/timing_probe.py``:
cold create+clone+install+green is 10.1s, the live bump/red/patch/green cycle
is 6.1s on a prewarmed sandbox. :class:`DaytonaRunner` reuses one prewarmed
sandbox across every call so the demo pays the 6.1s, not the 10.1s.
"""

from __future__ import annotations

import re
import shlex
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = [
    "DEFAULT_WORKDIR",
    "DaytonaRunner",
    "RawRun",
    "SandboxRunner",
]

#: Where the demo repo is cloned inside the sandbox.
DEFAULT_WORKDIR = "/home/daytona/repo"

#: Where a patch is uploaded before ``git apply`` reads it.
_PATCH_PATH = "/tmp/agentradar.patch"

# Package names, versions and pytest node ids are interpolated into a shell
# command. Anything outside these shapes is rejected rather than quoted, so a
# malformed value fails loudly instead of running.
_PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+!_-]*$")
_DOTTED = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_NODE_ID = re.compile(r"^[A-Za-z0-9_./\-\[\]:=+ ]+$")


@dataclass(frozen=True)
class RawRun:
    """One command's result. Unparsed on purpose — ``core.testreport`` reads it."""

    exit_code: int
    stdout: str
    stderr: str
    duration_s: float

    @property
    def ok(self) -> bool:
        """True when the command exited cleanly."""
        return self.exit_code == 0


@runtime_checkable
class SandboxRunner(Protocol):
    """Everything the repro and patch loops need from an execution environment."""

    def run_tests(self, node_ids: list[str], *, timeout_s: int = 180) -> RawRun:
        """Run the given pytest node ids; empty means the whole suite."""
        ...

    def set_package_version(self, package: str, version: str) -> RawRun:
        """Pin ``package`` to ``version``. This is what turns the suite red."""
        ...

    def apply_patch(self, diff: str) -> RawRun:
        """Apply a unified diff to the checkout."""
        ...

    def import_check(self, symbol: str, package: str) -> RawRun:
        """Fallback when no test covers a contact point: is the symbol still there?"""
        ...


def _validate(value: str, pattern: re.Pattern[str], what: str) -> str:
    if not pattern.match(value):
        raise ValueError(f"unsafe {what}: {value!r}")
    return value


class DaytonaRunner:
    """Drive one prewarmed Daytona sandbox.

    Construct with an already-connected sandbox handle so the adapter stays
    testable without the Daytona SDK installed; :meth:`connect` is the
    convenience path that imports the SDK and attaches to a sandbox id.
    """

    def __init__(self, sandbox: object, *, workdir: str = DEFAULT_WORKDIR) -> None:
        self._sandbox = sandbox
        self._workdir = workdir

    @classmethod
    def connect(
        cls, api_key: str, sandbox_id: str, *, workdir: str = DEFAULT_WORKDIR
    ) -> DaytonaRunner:
        """Attach to a prewarmed sandbox by id.

        ``api_key`` is passed in by the harness rather than read from the
        environment here, so this module has no path to a secret at all.
        """
        from daytona import Daytona, DaytonaConfig

        client = Daytona(DaytonaConfig(api_key=api_key))
        return cls(client.get(sandbox_id), workdir=workdir)

    # -- the Protocol ----------------------------------------------------

    def run_tests(self, node_ids: list[str], *, timeout_s: int = 180) -> RawRun:
        """Run the graph-selected tests. No ids means the whole suite."""
        for node_id in node_ids:
            _validate(node_id, _NODE_ID, "pytest node id")
        targets = " ".join(shlex.quote(node_id) for node_id in node_ids)
        command = "python -m pytest -v --durations=10 -rA"
        return self._exec(f"{command} {targets}".strip(), timeout_s=timeout_s)

    def set_package_version(self, package: str, version: str) -> RawRun:
        """Install ``package==version``, the bump that reproduces the break."""
        _validate(package, _PACKAGE, "package name")
        _validate(version, _VERSION, "version")
        spec = shlex.quote(f"{package}=={version}")
        return self._exec(
            f"pip install -q --break-system-packages {spec}", timeout_s=300
        )

    def apply_patch(self, diff: str) -> RawRun:
        """Upload the diff and ``git apply`` it.

        Uploaded as a file rather than echoed through the shell so that diff
        content can never be read as shell syntax.
        """
        upload = getattr(self._sandbox, "fs", None)
        if upload is None:
            raise RuntimeError("sandbox handle exposes no filesystem")
        upload.upload_file(diff.encode("utf-8"), _PATCH_PATH)
        return self._exec(
            f"git apply --verbose {shlex.quote(_PATCH_PATH)}", timeout_s=60
        )

    def import_check(self, symbol: str, package: str) -> RawRun:
        """Exit 0 if ``symbol`` still resolves under ``package``, 1 if it moved.

        Used when the graph finds a contact point that no test covers: the
        honest answer there is UNCOVERED, and this is the cheapest evidence
        that distinguishes "still fine" from "gone".

        ``symbol`` may be dotted and may name submodules. The probe imports
        the longest importable prefix before falling back to attribute
        lookup, because a submodule is not an attribute of its package until
        something imports it — a plain ``getattr`` walk would call a symbol
        that is present "gone".
        """
        _validate(symbol, _DOTTED, "symbol")
        _validate(package, _DOTTED, "package")
        probe = "\n".join(
            [
                "import importlib, sys",
                f'parts = "{package}.{symbol}".split(".")',
                "obj, reached = None, 0",
                "for stop in range(len(parts), 0, -1):",
                "    try:",
                '        obj = importlib.import_module(".".join(parts[:stop]))',
                "        reached = stop",
                "        break",
                "    except ImportError:",
                "        continue",
                "if obj is None:",
                "    sys.exit(1)",
                "for part in parts[reached:]:",
                "    obj = getattr(obj, part, None)",
                "    if obj is None:",
                "        sys.exit(1)",
                "sys.exit(0)",
            ]
        )
        return self._exec(f"python -c {shlex.quote(probe)}", timeout_s=60)

    # -- plumbing --------------------------------------------------------

    def _exec(self, command: str, *, timeout_s: int) -> RawRun:
        """Run one command in the workdir and time it.

        ``env`` is deliberately never passed — see the module docstring.
        """
        process = getattr(self._sandbox, "process", None)
        if process is None:
            raise RuntimeError("sandbox handle exposes no process API")
        started = time.monotonic()
        result = process.exec(command, cwd=self._workdir, timeout=timeout_s)
        elapsed = time.monotonic() - started
        return RawRun(
            exit_code=int(getattr(result, "exit_code", 1)),
            stdout=str(getattr(result, "result", "") or ""),
            stderr=str(getattr(result, "stderr", "") or ""),
            duration_s=elapsed,
        )
