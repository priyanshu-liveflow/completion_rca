"""Tests for the local test runner. Real subprocesses, no network."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.main.agentradar.adapters.localrunner import LocalRunner, _safe_env
from src.main.agentradar.adapters.sandbox import SandboxRunner


def test_satisfies_the_sandbox_protocol() -> None:
    """Consumers type-hint the Protocol; this is what makes the swap legal."""
    runner: SandboxRunner = LocalRunner(".")
    assert runner is not None


def test_rejects_a_workdir_that_does_not_exist() -> None:
    with pytest.raises(ValueError, match="workdir does not exist"):
        LocalRunner("/nonexistent/path/for/a/test")


def test_secrets_never_reach_the_test_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLAUDE.md: secrets never enter sandbox execution. Not even locally."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "bd-should-not-leak")
    monkeypatch.setenv("DAYTONA_API_KEY", "dt-should-not-leak")

    env = _safe_env()

    assert "OPENAI_API_KEY" not in env
    assert "BRIGHTDATA_API_KEY" not in env
    assert "DAYTONA_API_KEY" not in env
    assert "should-not-leak" not in "".join(env.values())


def test_allowlist_keeps_what_a_subprocess_actually_needs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    env = _safe_env()
    assert env["PATH"] == "/usr/bin"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"


def test_an_unknown_variable_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Allowlist, not denylist: anything unrecognised is excluded by default."""
    monkeypatch.setenv("SOME_NEW_TOKEN_WE_NEVER_HEARD_OF", "secret")
    assert "SOME_NEW_TOKEN_WE_NEVER_HEARD_OF" not in _safe_env()


def test_runs_a_passing_test_and_reports_success(tmp_path: Path) -> None:
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    result = LocalRunner(tmp_path).run_tests(["test_ok.py"])
    assert result.exit_code == 0
    assert "1 passed" in result.stdout


def test_runs_a_failing_test_and_reports_failure(tmp_path: Path) -> None:
    (tmp_path / "test_bad.py").write_text("def test_bad():\n    assert False\n")
    result = LocalRunner(tmp_path).run_tests(["test_bad.py"])
    assert result.exit_code == 1
    assert "1 failed" in result.stdout


def test_output_carries_per_case_lines_for_the_parser(tmp_path: Path) -> None:
    """`-rA` is required: `-q` drops the summary `parse_pytest` reads."""
    (tmp_path / "test_two.py").write_text(
        "def test_a():\n    assert True\n\n\ndef test_b():\n    assert True\n"
    )
    result = LocalRunner(tmp_path).run_tests(["test_two.py"])
    assert "PASSED" in result.stdout
    assert "2 passed" in result.stdout


def test_a_bad_node_id_is_refused_before_it_reaches_a_command_line() -> None:
    with pytest.raises(ValueError, match="unsafe pytest node id"):
        LocalRunner(".").run_tests(["tests/x.py; rm -rf /"])


def test_version_bumps_are_refused_rather_than_faked() -> None:
    """Mutating this machine's packages is the remote sandbox's job."""
    with pytest.raises(NotImplementedError, match="DaytonaRunner"):
        LocalRunner(".").set_package_version("mcp", "2.1.1")


def test_timeout_reports_the_sentinel_exit_code(tmp_path: Path) -> None:
    (tmp_path / "test_slow.py").write_text(
        "import time\n\n\ndef test_slow():\n    time.sleep(30)\n"
    )
    result = LocalRunner(tmp_path).run_tests(["test_slow.py"], timeout_s=1)
    assert result.exit_code == 124
    assert "timed out" in result.stderr


def test_workdir_is_resolved_and_exposed() -> None:
    runner = LocalRunner(".")
    assert runner.workdir == Path(os.getcwd()).resolve()
