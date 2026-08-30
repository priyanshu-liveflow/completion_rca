"""Mission store round-trip and MCP tool tests."""

from __future__ import annotations

from pathlib import Path
from threading import Thread

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


def test_dispatch_missing_mission_is_not_found() -> None:
    result = dispatch(
        "save_impact",
        {
            "mission_id": "missing",
            "row": {
                "contact_point": _contact().model_dump(),
                "verdict": "broken",
                "why": "test",
                "evidence_ref": None,
            },
        },
    )
    assert result == {
        "error": {
            "type": "not_found",
            "message": "mission not found: 'missing'",
        }
    }


def test_dispatch_rejects_non_boolean_breaking_hint() -> None:
    payload = _release().model_dump()
    payload["breaking_hint"] = "yes"
    result = dispatch("create_mission", payload)
    assert result["error"]["type"] == "invalid_input"
    assert "breaking_hint" in result["error"]["message"]


def test_default_store_is_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_server, "_store", None)
    monkeypatch.setattr(store_server, "_default_store", None)
    monkeypatch.setenv("AGENTRADAR_STORE_PATH", ":memory:")
    first = store_server.get_store()
    second = store_server.get_store()
    assert first is second


def test_concurrent_save_impact_preserves_all_rows(store: SqliteStore) -> None:
    """Eight threads, eight distinct sites, no lost update.

    Each thread saves a *different* contact point, so the lock is what is
    under test here and not the upsert: read-modify-write without it drops
    rows whenever two threads interleave.
    """
    created = store.create_mission(_release())

    def append_row(index: int) -> None:
        store.save_impact(
            created.id,
            ImpactRow(
                contact_point=_contact().model_copy(update={"fid": index}),
                verdict=Verdict.UNKNOWN,
                why=f"row-{index}",
                evidence_ref=None,
            ),
        )

    threads = [Thread(target=append_row, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    loaded = store.get_mission(created.id)
    assert len(loaded.impact_rows) == 8
    assert {row.why for row in loaded.impact_rows} == {f"row-{i}" for i in range(8)}


def test_save_impact_upserts_the_same_contact_point(store: SqliteStore) -> None:
    """A verdict arriving later replaces the placeholder, it does not duplicate it.

    This is the real mission shape: the graph locates a site with no verdict,
    then a test run proves it broken. Appending stored both and doubled the
    apparent blast radius.
    """
    created = store.create_mission(_release())
    store.save_impact(
        created.id,
        ImpactRow(
            contact_point=_contact(),
            verdict=Verdict.UNKNOWN,
            why="located by the graph",
            evidence_ref=None,
        ),
    )
    store.save_impact(
        created.id,
        ImpactRow(
            contact_point=_contact(),
            verdict=Verdict.BROKEN,
            why="collection error under 2.1.1",
            evidence_ref="report-1",
        ),
    )

    rows = store.get_mission(created.id).impact_rows
    assert len(rows) == 1
    assert rows[0].verdict is Verdict.BROKEN
    assert rows[0].evidence_ref == "report-1"


def test_save_impact_upsert_holds_graph_ordering(store: SqliteStore) -> None:
    """An updated row stays where the graph put it rather than jumping to the end."""
    created = store.create_mission(_release())
    for fid in (1, 2, 3):
        store.save_impact(
            created.id,
            ImpactRow(
                contact_point=_contact().model_copy(update={"fid": fid}),
                verdict=Verdict.UNKNOWN,
                why=f"site-{fid}",
                evidence_ref=None,
            ),
        )
    store.save_impact(
        created.id,
        ImpactRow(
            contact_point=_contact().model_copy(update={"fid": 1}),
            verdict=Verdict.BROKEN,
            why="site-1 proven broken",
            evidence_ref="report-1",
        ),
    )

    rows = store.get_mission(created.id).impact_rows
    assert [row.contact_point.fid for row in rows] == [1, 2, 3]
    assert rows[0].verdict is Verdict.BROKEN


# -- save_verify enforces validate_patch ------------------------------------
#
# `validate_patch` had no production caller: it was tested, documented, and
# unreachable. `save_verify` is where agent-written JSON becomes the evidence
# `can_act` reads, so it is the only place the rule can actually bind. These
# tests drive the MCP boundary, not the pure function, because the pure
# function was never the thing that was broken.

_ALLOWED_FILE = "src/intervals_mcp_server/mcp_instance.py"


def _diff_touching(*paths: str) -> str:
    return "".join(
        f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n"
        "@@ -1 +1 @@\n-from mcp.server.fastmcp import FastMCP\n"
        "+from mcp.server import MCPServer\n"
        for p in paths
    )


def _located_mission() -> Mission:
    """A mission whose impact analysis named exactly `_ALLOWED_FILE`."""
    created = dispatch("create_mission", _release().model_dump())
    assert "error" not in created
    mission_id = str(created["id"])
    dispatch(
        "save_impact",
        {
            "mission_id": mission_id,
            "row": ImpactRow(
                contact_point=_contact(),
                verdict=Verdict.BROKEN,
                why="Selected tests fail under mcp 2.1.1.",
                evidence_ref="rep_red",
            ).model_dump(),
        },
    )
    return Mission.model_validate(dispatch("get_mission", {"mission_id": mission_id}))


def _verify_payload(diff: str, declared: list[str]) -> dict[str, object]:
    return {
        "patch": {"diff": diff, "files": declared, "rationale": "rename import"},
        "before": _report(report_id="rep_red", passed=0, failed=2).model_dump(),
        "after": _report(report_id="rep_green", passed=61, failed=0).model_dump(),
    }


def test_save_verify_accepts_a_patch_inside_the_blast_radius() -> None:
    mission = _located_mission()
    result = dispatch(
        "save_verify",
        {
            "mission_id": mission.id,
            "result": _verify_payload(_diff_touching(_ALLOWED_FILE), [_ALLOWED_FILE]),
        },
    )
    assert "error" not in result
    assert Mission.model_validate(result).verify is not None


def test_save_verify_rejects_a_file_outside_the_blast_radius() -> None:
    mission = _located_mission()
    other = "src/intervals_mcp_server/unrelated.py"
    result = dispatch(
        "save_verify",
        {
            "mission_id": mission.id,
            "result": _verify_payload(_diff_touching(other), [other]),
        },
    )
    assert result["error"]["type"] == "patch_rejected"
    assert other in result["error"]["message"]


def test_save_verify_rejects_an_edit_to_a_test_file() -> None:
    """The whole product: an agent may not fix a failing test by editing it."""
    mission = _located_mission()
    result = dispatch(
        "save_verify",
        {
            "mission_id": mission.id,
            "result": _verify_payload(
                _diff_touching("tests/test_server.py"), ["tests/test_server.py"]
            ),
        },
    )
    assert result["error"]["type"] == "patch_rejected"
    assert (
        "may not fix a failing test by editing the test" in result["error"]["message"]
    )


def test_save_verify_reads_the_diff_not_the_declared_file_list() -> None:
    """`Patch.files` is agent-supplied, so the declared list proves nothing.

    Here the payload declares only the allowed production file while the diff
    rewrites a test. Trusting `patch.files` passes both of `validate_patch`'s
    rules while `git apply` edits the test.
    """
    mission = _located_mission()
    result = dispatch(
        "save_verify",
        {
            "mission_id": mission.id,
            "result": _verify_payload(
                _diff_touching("tests/test_server.py"), [_ALLOWED_FILE]
            ),
        },
    )
    assert result["error"]["type"] == "patch_rejected"
    assert "tests/test_server.py" in result["error"]["message"]


def test_save_verify_rejects_a_rename_that_moves_a_test_out_of_the_way() -> None:
    """A rename names two paths; only the destination looks innocent.

    `diff --git a/tests/test_server.py b/<allowed>.py` reads as one allowed,
    non-test file if only the `b/` side is recorded — while `git apply`
    deletes the test. Both endpoints have to count.
    """
    mission = _located_mission()
    rename = (
        f"diff --git a/tests/test_server.py b/{_ALLOWED_FILE}\n"
        "similarity index 92%\n"
        "rename from tests/test_server.py\n"
        f"rename to {_ALLOWED_FILE}\n"
    )
    result = dispatch(
        "save_verify",
        {
            "mission_id": mission.id,
            "result": _verify_payload(rename, [_ALLOWED_FILE]),
        },
    )
    assert result["error"]["type"] == "patch_rejected"
    assert "tests/test_server.py" in result["error"]["message"]


def test_save_verify_refuses_every_patch_when_nothing_was_located() -> None:
    """No impact rows means no blast radius, so no patch is aimed at anything."""
    created = dispatch("create_mission", _release().model_dump())
    result = dispatch(
        "save_verify",
        {
            "mission_id": str(created["id"]),
            "result": _verify_payload(_diff_touching(_ALLOWED_FILE), [_ALLOWED_FILE]),
        },
    )
    assert result["error"]["type"] == "patch_rejected"
    assert "allowed: none" in result["error"]["message"]


@pytest.mark.parametrize("sent", ["WATCHING", "watching", "  Reproducing  "])
def test_set_state_accepts_the_casing_our_own_prompt_teaches(sent: str) -> None:
    """`MissionState` values are lower; its members and our prose are upper.

    A live mission read `WATCHING -> LOCATING -> ...` from the conductor
    prompt, sent `"WATCHING"`, and got `unknown state`. Failing a caller over
    the casing of a name we spell two ways ourselves is a pointless error at
    the one step whose entire job is bookkeeping.
    """
    created = dispatch("create_mission", _release().model_dump())
    result = dispatch("set_state", {"mission_id": created["id"], "state": sent})
    assert "error" not in result
    assert result["state"] == sent.strip().lower()


def test_set_state_still_rejects_a_state_that_does_not_exist() -> None:
    created = dispatch("create_mission", _release().model_dump())
    result = dispatch("set_state", {"mission_id": created["id"], "state": "wat"})
    assert result["error"]["type"] == "invalid_input"
    assert "expected one of" in result["error"]["message"]
    assert "awaiting_approval" in result["error"]["message"]
