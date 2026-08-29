"""Round-trip and invariant tests for every AgentRadar contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.main.agentradar.contracts.collector import (
    CollectorRun,
    CollectorSpec,
    HealthVerdict,
)
from src.main.agentradar.contracts.dependency import Dependency, ReleaseEvent, Watchlist
from src.main.agentradar.contracts.evidence import TestCase, TestReport, TestSelection
from src.main.agentradar.contracts.impact import (
    BlastRadius,
    ContactPoint,
    ImpactRow,
    Verdict,
)
from src.main.agentradar.contracts.mission import ActionPlan, Mission, MissionState
from src.main.agentradar.contracts.patch import Patch, VerifyResult
from src.main.agentradar.contracts.web import PageContent, SearchHit, SearchResults


def _dependency() -> Dependency:
    return Dependency(
        name="mcp",
        current_spec=">=1.4.0,<2.0.0",
        current_version="1.29.1",
        source="pyproject.toml",
    )


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


def _case(*, outcome: str = "failed") -> TestCase:
    return TestCase(
        node_id="tests/test_server.py::test_boot",
        outcome=outcome,  # type: ignore[arg-type]
        duration_s=0.12,
        traceback=(
            "ModuleNotFoundError: mcp.server.fastmcp" if outcome == "failed" else None
        ),
    )


def _report(
    *, report_id: str, passed: int, failed: int, outcome: str, errors: int = 0
) -> TestReport:
    return TestReport(
        id=report_id,
        package="mcp",
        version="2.1.1",
        cases=[_case(outcome=outcome)],
        passed=passed,
        failed=failed,
        errors=errors,
        duration_s=0.5,
        raw_tail="Interrupted: 2 errors during collection",
    )


def _patch() -> Patch:
    return Patch(
        diff=(
            "- from mcp.server.fastmcp import FastMCP\n"
            "+ from mcp.server.mcpserver import MCPServer as FastMCP\n"
        ),
        files=["src/intervals_mcp_server/mcp_instance.py"],
        rationale="MCP v2 renamed FastMCP to MCPServer.",
    )


def _health(*, healthy: bool) -> HealthVerdict:
    return HealthVerdict(
        healthy=healthy,
        rows_returned=8 if healthy else 1,
        missing_field_ratio=0.0 if healthy else 0.4,
        missing_fields=[] if healthy else ["tag"],
        symptom=(
            None
            if healthy
            else "1 of 5 rows missing 'tag'; 1 row returned, expected >= 5"
        ),
    )


def _round_trip(model: object) -> None:
    cls = type(model)
    restored = cls.model_validate(model.model_dump())  # type: ignore[attr-defined]
    assert restored == model


def test_dependency_round_trip() -> None:
    _round_trip(_dependency())


def test_watchlist_round_trip() -> None:
    _round_trip(Watchlist(repo="intervals-mcp-server", dependencies=[_dependency()]))


def test_release_event_round_trip() -> None:
    _round_trip(_release())


def test_contact_point_round_trip() -> None:
    _round_trip(_contact())


def test_blast_radius_round_trip() -> None:
    _round_trip(
        BlastRadius(
            contact_point=_contact(),
            callers=["make_app", "test_boot"],
            depth_reached=2,
        )
    )


def test_impact_row_round_trip() -> None:
    _round_trip(
        ImpactRow(
            contact_point=_contact(),
            verdict=Verdict.BROKEN,
            why="Selected tests fail to import under mcp 2.1.1.",
            evidence_ref="rep_red",
        )
    )


def test_verdict_values() -> None:
    assert list(Verdict) == [
        Verdict.UNKNOWN,
        Verdict.BROKEN,
        Verdict.SAFE,
        Verdict.UNCOVERED,
    ]


def test_test_selection_round_trip() -> None:
    _round_trip(_selection())
    _round_trip(
        TestSelection(
            tests=["tests/test_server.py::test_boot"],
            strategy="imports",
            reached_from=["create_mcp_server"],
        )
    )


def test_test_case_round_trip() -> None:
    _round_trip(_case())


def test_test_report_round_trip() -> None:
    report = _report(report_id="rep_red", passed=0, failed=2, outcome="error")
    _round_trip(report)


def test_test_report_is_green() -> None:
    green = _report(report_id="rep_green", passed=61, failed=0, outcome="passed")
    red = _report(report_id="rep_red", passed=0, failed=2, outcome="failed")
    empty = TestReport(
        id="rep_empty",
        package="mcp",
        version="2.1.1",
        cases=[],
        passed=0,
        failed=0,
        errors=0,
        duration_s=0.0,
        raw_tail="Interrupted: 2 errors during collection",
    )
    collection = TestReport(
        id="rep_collection",
        package="mcp",
        version="2.1.1",
        cases=[],
        passed=0,
        failed=0,
        errors=2,
        duration_s=0.37,
        raw_tail="Interrupted: 2 errors during collection",
    )
    mixed = TestReport(
        id="rep_mixed",
        package="mcp",
        version="2.1.1",
        cases=[
            _case(outcome="passed"),
            TestCase(
                node_id="tests/test_server.py",
                outcome="error",
                duration_s=0.0,
                traceback="collection error",
            ),
        ],
        passed=1,
        failed=0,
        errors=0,
        duration_s=0.5,
        raw_tail="1 passed, 1 error",
    )
    assert green.is_green is True
    assert green.is_broken is False
    assert red.is_green is False
    assert red.is_broken is True
    assert empty.is_green is False
    assert empty.is_broken is False
    assert collection.is_green is False
    assert collection.is_broken is True
    assert mixed.is_green is False
    assert mixed.is_broken is True


def test_patch_round_trip() -> None:
    _round_trip(_patch())


def test_verify_result_round_trip() -> None:
    before = _report(report_id="rep_red", passed=0, failed=2, outcome="failed")
    after = _report(report_id="rep_green", passed=61, failed=0, outcome="passed")
    result = VerifyResult(
        patch=_patch(),
        before=before,
        after=after,
    )
    _round_trip(result)
    assert result.verified is True


def test_verify_result_collection_error_is_broken() -> None:
    before = TestReport(
        id="rep_collection",
        package="mcp",
        version="2.1.1",
        cases=[],
        passed=0,
        failed=0,
        errors=2,
        duration_s=0.37,
        raw_tail="Interrupted: 2 errors during collection",
    )
    after = _report(report_id="rep_green", passed=61, failed=0, outcome="passed")
    assert before.is_broken is True
    assert before.failed == 0
    verified = before.is_broken and after.is_green
    assert verified is True


def test_collector_spec_round_trip() -> None:
    _round_trip(
        CollectorSpec(
            id="c_mcp_releases",
            url="https://github.com/modelcontextprotocol/python-sdk/releases",
            description="Extract releases: tag, date, body, breaking_change_flag",
            required_fields=["tag", "date", "body"],
        )
    )


def test_health_verdict_round_trip() -> None:
    _round_trip(_health(healthy=False))


def test_collector_run_round_trip() -> None:
    _round_trip(
        CollectorRun(
            spec_id="c_mcp_releases",
            rows=[{"tag": "v2.1.1", "date": "2026-01-15", "body": "rename"}],
            health=_health(healthy=False),
            healed=True,
            health_after_heal=_health(healthy=True),
        )
    )


def test_mission_state_values() -> None:
    assert [s.value for s in MissionState] == [
        "watching",
        "locating",
        "reproducing",
        "patching",
        "awaiting_approval",
        "done",
        "failed",
    ]


def test_mission_round_trip_and_mutation() -> None:
    mission = Mission(id="m1", release=_release(), state=MissionState.WATCHING)
    assert mission.impact_rows == []
    mission.state = MissionState.LOCATING
    mission.impact_rows.append(
        ImpactRow(
            contact_point=_contact(),
            verdict=Verdict.UNKNOWN,
            why="Graph hit; not yet proven.",
            evidence_ref=None,
        )
    )
    dumped = mission.model_dump()
    restored = Mission.model_validate(dumped)
    assert restored.state is MissionState.LOCATING
    assert len(restored.impact_rows) == 1


def test_action_plan_round_trip() -> None:
    _round_trip(
        ActionPlan(
            target="github_pr",
            summary="Open a PR with the verified FastMCP rename.",
            payload={"branch": "fix/mcp-v2"},
            requires_approval=True,
        )
    )


def test_search_results_round_trip() -> None:
    _round_trip(
        SearchResults(
            query="mcp python sdk v2 migration",
            hits=[
                SearchHit(
                    title="MCP Python SDK v2 migration",
                    url="https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md",
                    snippet="FastMCP was renamed to MCPServer.",
                )
            ],
        )
    )


def test_page_content_round_trip() -> None:
    _round_trip(
        PageContent(
            url="https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md",
            text="# Migration\n\nFastMCP is now MCPServer.\n",
        )
    )


def test_frozen_models_reject_assignment() -> None:
    dep = _dependency()
    with pytest.raises(ValidationError):
        dep.name = "other"  # type: ignore[misc]
