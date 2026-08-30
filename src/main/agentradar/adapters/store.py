"""Mission persistence. Protocol + SQLite implementation."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from typing import Protocol

from ..contracts.dependency import ReleaseEvent
from ..contracts.evidence import TestReport, TestSelection
from ..contracts.impact import ImpactRow
from ..contracts.mission import Mission, MissionState
from ..contracts.patch import VerifyResult
from ..contracts.review import ReviewRun

__all__ = ["MissionStore", "SqliteStore", "default_store_path"]


def default_store_path() -> str:
    """SQLite path from ``AGENTRADAR_STORE_PATH``, else ``agentradar.db``."""
    return os.environ.get("AGENTRADAR_STORE_PATH", "agentradar.db")


class MissionStore(Protocol):
    """Persistence for mission state and evidence."""

    def create_mission(self, release: ReleaseEvent) -> Mission: ...

    def save_impact(self, mission_id: str, row: ImpactRow) -> None: ...

    def save_selection(self, mission_id: str, sel: TestSelection) -> None: ...

    def save_report(self, mission_id: str, report: TestReport) -> None: ...

    def save_verify(self, mission_id: str, result: VerifyResult) -> None: ...

    def get_mission(self, mission_id: str) -> Mission: ...

    def set_state(self, mission_id: str, state: MissionState) -> None: ...


class SqliteStore:
    """Single-file SQLite store with JSON columns for contract payloads."""

    def __init__(self, path: str | None = None) -> None:
        db_path = path if path is not None else default_store_path()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS missions (
                id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                release_json TEXT NOT NULL,
                impact_rows_json TEXT NOT NULL,
                selection_json TEXT,
                reports_json TEXT NOT NULL,
                verify_json TEXT
            )
            """
        )
        # Review runs are a separate table, not a mission with a strange
        # shape. A mission tracks one dependency release through states; a
        # review run is a snapshot of one pull request at one moment and has
        # no lifecycle. Forcing them together would give both a state column
        # that only one of them means anything by.
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS review_runs (
                id TEXT PRIMARY KEY,
                repo TEXT NOT NULL,
                pr INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                run_json TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def create_mission(self, release: ReleaseEvent) -> Mission:
        """Insert a new mission in ``WATCHING`` state."""
        with self._lock:
            mission = Mission(
                id=str(uuid.uuid4()),
                release=release,
                state=MissionState.WATCHING,
            )
            self._insert(mission)
            return mission.model_copy(deep=True)

    def save_impact(self, mission_id: str, row: ImpactRow) -> None:
        """Record one impact row, replacing any earlier row for the same site.

        Upsert, not append. A mission naturally saves the same contact point
        twice — once when the graph locates it, with `verdict=unknown`, and
        again once a test run has proven it `broken` or `safe`. Appending
        turned seven located sites into fourteen stored rows, half of them
        superseded, and an impact table that double-counts the blast radius
        is not evidence, it is a bug a reader has to correct for.

        Identity is the `ContactPoint` itself, so a re-save carrying a new
        verdict replaces the placeholder in place, holding the graph's
        original ordering rather than moving the row to the end.
        """
        with self._lock:
            mission = self.get_mission(mission_id)
            rows = mission.impact_rows
            for i, existing in enumerate(rows):
                if existing.contact_point == row.contact_point:
                    rows[i] = row
                    break
            else:
                rows.append(row)
            self._update(mission)

    def save_selection(self, mission_id: str, sel: TestSelection) -> None:
        """Persist graph-guided test selection for the mission."""
        with self._lock:
            mission = self.get_mission(mission_id)
            mission.selection = sel
            self._update(mission)

    def save_report(self, mission_id: str, report: TestReport) -> None:
        """Append a parsed test report to the mission."""
        with self._lock:
            mission = self.get_mission(mission_id)
            mission.reports.append(report)
            self._update(mission)

    def save_verify(self, mission_id: str, result: VerifyResult) -> None:
        """Persist patch verification evidence for the mission."""
        with self._lock:
            mission = self.get_mission(mission_id)
            mission.verify = result
            self._update(mission)

    def get_mission(self, mission_id: str) -> Mission:
        """Load a mission by id."""
        row = self._conn.execute(
            "SELECT * FROM missions WHERE id = ?",
            (mission_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"mission not found: {mission_id!r}")
        return Mission.model_validate(
            {
                "id": row["id"],
                "state": row["state"],
                "release": json.loads(row["release_json"]),
                "impact_rows": json.loads(row["impact_rows_json"]),
                "selection": (
                    json.loads(row["selection_json"])
                    if row["selection_json"] is not None
                    else None
                ),
                "reports": json.loads(row["reports_json"]),
                "verify": (
                    json.loads(row["verify_json"])
                    if row["verify_json"] is not None
                    else None
                ),
            }
        )

    def save_review_run(self, run: ReviewRun) -> None:
        """Persist a review verification, superseding any earlier run for that PR.

        A re-verification replaces the previous run rather than accumulating
        beside it: "what does this pull request look like now" has one answer,
        and a list of stale ones is how a dashboard starts lying.
        """
        with self._lock:
            self._conn.execute(
                "DELETE FROM review_runs WHERE repo = ? AND pr = ?",
                (run.repo, run.pr),
            )
            self._conn.execute(
                "INSERT INTO review_runs (id, repo, pr, created_at, run_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (run.id, run.repo, run.pr, run.created_at, run.model_dump_json()),
            )
            self._conn.commit()

    def get_review_run(self, run_id: str) -> ReviewRun | None:
        """One persisted review run, or None when there is no such id."""
        row = self._conn.execute(
            "SELECT run_json FROM review_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return ReviewRun.model_validate_json(row["run_json"]) if row else None

    def list_review_runs(self, limit: int = 50) -> list[ReviewRun]:
        """Persisted review runs, newest first."""
        rows = self._conn.execute(
            "SELECT run_json FROM review_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [ReviewRun.model_validate_json(row["run_json"]) for row in rows]

    def set_state(self, mission_id: str, state: MissionState) -> None:
        """Update mission lifecycle state."""
        with self._lock:
            mission = self.get_mission(mission_id)
            mission.state = state
            self._update(mission)

    def _insert(self, mission: Mission) -> None:
        payload = self._row_payload(mission)
        self._conn.execute(
            """
            INSERT INTO missions (
                id, state, release_json, impact_rows_json,
                selection_json, reports_json, verify_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mission.id,
                mission.state.value,
                payload["release_json"],
                payload["impact_rows_json"],
                payload["selection_json"],
                payload["reports_json"],
                payload["verify_json"],
            ),
        )
        self._conn.commit()

    def _update(self, mission: Mission) -> None:
        payload = self._row_payload(mission)
        self._conn.execute(
            """
            UPDATE missions SET
                state = ?,
                release_json = ?,
                impact_rows_json = ?,
                selection_json = ?,
                reports_json = ?,
                verify_json = ?
            WHERE id = ?
            """,
            (
                mission.state.value,
                payload["release_json"],
                payload["impact_rows_json"],
                payload["selection_json"],
                payload["reports_json"],
                payload["verify_json"],
                mission.id,
            ),
        )
        self._conn.commit()

    @staticmethod
    def _row_payload(mission: Mission) -> dict[str, str | None]:
        return {
            "release_json": json.dumps(mission.release.model_dump(mode="json")),
            "impact_rows_json": json.dumps(
                [row.model_dump(mode="json") for row in mission.impact_rows]
            ),
            "selection_json": (
                json.dumps(mission.selection.model_dump(mode="json"))
                if mission.selection is not None
                else None
            ),
            "reports_json": json.dumps(
                [report.model_dump(mode="json") for report in mission.reports]
            ),
            "verify_json": (
                json.dumps(mission.verify.model_dump(mode="json"))
                if mission.verify is not None
                else None
            ),
        }
