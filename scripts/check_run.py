"""Inspect what a mission actually persisted.

    python scripts/check_run.py            # recent missions, one line each
    python scripts/check_run.py <id>       # full evidence for one mission

Reads the store directly. The store is the product: if evidence only exists
in a chat transcript and not here, the mission did not really happen.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Run me as `python scripts/check_run.py` from anywhere without setting
# PYTHONPATH. Python puts `scripts/` on the path, not the repo root, so the
# `src.` imports below fail unless the root is added first.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.main.agentradar.adapters.store import SqliteStore, default_store_path
from src.main.agentradar.contracts.mission import Mission
from src.main.agentradar.core.patch import can_act


def _summary(mission: Mission) -> str:
    reports = len(mission.reports)
    verdicts = {row.verdict.value for row in mission.impact_rows}
    return (
        f"{mission.id[:8]}  {mission.state.value:<18} "
        f"impact={len(mission.impact_rows):<3} reports={reports:<3} "
        f"verify={'yes' if mission.verify else 'no':<3} "
        f"verdicts={','.join(sorted(verdicts)) or '-'}"
    )


def _detail(mission: Mission) -> None:
    print(f"mission  {mission.id}")
    print(f"state    {mission.state.value}")
    print(f"release  {mission.release.dependency} -> {mission.release.version}")

    print(f"\nimpact rows ({len(mission.impact_rows)})")
    for row in mission.impact_rows:
        cp = row.contact_point
        print(f"  {row.verdict.value:<10} {cp.file_path}::{cp.function_name}")

    if mission.selection is not None:
        sel = mission.selection
        print(f"\nselection  strategy={sel.strategy} truncated={sel.truncated}")
        for node in sel.tests:
            print(f"  {node}")
    else:
        print("\nselection  NONE — no tests were ever chosen")

    print(f"\ntest reports ({len(mission.reports)})")
    for rep in mission.reports:
        state = "green" if rep.is_green else ("BROKEN" if rep.is_broken else "empty")
        print(
            f"  {rep.id:<12} {rep.package}=={rep.version:<8} "
            f"passed={rep.passed:<4} failed={rep.failed:<4} "
            f"errors={rep.errors:<3} -> {state}"
        )

    verify = mission.verify
    print("\ngate")
    if verify is None:
        print("  no VerifyResult — can_act is False, the PR tool does not exist")
        return
    print(f"  before  broken={verify.before.is_broken}  ({verify.before.id})")
    print(f"  after   green ={verify.after.is_green}   ({verify.after.id})")
    print(f"  verified={verify.verified}   can_act={can_act(verify)}")
    print(
        f"  patch touches {len(verify.patch.files)} file(s): "
        f"{', '.join(verify.patch.files) or '(none)'}"
    )


def main() -> int:
    store = SqliteStore(default_store_path())
    if len(sys.argv) > 1:
        wanted = sys.argv[1]
        try:
            _detail(store.get_mission(wanted))
            return 0
        except KeyError:
            pass
        # Accept an unambiguous id prefix — the summary view prints 8 chars.
        import sqlite3

        con = sqlite3.connect(default_store_path())
        hits = [
            r[0]
            for r in con.execute(
                "select id from missions where id like ?", (wanted + "%",)
            )
        ]
        if len(hits) == 1:
            _detail(store.get_mission(hits[0]))
            return 0
        if not hits:
            print(f"no mission {wanted!r}", file=sys.stderr)
        else:
            print(f"{wanted!r} matches {len(hits)} missions", file=sys.stderr)
        return 1

    ids = store.list_mission_ids() if hasattr(store, "list_mission_ids") else []
    if not ids:
        import sqlite3

        con = sqlite3.connect(default_store_path())
        ids = [
            r[0]
            for r in con.execute("select id from missions order by rowid desc limit 15")
        ]
    for mid in ids:
        print(_summary(store.get_mission(mid)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
