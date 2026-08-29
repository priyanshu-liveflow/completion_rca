"""MCP server for mission state and evidence persistence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.main.agentradar.adapters.store import (
    MissionStore,
    SqliteStore,
    default_store_path,
)
from src.main.agentradar.contracts.dependency import ReleaseEvent
from src.main.agentradar.contracts.evidence import TestSelection
from src.main.agentradar.contracts.impact import ImpactRow
from src.main.agentradar.contracts.mission import Mission, MissionState
from src.main.agentradar.contracts.patch import VerifyResult
from src.main.agentradar.core.testreport import parse_pytest
from src.main.agentradar.mcp._server import ToolError, serve, tool

_store: MissionStore | None = None
_default_store: SqliteStore | None = None


def set_store(store: MissionStore) -> None:
    """Inject a store implementation. Tests pass ``SqliteStore(':memory:')``."""
    global _store
    _store = store


def get_store() -> MissionStore:
    """Return the active store, caching the default SQLite instance."""
    global _default_store
    if _store is not None:
        return _store
    if _default_store is None:
        _default_store = SqliteStore(default_store_path())
    return _default_store


def _not_found_error(exc: KeyError) -> ToolError:
    message = str(exc.args[0]) if exc.args else str(exc)
    return ToolError("not_found", message)


def _mission_or_error(mission_id: str) -> Mission:
    try:
        return get_store().get_mission(mission_id)
    except KeyError as exc:
        raise _not_found_error(exc) from exc


def _mutate(mission_id: str, action: Callable[[], None]) -> Mission:
    """Run a store mutation and return the refreshed mission."""
    try:
        action()
    except KeyError as exc:
        raise _not_found_error(exc) from exc
    return _mission_or_error(mission_id)


@tool(
    "create_mission",
    "Start a mission for a dependency release event.",
    {
        "type": "object",
        "properties": {
            "dependency": {"type": "string"},
            "version": {"type": "string"},
            "published_at": {"type": "string"},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "url": {"type": "string"},
            "breaking_hint": {"type": "boolean"},
            "source_collector": {"type": "string"},
        },
        "required": [
            "dependency",
            "version",
            "published_at",
            "title",
            "body",
            "url",
        ],
    },
)
def create_mission(
    dependency: str,
    version: str,
    published_at: str,
    title: str,
    body: str,
    url: str,
    breaking_hint: bool = False,
    source_collector: str | None = None,
) -> Mission:
    """Create a mission in WATCHING state."""
    release = ReleaseEvent(
        dependency=dependency,
        version=version,
        published_at=published_at,
        title=title,
        body=body,
        url=url,
        breaking_hint=breaking_hint,
        source_collector=source_collector,
    )
    return get_store().create_mission(release)


@tool(
    "get_mission",
    "Load a mission with all persisted evidence.",
    {
        "type": "object",
        "properties": {"mission_id": {"type": "string"}},
        "required": ["mission_id"],
    },
)
def get_mission(mission_id: str) -> Mission:
    """Return the full mission record."""
    return _mission_or_error(mission_id)


@tool(
    "set_state",
    "Advance mission lifecycle state.",
    {
        "type": "object",
        "properties": {
            "mission_id": {"type": "string"},
            "state": {"type": "string"},
        },
        "required": ["mission_id", "state"],
    },
)
def set_state(mission_id: str, state: str) -> Mission:
    """Update mission state and return the refreshed record."""
    try:
        mission_state = MissionState(state)
    except ValueError as exc:
        raise ToolError("invalid_input", f"unknown state {state!r}") from exc
    return _mutate(
        mission_id,
        lambda: get_store().set_state(mission_id, mission_state),
    )


@tool(
    "save_impact",
    "Append one impact-table row to a mission.",
    {
        "type": "object",
        "properties": {
            "mission_id": {"type": "string"},
            "row": {"type": "object"},
        },
        "required": ["mission_id", "row"],
    },
)
def save_impact(mission_id: str, row: dict[str, Any]) -> Mission:
    """Persist an :class:`ImpactRow` and return the mission."""
    impact = ImpactRow.model_validate(row)
    return _mutate(
        mission_id,
        lambda: get_store().save_impact(mission_id, impact),
    )


@tool(
    "save_selection",
    "Persist graph-guided test selection for a mission.",
    {
        "type": "object",
        "properties": {
            "mission_id": {"type": "string"},
            "selection": {"type": "object"},
        },
        "required": ["mission_id", "selection"],
    },
)
def save_selection(mission_id: str, selection: dict[str, Any]) -> Mission:
    """Persist a :class:`TestSelection` and return the mission."""
    sel = TestSelection.model_validate(selection)
    return _mutate(
        mission_id,
        lambda: get_store().save_selection(mission_id, sel),
    )


@tool(
    "save_report",
    "Parse raw pytest output and append a test report to a mission.",
    {
        "type": "object",
        "properties": {
            "mission_id": {"type": "string"},
            "stdout": {"type": "string"},
            "package": {"type": "string"},
            "version": {"type": "string"},
            "report_id": {"type": "string"},
            "duration_s": {"type": "number"},
            "exit_code": {"type": "integer"},
        },
        "required": ["mission_id", "stdout", "package", "version", "report_id"],
    },
)
def save_report(
    mission_id: str,
    stdout: str,
    package: str,
    version: str,
    report_id: str,
    duration_s: float = 0.0,
    exit_code: int | None = None,
) -> Mission:
    """Parse pytest output in core, persist the report, return the mission."""
    report = parse_pytest(
        stdout,
        package,
        version,
        report_id,
        duration_s=duration_s,
        exit_code=exit_code,
    )
    return _mutate(
        mission_id,
        lambda: get_store().save_report(mission_id, report),
    )


@tool(
    "save_verify",
    "Persist patch verification evidence for a mission.",
    {
        "type": "object",
        "properties": {
            "mission_id": {"type": "string"},
            "result": {"type": "object"},
        },
        "required": ["mission_id", "result"],
    },
)
def save_verify(mission_id: str, result: dict[str, Any]) -> Mission:
    """Persist a :class:`VerifyResult` and return the mission."""
    verify = VerifyResult.model_validate(result)
    return _mutate(
        mission_id,
        lambda: get_store().save_verify(mission_id, verify),
    )


def main() -> None:
    """Entry: ``python -m src.main.agentradar.mcp.store_server --port 8767``."""
    import argparse

    parser = argparse.ArgumentParser(description="AgentRadar mission store MCP server")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    serve("mcp-store", args.port)


if __name__ == "__main__":
    main()
