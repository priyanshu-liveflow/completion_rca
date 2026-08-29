"""Mission store round-trip and MCP tool tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.main.agentradar.adapters.store import SqliteStore
from src.main.agentradar.contracts.dependency import ReleaseEvent
from src.main.agentradar.contracts.evidence import TestCase, TestReport, TestSelection
from src.main.agentradar.contracts.impact import ContactPoint, ImpactRow, Verdict
from src.main.agentradar.contracts.mission import Mission, MissionState
from src.main.agentradar.contracts.patch import Patch, VerifyResult
from src.main.agentradar.mcp import store_server
from src.main.agentradar.mcp._server import dispatch

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def store() -> SqliteStore:
    """In-memory SQLite store."""
    return SqliteStore(":memory:")


@pytest.fixture(autouse=True)
def _inject_store(store: SqliteStore) -> None:
    store_server.set_store(store)


def _release() -> ReleaseEvent:
    return ReleaseEvent(
        dependency="mcp",
        version="2.1.1",
        published_at="2026-01-15T00:00:00Z",
        title="MCP Python SDK 2.1.1",
        body="FastMCP was renamed to MCPServer.",
        url="https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.1.1",
        breaking_hint=True,
        source_collector="c_mcp_releases",
    )


def _contact() -> ContactPoint:
    return ContactPoint(
        symbol="FastMCP",
        function_name="create_mcp_server",
        fid=42,
        file_path="src/intervals_mcp_server/mcp_instance.py",
        line=17,
    )


def _selection() -> TestSelection:
    return TestSelection(
        tests=["tests/test_server.py::test_boot"],
        strategy="callers",
        reached_from=["create_mcp_server"],
        truncated=False,
    )


def _report(*, report_id: str, passed: int, failed: int) -> TestReport:
    return TestReport(
        id=report_id,
        package="mcp",
        version="2.1.1",
        cases=[
            TestCase(
                node_id="tests/test_server.py::test_boot",
                outcome="failed" if failed else "passed",
                duration_s=0.12,
                traceback="ModuleNotFoundError" if failed else None,
            )
        ],
        passed=passed,
        failed=failed,
        errors=0,
        duration_s=0.5,
        raw_tail="tail",
    )


def _patch() -> Patch:
    return Patch(
        diff="- old\n+ new\n",
        files=["src/intervals_mcp_server/mcp_instance.py"],
        rationale="rename import",
    )


def _verify() -> VerifyResult:
    before = _report(report_id="rep_red", passed=0, failed=2)
    after = _report(report_id="rep_green", passed=61, failed=0)
    return VerifyResult(
        patch=_patch(),
        before=before,
        after=after,
        verified=before.is_broken and after.is_green,
    )


def test_full_mission_round_trip(store: SqliteStore) -> None:
    """Every mission field survives a persist → reload cycle."""
    created = store.create_mission(_release())
    store.set_state(created.id, MissionState.LOCATING)

    impact = ImpactRow(
        contact_point=_contact(),
        verdict=Verdict.BROKEN,
        why="Selected tests fail under mcp 2.1.1.",
        evidence_ref="rep_red",
    )
    store.save_impact(created.id, impact)
    store.save_selection(created.id, _selection())
    store.save_report(created.id, _report(report_id="rep_red", passed=0, failed=2))
    store.save_verify(created.id, _verify())
    store.set_state(created.id, MissionState.AWAITING_APPROVAL)

    loaded = store.get_mission(created.id)
    assert loaded.id == created.id
    assert loaded.state is MissionState.AWAITING_APPROVAL
    assert loaded.release == _release()
    assert loaded.impact_rows == [impact]
    assert loaded.selection == _selection()
    assert len(loaded.reports) == 1
    assert loaded.reports[0] == _report(report_id="rep_red", passed=0, failed=2)
    assert loaded.verify == _verify()


def test_get_mission_missing_raises(store: SqliteStore) -> None:
    with pytest.raises(KeyError, match="mission not found"):
        store.get_mission("missing")


def test_mcp_create_and_get_mission() -> None:
    payload = _release().model_dump()
    created = store_server.create_mission(**payload)
    assert isinstance(created, Mission)
    assert created.state is MissionState.WATCHING

    fetched = store_server.get_mission(created.id)
    assert fetched == created


def test_mcp_save_report_parses_raw_pytest() -> None:
    stdout = (FIXTURES / "pytest_output_red.txt").read_text(encoding="utf-8")
    created = store_server.create_mission(**_release().model_dump())
    mission = store_server.save_report(
        mission_id=created.id,
        stdout=stdout,
        package="mcp",
        version="2.1.1",
        report_id="rep_red",
        exit_code=2,
    )
    assert len(mission.reports) == 1
    report = mission.reports[0]
    assert report.id == "rep_red"
    assert report.is_broken is True
    assert report.errors == 2


def test_dispatch_returns_contract_models() -> None:
    created = dispatch(
        "create_mission",
        _release().model_dump(),
    )
    assert isinstance(created, dict)
    assert created["state"] == "watching"
    mission_id = created["id"]

    updated = dispatch(
        "set_state",
        {"mission_id": mission_id, "state": "locating"},
    )
    assert updated["state"] == "locating"

    green_stdout = (FIXTURES / "pytest_output_green.txt").read_text(encoding="utf-8")
    with_report = dispatch(
        "save_report",
        {
            "mission_id": mission_id,
            "stdout": green_stdout,
            "package": "mcp",
            "version": "2.1.1",
            "report_id": "rep_green",
        },
    )
    assert with_report["reports"][0]["passed"] == 61
