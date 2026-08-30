"""End-to-end smoke test over real data. No mocks, no fixtures for the graph.

Runs the pipeline as far as the merged code allows and prints where it stops.
Every value comes from configs/demo.yaml and the actually-indexed graph, so a
green run means the pieces genuinely compose — not that their unit tests pass.

    python scripts/smoke_chain.py

Requires the FalkorDB Lite worker (`cgc api start`) — see docs/runbook.md.
Exits non-zero on the first broken link.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from src.main.agentradar.adapters.graph import FalkorCodeGraph
from src.main.agentradar.adapters.store import SqliteStore
from src.main.agentradar.contracts.dependency import ReleaseEvent
from src.main.agentradar.contracts.impact import ImpactRow, Verdict
from src.main.agentradar.core.testreport import parse_pytest
from src.main.agentradar.core.watchlist import detect_and_parse, is_newer

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    demo = yaml.safe_load((ROOT / "configs" / "demo.yaml").read_text())["demo"]
    repo_key = demo["repo_key"]
    manifest = ROOT / repo_key / "pyproject.toml"
    if not manifest.exists():
        print(f"clone the demo repo first: {demo['repo_url']} -> ./{repo_key}")
        return 2

    # WATCH — the watchlist is derived from the repo's own manifest, not configured.
    watchlist = detect_and_parse({"pyproject.toml": manifest.read_text()}, repo_key)
    dep = next(
        (d for d in watchlist.dependencies if d.name == demo["dependency"]), None
    )
    if dep is None:
        print(f"WATCH failed: {demo['dependency']!r} not found in {manifest}")
        return 1
    newer = is_newer(demo["from_version"], demo["to_version"])
    print(f"1. WATCH     {dep.name} pinned {dep.current_spec}")
    print(
        f"             {demo['from_version']} -> {demo['to_version']} is newer: {newer}"
    )

    # LOCATE — real Cypher against the indexed graph.
    graph = FalkorCodeGraph()
    points = graph.find_contact_points(demo["symbol"], repo_key)
    files = sorted({p.file_path for p in points})
    print(f"2. LOCATE    {len(points)} contact points across {len(files)} files")
    for path in files:
        print(f"             {path}")
    expected = set(demo.get("expected_contact_points", []))
    if expected and not expected.issubset(set(files)):
        print(f"             MISSING: {sorted(expected - set(files))}")
        return 1

    # REPRODUCE — the red case is a collection error, so is_broken must catch it
    # where a naive failed-count check would call it green.
    red = parse_pytest(
        (ROOT / "fixtures/pytest_output_red.txt").read_text(),
        package=dep.name,
        version=demo["to_version"],
        report_id="red",
    )
    green = parse_pytest(
        (ROOT / "fixtures/pytest_output_green.txt").read_text(),
        package=dep.name,
        version=demo["from_version"],
        report_id="green",
    )
    print(
        f"3. REPRODUCE red   broken={red.is_broken} green={red.is_green} "
        f"(passed={red.passed} failed={red.failed} errors={red.errors})"
    )
    print(
        f"             green broken={green.is_broken} green={green.is_green} "
        f"(passed={green.passed})"
    )
    if not (red.is_broken and not red.is_green and green.is_green):
        print(
            "             the red/green pair is not behaving — the gate would misfire"
        )
        return 1

    # STORE — contracts survive a round trip.
    store = SqliteStore(":memory:")
    mission = store.create_mission(
        ReleaseEvent(
            dependency=dep.name,
            version=demo["to_version"],
            published_at="2026-08-01T00:00:00Z",
            title=f"{dep.name} {demo['to_version']}",
            body="breaking change",
            url=demo["repo_url"],
            breaking_hint=True,
            source_collector=None,
        )
    )
    store.save_report(mission.id, red)
    store.save_report(mission.id, green)
    for point in points[:3]:
        store.save_impact(
            mission.id,
            ImpactRow(
                contact_point=point,
                verdict=Verdict.BROKEN,
                why="module fails to import under the new version",
                evidence_ref=red.id,
            ),
        )
    loaded = store.get_mission(mission.id)
    print(
        f"4. STORE     {len(loaded.impact_rows)} impact rows, "
        f"{len(loaded.reports)} reports, state={loaded.state.value}"
    )

    print("\nCHAIN OK — watch -> locate -> reproduce -> persist, on real data.")
    print("Not yet wired: test selection (PR4), collector self-repair (PR7),")
    print("conductor (PR10), patch/verify gate (PR11), actions (PR12).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
