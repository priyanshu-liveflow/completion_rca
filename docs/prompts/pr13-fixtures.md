# PR13 — `chore(fixtures): event recorder`  ·  **Composer**  ·  cut if late

The offline escape hatch. If the live demo dies on venue wifi, this replays a
real mission from disk with zero network. Build it only once PR12 is merged.

## Working rules

```bash
cd ~/research-agents
git worktree add ~/research-agents-pr13fix -b chore/fixtures origin/main
cd ~/research-agents-pr13fix
```

`git branch --show-current` before every commit. Never touch `main`.

## Files

```
scripts/record_fixtures.py       NEW
scripts/replay_fixture.py        NEW
fixtures/missions/<name>.jsonl   GENERATED — commit at least one real capture
```

Stdlib only, matching `scripts/configure_trueforge.py` — it already talks to
TrueForge over SSE with no dependencies. Read it before starting; do not add a
library.

## `scripts/record_fixtures.py`

```
python scripts/record_fixtures.py --agent conductor --prompt "<mission text>" \
    --out fixtures/missions/demo.jsonl
```

Open a session, post a turn, subscribe to the SSE stream, write **every** event
as one JSON object per line, in arrival order, with a relative `t_ms` since the
first event. Stop on `turn.done`.

Turn shape, verified against a running instance — get this wrong and you get a
200 with a live stream that fails at `turn.done` with "messages must not be
empty" and zero tokens:

```
POST /api/v1/sessions        {"agent": {"name": "conductor"}}
POST /api/v1/sessions/{id}/turns
     {"input": [{"type": "user.message", "content": "..."}]}
```

`{"message": ...}` and `{"prompt": ...}` are the trap. Use the array form.

Event names, observed live: `turn.created`, `turn.done`, `model.message`,
`model.message.delta`, `tool.response`, `tool.approval_required`,
`tool.response_required`, `thread.created`, `thread.done`, `mcp.initialize`,
`mcp.auth_required`, `sandbox.created`.

**Record everything, filter nothing.** An unknown event name is still written
verbatim — a recorder that drops what it doesn't recognize is worthless the
first time the API adds an event.

**Redact before writing.** Never let an API key, token, bearer header, or
connection string reach a committed file. Scrub known key prefixes (`dtn_`,
`nvapi-`, `sk-`, `ghp_`) and any `authorization` header from every payload, and
assert in a test that a captured fixture contains none of them. This file gets
committed to a public repo — treat it that way.

## `scripts/replay_fixture.py`

```
python scripts/replay_fixture.py fixtures/missions/demo.jsonl [--speed 2.0]
```

Replays to stdout honoring the recorded `t_ms` gaps, so it looks like a live
run rather than a wall of text. `--speed` scales the delay; `--speed 0` dumps
instantly. No network, no TrueForge, no FalkorDB — it must run on a laptop in
airplane mode. That is the entire point.

## Acceptance

- Record one real mission end to end against the live conductor; commit the
  JSONL.
- The capture contains `sandbox.created` and at least one `tool.response` — if
  it doesn't, you recorded a turn that never reached the sandbox, and it is
  useless as a fallback.
- Replay it with the network **off** and confirm the output is legible as a
  demo.
- A test asserts no secret prefix appears in any committed fixture.
- `ruff check`, `python scripts/check_layering.py`, `pytest tests/agentradar -q`
  all green.

Cut this without regret if the clock runs out — it is item #1 on the cut list
in `docs/build-plan.md`. But if the wifi is bad at the venue, it is the only
thing standing between you and a dead demo.
