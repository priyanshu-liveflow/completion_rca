# Connected workflow runbook

For a no-credentials first run, use the [README quick start](../README.md).
These steps concern the live dependency workflow. Older troubleshooting notes
below record the original environment and may differ from current service plans.

## Prerequisites

- Python 3.11+, uv, Git, and Node.js 22.14+.
- `uv sync --group dev`, `npm ci --prefix agents`, and `npm ci --prefix apps/web`.
- A configured FalkorDB Lite index. Clone the target at the commit in
  `configs/demo.yaml`; index its source **and tests**, with `IGNORE_TEST_FILES=false`.
  Run `uv run cgc api start --host 127.0.0.1` and leave the worker alive.
  `FALKORDB_SOCKET_PATH` must match the worker if its socket is not in the default location.
  The Lite worker needs a Python 3.12+ environment with `falkordblite`. Verify
  that FalkorDB really started: newer indexers can fall back to KùzuDB, which
  AgentRadar's FalkorDB adapter cannot read. A successful index command alone
  does not establish that the required backend is available.
- Bright Data CLI (`bdata`), an API key, and configured SERP/Unlocker zones.
  Collector IDs in `collectors/` are account-bound hackathon artifacts; configure
  collectors in your own account when reproducing the workflow.
- Daytona access and an available model provider. `configure_trueforge.py`
  currently requires `NIM_KEY` and `DAYTONA_API_KEY`; the checked-in conductor
  additionally needs the OpenAI model named in `agents/conductor.json`.
- GitHub CLI authentication for the intended PR target.

Copy `.env.example` to `.env` and fill only the needed settings. The configuration
script reads the root `.env`; launch MCP processes with `uv run --env-file .env`
so the Bright Data credentials/zones reach the web adapter. Keep secrets out of
terminal output and sandbox commands.


The service commands below assume the repository root as the working directory.
Model availability, quotas, and timings in the troubleshooting notes are historical observations.

## Bring the stack up

Order matters: the MCP servers must be listening before `seed.ts` registers
them, and TrueForge must be up before either.

```bash
npx @truefoundry/trueforge@latest          # localhost:8790, Node 22.14+
uv run python scripts/configure_trueforge.py      # model + sandbox providers

uv run --env-file .env python -m src.main.agentradar.mcp.graph_server  --port 8768   # needs FalkorDB
uv run --env-file .env python -m src.main.agentradar.mcp.web_server    --port 8766   # needs bdata
uv run --env-file .env python -m src.main.agentradar.mcp.store_server  --port 8767
uv run --env-file .env python -m src.main.agentradar.mcp.github_server --port 8769   # needs gh auth

cd agents && npm ci && npx tsx seed.ts
```

After seeding, start the frontend with `npm run dev --prefix apps/web -- --hostname 127.0.0.1`
and visit `http://localhost:3000/?live=1`. Resolve live GitHub approvals in TrueForge;
the dashboard currently streams evidence but does not submit live approval decisions.
Refreshing the dashboard starts a new session.

## Port map

| Server | Port | Notes |
|---|---|---|
| TrueForge | 8790 | |
| web | 8766 | |
| store | 8767 | |
| graph | **8768** | **not 8765** |
| github | **8769** | |

The graph server does not use 8765. That port has been occupied by an
unrelated local service, and a foreign server answering `404` on `/sse` is
invisible from TrueForge's side: `seed.ts` prints `registered` because
registration only stores a URL string. Nothing health-checks it. The failure
surfaces mid-mission as `Failed to list tools for 'graph'`, which costs the
entire locate step.

**Check the URLs answer before trusting a green seed:**

```bash
for p in 8766 8767 8768 8769; do
  printf "%s " $p; curl -s -m 3 -o /dev/null -w "%{http_code}\n" http://localhost:$p/sse
done
```

Four `200`s. Anything else means a server is down or something else owns the port.

## Restart servers after every merge

MCP servers keep serving the code they started with. A server launched from a
worktree that has since been deleted keeps running from the deleted path, so
tools merged later are simply absent — `select_tests` went missing this way and
the agent honestly reported it as unregistered. After merging, kill and
relaunch from the checkout you actually want:

