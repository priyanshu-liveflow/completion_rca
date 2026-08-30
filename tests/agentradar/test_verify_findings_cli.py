"""Tests for the verifier CLI.

Imported normally, from `agentradar.cli.verify_findings`, which is why this
file exists at all: the verifier reported findings against the CLI as
`uncovered` while it lived in `scripts/`, because `select_tests` walks import
edges and a script reached only by path has none. A real `import` is what
makes the coverage visible to the graph, not just true in fact.

`importlib.reload` is used where a test changes the environment, since the
argument defaults are read from `os.environ` at module import.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

import pytest

from src.main.agentradar.cli import verify_findings as cli_module


def _load() -> ModuleType:
    """Re-import the CLI so `os.environ` is read again for argument defaults."""
    return importlib.reload(cli_module)


@pytest.fixture
def cli() -> ModuleType:
    return _load()


def test_pr_is_required(cli: ModuleType) -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


def test_defaults_are_sane(cli: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AGENTRADAR_REPO",
        "AGENTRADAR_REPO_KEY",
        "AGENTRADAR_SOURCE_ROOT",
        "AGENTRADAR_TEST_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)
    args = _load().build_parser().parse_args(["--pr", "20"])
    assert args.pr == 20
    assert "/" in args.repo
    assert args.test_root == "tests"
    # Empty by design: this repo's own tests import `src.main.agentradar...`
    # with the `src.` still on the front, so stripping a source root breaks
    # import matching.
    assert args.source_root == ""
    assert args.no_run is False
    assert args.fix is False


def test_every_connection_is_environment_overridable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The point of the env vars: run on a machine that is not this one."""
    monkeypatch.setenv("AGENTRADAR_REPO", "acme/widgets")
    monkeypatch.setenv("AGENTRADAR_REPO_KEY", "widgets")
    monkeypatch.setenv("AGENTRADAR_SOURCE_ROOT", "lib")
    monkeypatch.setenv("AGENTRADAR_TEST_ROOT", "spec")
    monkeypatch.setenv("AGENTRADAR_WORKDIR", "/tmp/widgets")

    args = _load().build_parser().parse_args(["--pr", "3"])

    assert args.repo == "acme/widgets"
    assert args.repo_key == "widgets"
    assert args.source_root == "lib"
    assert args.test_root == "spec"
    assert args.workdir == "/tmp/widgets"


def test_flags_override_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTRADAR_REPO", "acme/widgets")
    args = _load().build_parser().parse_args(["--pr", "3", "--repo", "other/repo"])
    assert args.repo == "other/repo"


def test_reviewer_is_repeatable(cli: ModuleType) -> None:
    args = cli.build_parser().parse_args(
        ["--pr", "1", "--reviewer", "a[bot]", "--reviewer", "b[bot]"]
    )
    assert args.reviewer == ["a[bot]", "b[bot]"]


def test_narration_goes_to_stderr_so_markdown_can_be_piped(
    cli: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--markdown | gh pr comment --body-file -` must not carry the log."""
    cli.say("progress line")
    captured = capsys.readouterr()
    assert "progress line" in captured.err
    assert captured.out == ""


def test_a_clean_review_exits_zero_without_touching_the_graph(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No findings is a clean bill of health, not a failure."""

    class _NoFindings:
        def __init__(self, *a: object, **k: object) -> None:
            pass

        def findings(self, pr: int) -> list[object]:
            return []

    def _explode(*a: object, **k: object) -> None:
        raise AssertionError("the graph must not be opened when there is nothing to do")

    monkeypatch.setattr(cli, "GhReviewSource", _NoFindings)
    monkeypatch.setattr(cli, "FalkorCodeGraph", _explode)

    assert cli.main(["--pr", "20", "--no-save"]) == 0


def test_workdir_defaults_to_the_repo_root(cli: ModuleType) -> None:
    """Regression: the default was `__file__.parent.parent`.

    That was the repo root while the CLI lived in `scripts/` and silently
    became `src/main/agentradar` when it moved into the package. pytest then
    ran in a directory with no `tests/`, exited 4 for a usage error, and every
    verdict turned `inconclusive` — a whole run of nothing, from a path
    expression that still looked reasonable.
    """
    root = Path(cli.build_parser().parse_args(["--pr", "1"]).workdir)
    assert (root / "pyproject.toml").is_file()
    assert (root / "tests" / "agentradar").is_dir()
