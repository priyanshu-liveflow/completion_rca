"""`can_act` — the single most important assertion in the codebase.

Every `TestReport` here comes from `core.testreport.parse_pytest` reading the
real captured fixtures in `fixtures/pytest_output_{red,green}.txt`, not a
hand-constructed report, so the gate is proven against output pytest actually
produced rather than against assumptions about its shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.main.agentradar.contracts.evidence import TestReport
from src.main.agentradar.contracts.patch import Patch
from src.main.agentradar.core.patch import build_verify_result, can_act
from src.main.agentradar.core.testreport import parse_pytest

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

_PATCH = Patch(diff="", files=["src/x.py"], rationale="bump mcp 1.x -> 2.x")


def _fixture(name: str) -> str:
    return (FIXTURES / f"pytest_output_{name}.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def red_report() -> TestReport:
    return parse_pytest(_fixture("red"), "mcp", "2.1.1", "r_red")


@pytest.fixture(scope="module")
def green_report() -> TestReport:
    return parse_pytest(_fixture("green"), "mcp", "2.1.1", "r_green")


# -- the four cases test_gate.py must assert --------------------------------


def test_verify_none_cannot_act() -> None:
    assert can_act(None) is False


def test_before_green_cannot_act(green_report: TestReport) -> None:
    """Nothing was broken to begin with, so there is nothing proven fixed."""
    assert green_report.is_green is True
    verify = build_verify_result(_PATCH, before=green_report, after=green_report)
    assert verify.verified is False
    assert can_act(verify) is False


def test_after_red_cannot_act(red_report: TestReport) -> None:
    """The patch did not fix anything: after is still broken."""
    verify = build_verify_result(_PATCH, before=red_report, after=red_report)
    assert verify.verified is False
    assert can_act(verify) is False


def test_before_broken_after_green_can_act(
    red_report: TestReport, green_report: TestReport
) -> None:
    verify = build_verify_result(_PATCH, before=red_report, after=green_report)
    assert verify.verified is True
    assert can_act(verify) is True


# -- the case that motivates the whole design -------------------------------


def test_collection_error_counts_as_broken_and_opens_the_gate(
    red_report: TestReport, green_report: TestReport
) -> None:
    """Our demo's red case is a collection error, not a test failure.

    Two modules fail to import: pytest reports `passed=0, failed=0, errors=2`.
    A gate keyed on `before.failed > 0` would call this run healthy and
    refuse to open the PR after a patch that actually worked — at the last
    step of the demo. `is_broken` must still be True here, and pairing it
    with a green `after` must still open the gate.
    """
    assert red_report.passed == 0
    assert red_report.failed == 0
    assert red_report.errors == 2
    assert red_report.is_broken is True
    assert red_report.is_green is False

    verify = build_verify_result(_PATCH, before=red_report, after=green_report)
    assert verify.verified is True
    assert can_act(verify) is True
