# AgentRadar Frontend Design QA

- reference: option 1b — Paper Schematic
- fixture URL: http://localhost:3000/
- live URL: http://localhost:3000/?live=1
- tested viewports: 1440x1024, 1180x900, 1024x768, 900x768, 768x768 — *manual viewport inspection not performed by agent*
- fixture interactions: automated component tests pass; manual click-through not performed
- live stream: recorded fixture `fixtures/missions/demo.jsonl` now passes backend replay tests; no new live turn has been attempted with OpenAI yet (key not supplied)
- accessibility smoke: automated component tests include focus/keyboard cases; manual screen-reader audit not performed
- console: no build-time TypeScript/ESLint warnings; runtime console not verified
- external writes performed: none
- open P0 issues: 0
- open P1 issues: 1
- open P2 issues: 0
- final result: blocked

## P0 — resolved

`fixtures/missions/demo.jsonl` was updated from `origin/main` and now contains the full red-to-green `sandbox.created` and `tool.response` mission-snapshot sequence. `tests/agentradar/test_fixtures.py` passes.

## P1 — manual visual QA not completed

The following were verified only through automated checks and HTTP smoke tests; a human should confirm on a real browser before declaring `final result: passed`:

1. **Viewports** — the responsive CSS breakpoints are in place, but were not visually inspected.
2. **Fixture demo** — `npm test` covers node selection, arrow count, and approval gating; actual click-through was not done.
3. **Live mode** — the proxy returns `200` for session creation and `400` for invalid turns, and the recorded fixture is replay-valid, but no live OpenAI red-to-green stream has been observed.
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
  338 passed, 3 skipped

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

1. Manually verify the five viewports, fixture click-through, live `/api/trueforge` stream, and browser console.
2. Run a fresh live conductor turn with OpenAI (supply `OPENAI_API_KEY`, `DAYTONA_API_KEY`, and `NIM_KEY` in `.env`; `NIM_KEY` is a placeholder because the NIM provider is already configured).
3. Update this file with the manual results and set `final result: passed` when no P0–P2 issues remain.
