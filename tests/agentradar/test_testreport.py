"""Parser tests. No sandbox, no subprocess — only the captured fixtures.

The fixtures were captured by hand at H0 from the real demo repo, which is why
these tests can prove the red case is honest without any runner involved.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.main.agentradar.core.testreport import RAW_TAIL_CHARS, parse_pytest, strip_ansi

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

RED_MODULES = {"tests/test_make_intervals_request.py", "tests/test_server.py"}

# A parametrised node id: brackets and dots must survive the parser intact.
PARAMETRISED_ID = (
    "tests/test_value.py::test_pace_units_deserialise_from_api_string"
    "[MINS_KM-ValueUnits.MINS_KM]"
)


def _fixture(name: str) -> str:
    return (FIXTURES / f"pytest_output_{name}.txt").read_text(encoding="utf-8")


@pytest.fixture
def red() -> str:
    return _fixture("red")


@pytest.fixture
def green() -> str:
    return _fixture("green")


# -- the red case: a collection error, not a test failure --------------------


def test_collection_error_is_not_green(red: str) -> None:
    """The failure mode this parser exists to prevent.

    Zero per-test node ids exist because the modules never imported. A parser
    that only counts ``FAILED`` lines calls this green.
    """
    report = parse_pytest(red, "mcp", "2.1.1", "r_red")

    assert report.is_green is False
    assert report.is_broken is True
    assert report.errors == 2
    assert report.passed == 0
    assert report.failed == 0


def test_collection_error_names_the_modules(red: str) -> None:
    report = parse_pytest(red, "mcp", "2.1.1", "r_red")

    assert {case.node_id for case in report.cases} == RED_MODULES
    assert all(case.outcome == "error" for case in report.cases)


def test_collection_error_captures_the_traceback(red: str) -> None:
    report = parse_pytest(red, "mcp", "2.1.1", "r_red")

    for case in report.cases:
        assert case.traceback is not None
        assert "ModuleNotFoundError" in case.traceback
        assert "mcp.server.fastmcp" in case.traceback


def test_red_carries_the_wall_time_pytest_printed(red: str) -> None:
    assert parse_pytest(red, "mcp", "2.1.1", "r_red").duration_s == pytest.approx(0.37)


# -- the green case ----------------------------------------------------------


def test_green_run_is_green(green: str) -> None:
    report = parse_pytest(green, "mcp", "1.29.1", "r_green")

    assert report.is_green is True
    assert report.is_broken is False
    assert report.passed == 61
    assert report.failed == 0
    assert report.errors == 0
    assert len(report.cases) == 61


def test_green_node_ids_are_pytest_node_ids(green: str) -> None:
    report = parse_pytest(green, "mcp", "1.29.1", "r_green")
    node_ids = {case.node_id for case in report.cases}

    assert "tests/test_server.py::test_get_activities" in node_ids
    assert PARAMETRISED_ID in node_ids
    assert all("::" in node_id for node_id in node_ids)


def test_durations_attach_to_their_node(green: str) -> None:
    report = parse_pytest(green, "mcp", "1.29.1", "r_green")
    timed = {case.node_id: case.duration_s for case in report.cases if case.duration_s}

    assert timed == {"tests/test_server.py::test_get_activities": pytest.approx(0.24)}


def test_passing_cases_carry_no_traceback(green: str) -> None:
    report = parse_pytest(green, "mcp", "1.29.1", "r_green")

    assert all(case.traceback is None for case in report.cases)


# -- the repro is honest -----------------------------------------------------


def test_repro_is_honest(red: str, green: str) -> None:
    """A repro that fails either way proves nothing.

    Every module that errors under the bumped version must have tests that
    pass under the original one. Without this, "red" could just mean the
    suite was broken all along.
    """
    broken = parse_pytest(red, "mcp", "2.1.1", "r_red")
    baseline = parse_pytest(green, "mcp", "1.29.1", "r_green")

    assert broken.is_broken and baseline.is_green

    errored_modules = {
        case.node_id.split("::")[0] for case in broken.cases if case.outcome == "error"
    }
    passing_modules = {
        case.node_id.split("::")[0]
        for case in baseline.cases
        if case.outcome == "passed"
    }

    assert errored_modules == RED_MODULES
    assert errored_modules <= passing_modules


# -- robustness --------------------------------------------------------------


def test_empty_output_is_not_green() -> None:
    report = parse_pytest("", "mcp", "2.1.1", "r_empty")

    assert report.cases == []
    assert report.passed == 0
    assert report.is_green is False
    assert report.is_broken is False


def test_counts_line_alone_is_enough() -> None:
    """Without ``-rA`` there is no summary block, only the totals rule."""
    stdout = (
        "===== test session starts =====\n"
        "collected 3 items\n\n"
        "tests/test_a.py ..F   [100%]\n\n"
        "===== 1 failed, 2 passed in 1.25s =====\n"
    )
    report = parse_pytest(stdout, "mcp", "2.1.1", "r_counts")

    assert report.cases == []
    assert report.passed == 2
    assert report.failed == 1
    assert report.duration_s == pytest.approx(1.25)
    assert report.is_broken is True


def test_interrupted_line_alone_still_reports_damage() -> None:
    """Collection can abort before any summary block is written."""
    stdout = (
        "collected 0 items / 3 errors\n"
        "!!!!! Interrupted: 3 errors during collection !!!!!\n"
    )
    report = parse_pytest(stdout, "mcp", "2.1.1", "r_interrupt")

    assert report.errors == 3
    assert report.is_green is False
    assert report.is_broken is True


def test_failed_case_keeps_its_node_id_and_traceback() -> None:
    stdout = (
        "===== FAILURES =====\n"
        "_____ test_adds _____\n"
        "    assert add(1, 2) == 4\n"
        "E   assert 3 == 4\n"
        "===== short test summary info =====\n"
        "FAILED tests/test_math.py::test_adds - assert 3 == 4\n"
        "===== 1 failed in 0.01s =====\n"
    )
    report = parse_pytest(stdout, "mcp", "2.1.1", "r_fail")

    (case,) = report.cases
    assert case.node_id == "tests/test_math.py::test_adds"
    assert case.outcome == "failed"
    assert case.traceback is not None
    assert "assert 3 == 4" in case.traceback


def test_skipped_does_not_count_as_passed() -> None:
    stdout = (
        "===== short test summary info =====\n"
        "SKIPPED [1] tests/test_net.py:12: needs network\n"
        "===== 1 skipped in 0.01s =====\n"
    )
    report = parse_pytest(stdout, "mcp", "2.1.1", "r_skip")

    (case,) = report.cases
    assert case.outcome == "skipped"
    # Not `tests/test_net.py:12: needs network` — that selects nothing.
    assert case.node_id == "tests/test_net.py"
    assert ":" not in case.node_id
    assert "needs network" not in case.node_id
    assert report.passed == 0
    assert report.is_green is False


# -- a nonzero exit is never green (Qodo #1) ---------------------------------


def test_nonzero_exit_is_not_green_even_when_output_looks_clean() -> None:
    """The gate's second escape hatch, after collection errors.

    pytest can exit nonzero with nothing but passes in its output — an internal
    error, a plugin crash, ``-x`` cutting the run short. Green here would let a
    patch verify on a run that never finished.
    """
    stdout = (
        "===== short test summary info =====\n"
        "PASSED tests/test_a.py::test_one\n"
        "PASSED tests/test_a.py::test_two\n"
        "===== 2 passed in 0.10s =====\n"
    )

    clean = parse_pytest(stdout, "mcp", "1.29.1", "r_ok", exit_code=0)
    assert clean.is_green is True

    crashed = parse_pytest(stdout, "mcp", "1.29.1", "r_crash", exit_code=3)
    assert crashed.is_green is False
    assert crashed.is_broken is True
    assert crashed.errors == 1
    assert crashed.passed == 2


def test_exit_code_does_not_inflate_explained_damage() -> None:
    """When the output already accounts for the failure, do not add to it."""
    stdout = (
        "===== short test summary info =====\n"
        "FAILED tests/test_a.py::test_one\n"
        "===== 1 failed in 0.10s =====\n"
    )
    report = parse_pytest(stdout, "mcp", "2.1.1", "r_fail", exit_code=1)

    assert report.failed == 1
    assert report.errors == 0


def test_exit_code_is_optional(red: str) -> None:
    """Callers without an exit status still get the collection-error verdict."""
    assert parse_pytest(red, "mcp", "2.1.1", "r_red").is_broken is True


# -- mixed runs (Qodo #2) ----------------------------------------------------


def test_mixed_run_counts_passes_from_the_totals_line() -> None:
    """With ``-rf`` the summary lists failures only; the totals still know."""
    stdout = (
        "===== short test summary info =====\n"
        "FAILED tests/test_a.py::test_three\n"
        "===== 1 failed, 2 passed in 0.30s =====\n"
    )
    report = parse_pytest(stdout, "mcp", "2.1.1", "r_mixed", exit_code=1)

    assert report.passed == 2
    assert report.failed == 1
    assert len(report.cases) == 1
    assert report.is_green is False
    assert report.is_broken is True


def test_full_summary_still_counts_its_own_cases(green: str) -> None:
    """Reconciling with the totals line must not double-count under ``-rA``."""
    assert parse_pytest(green, "mcp", "1.29.1", "r_green").passed == 61


def test_caller_measured_duration_wins() -> None:
    stdout = "===== 1 passed in 0.50s =====\n"

    assert (
        parse_pytest(stdout, "mcp", "1.29.1", "r_d", duration_s=6.1).duration_s == 6.1
    )
    assert parse_pytest(stdout, "mcp", "1.29.1", "r_d").duration_s == pytest.approx(
        0.50
    )


def test_skip_with_a_real_node_id_is_left_alone() -> None:
    """Only the ``path:line: reason`` form needs rewriting."""
    stdout = (
        "===== short test summary info =====\n"
        "SKIPPED tests/test_net.py::test_fetch\n"
        "===== 1 skipped in 0.01s =====\n"
    )
    (case,) = parse_pytest(stdout, "mcp", "2.1.1", "r_skip2").cases

    assert case.node_id == "tests/test_net.py::test_fetch"


def test_ansi_colour_does_not_change_the_verdict(green: str) -> None:
    coloured = green.replace("PASSED", "\x1b[32mPASSED\x1b[0m")
    report = parse_pytest(coloured, "mcp", "1.29.1", "r_ansi")

    assert report.passed == 61
    assert report.is_green is True
    assert "\x1b[" not in report.raw_tail


def test_strip_ansi_leaves_plain_text_alone(red: str) -> None:
    assert strip_ansi(red) == red


def test_raw_tail_is_bounded(green: str) -> None:
    report = parse_pytest(green, "mcp", "1.29.1", "r_tail")

    assert len(report.raw_tail) <= RAW_TAIL_CHARS
    assert report.raw_tail.endswith("\n") or report.raw_tail.endswith("=")