```bash
ps aux | grep "[a]gentradar.mcp"     # confirm every path is the main checkout
```

## Model providers

Register OpenAI as `type: "openai"`, **never** `type: "custom"`.

TrueForge's `buildProviderOptions` branches on the type. `"openai"` routes to
the OpenAI provider and `/v1/responses`; anything else falls through to the
openai-*compatible* provider and `/v1/chat/completions`. On that path every
gpt-5.6 turn dies with:

```
Function tools with reasoning_effort are not supported for gpt-5.6-sol in
/v1/chat/completions. To use function tools, use /v1/responses.
```

The agent always carries TrueForge's built-in tools, so that is every turn.
`custom` stays correct for NVIDIA, which genuinely is only OpenAI-shaped.

Other provider facts, each verified the hard way:

- **`PUT`, not `POST`.** POST only creates. Editing the model list and
  re-POSTing answers `already exists` and silently changes nothing.
- **Omit `max_output_tokens` for gpt-5.x.** Setting it makes TrueForge send
  `max_tokens`, which those models reject in favour of `max_completion_tokens`.
- **A `429` with `total_tokens: 0` in under 200ms is quota, not rate limiting.**
  Rate limiting recovers; this does not. NVIDIA NIM answers an exhausted free
  tier this way. Switch providers rather than waiting it out.
- **TrueForge silently drops unknown manifest keys.** A `201` on agent creation
  does not mean the key you sent was kept. Read the agent back and check.

## Sandbox

Daytona's free tier caps *concurrent* CPU at 10, and a sandbox holds its share
until it stops. Every TrueForge session starts a new one.

It does not fail cleanly as it fills. Early runs clone fine; later ones report
`fork/exec /usr/bin/bash: no such file or directory`, which reads as a broken
image and is not; only when the tier is fully consumed does the honest error
appear — `Total CPU limit exceeded. Maximum allowed: 10`.

```bash
SANDBOX_AUTO_STOP_MIN=20  uv run python scripts/configure_trueforge.py   # development
SANDBOX_AUTO_STOP_MIN=120 uv run python scripts/configure_trueforge.py   # demo day
```

Short for development or leaked sandboxes exhaust the tier by lunchtime; long
for the demo or the prewarmed sandbox stops while you wait for your slot. The
script prints the active value — read it rather than assuming.

Reclaim leaked sandboxes at <https://app.daytona.io/dashboard/sandboxes>.
TrueForge exposes no sandbox management route.

## Bright Data

```bash
npm install -g @brightdata/cli     # provides `bdata` and `brightdata`
```

An API key alone is not enough. The account needs a **SERP** zone and a **Web
Unlocker** zone, created in the control panel, then:

```
BRIGHTDATA_API_KEY=...
BRIGHTDATA_SERP_ZONE=...
BRIGHTDATA_UNLOCKER_ZONE=...
```

Without them every call fails with `No zone specified`, which arrives *after*
authentication succeeds — so a valid key looks like a working setup until the
first real call. `bdata zones` lists what exists.

## Fresh checkout

`agents/node_modules` and `apps/web/node_modules` are not committed. `npx tsx
agents/seed.ts` fails with `ERR_MODULE_NOT_FOUND` until `npm ci` runs in
`agents/`. Do this before the venue, not at it.

## Offline fallback

No network, no TrueForge, no FalkorDB:

```bash
python scripts/replay_fixture.py fixtures/missions/demo.jsonl --speed 1.5
```

Replays a recorded mission honouring the original inter-event gaps. This is the
escape hatch if the live demo fails on stage — rehearse it once so the command
is muscle memory.

## Pre-demo checklist

1. `SANDBOX_AUTO_STOP_MIN=120 uv run python scripts/configure_trueforge.py`
2. Daytona dashboard: sandbox count near zero
3. Four `200`s from the port check above
4. `ps aux | grep agentradar.mcp` — every path is the main checkout
5. `npx tsx agents/seed.ts` — four servers registered, instructions inside 3-6k tokens
6. One throwaway conductor turn to confirm the model answers
7. `python scripts/replay_fixture.py fixtures/missions/demo.jsonl --speed 0` works
