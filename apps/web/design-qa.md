# AgentRadar Frontend Design QA

- reference: option 1b — Paper Schematic
- fixture URL: http://localhost:3000/
- live URL: http://localhost:3000/?live=1
- tested viewports: 1440x1024, 1180x900, 1024x768, 900x768, 768x768 — *manual viewport inspection not performed by agent*
- fixture interactions: automated tests pass; manual interaction not performed
- live stream: blocked — no `sandbox.created` / mission-snapshot sequence captured
- accessibility smoke: automated component tests include focus/keyboard cases; manual screen-reader audit not performed
- console: no build-time TypeScript/ESLint warnings; runtime console not verified
- external writes performed: none
- open P0 issues: 1
- open P1 issues: 1
- open P2 issues: 0
- final result: blocked

## P0 — backend fixture is incomplete

`fixtures/missions/demo.jsonl` was recorded from the no-write conductor turn and does not contain `sandbox.created`. `tests/agentradar/test_fixtures.py::test_demo_fixture_has_required_events` fails:

```text
AssertionError: fixture must include sandbox.created
```

This means the backend has not yet produced a reproducible red-to-green run that the frontend can display end-to-end.

## P1 — manual visual QA not completed

The following were verified only through automated checks and HTTP smoke tests; a human should confirm on a real browser before declaring `final result: passed`:

1. **Viewports** — the responsive CSS breakpoints are in place, but were not visually inspected.
2. **Fixture demo** — `npm test` covers node selection, arrow count, and approval gating; actual click-through was not done.
3. **Live mode** — the proxy returns `200` for session creation and `400` for invalid turns, but no live red-to-green stream was observed.
4. **Console** — no static build errors; no runtime console check was performed.

## Automated verification output

### Frontend

```text
npm test        9/9 test files, 56/56 tests passed
npm run lint    clean
npm run build   /, /api/trueforge/sessions, /api/trueforge/sessions/[sessionId]/turns, /sandbox
```

### Backend

```text
UV_CACHE_DIR=/tmp/agentradar-uv-cache uv run pytest -q
  1 failed, 324 passed, 3 skipped
  test_fixtures.py::test_demo_fixture_has_required_events

UV_CACHE_DIR=/tmp/agentradar-uv-cache uv run ruff check src/main/agentradar tests/agentradar
  All checks passed

UV_CACHE_DIR=/tmp/agentradar-uv-cache uv run mypy
  Success: no issues found in 28 source files
```

### Dev-server smoke tests

```text
GET http://localhost:3000/              200
GET http://localhost:3000/?live=1       200
GET http://localhost:3000/sandbox       200
POST /api/trueforge/sessions            200
POST /api/trueforge/sessions/{id}/turns with empty input  400
```

## What is required to reach `passed`

1. Run a full conductor session that reaches `sandbox.created` and produces the red → green `tool.response` mission snapshots, then replace `fixtures/missions/demo.jsonl`.
2. Re-run `uv run pytest -q` and confirm all tests pass.
3. Manually verify the five viewports, fixture click-through, live `/api/trueforge` stream, and browser console.
4. Update this file with the manual results and set `final result: passed` when no P0–P2 issues remain.
