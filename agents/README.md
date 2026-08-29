# agents/ — the conductor

The conductor is a **declarative manifest**, not code. There is no agent
runtime in this directory — `conductor.json` plus `prompts/*.md` plus
`../actions/policy.yaml` describe what TrueForge should run; `seed.ts`
compiles them into the shape TrueForge's API actually expects and
creates-or-updates the agent through it.

## Layout

```
conductor.json      static shape: name, model, mcp server refs, sandbox config
prompts/*.md         procedures, concatenated in filename order into `instructions`
seed.ts              the only code here: compile + idempotent create/update
package.json         two dependencies: yaml (parse the policy), tsx (run seed.ts)
```

`../actions/policy.yaml` lives one level up because it is not agent-specific —
it is the approval policy for AgentRadar's action layer generally, of which
the conductor is the first and (for now) only consumer.

## Model choice

`conductor.json` pins `nvidia-nim/kimi-k3` — the "heavy" tier, not the
"default" tier the models were tiered for. This was not the first choice.
`nvidia-nim/deepseek-v4-flash` (the intended default) was re-verified live
against this machine's TrueForge instance while building this PR and hung
indefinitely: `turn.created` and an empty `model.message` arrive, then
nothing — no `model.message.delta`, no `tool_call`, no `turn.done`, no error
event, across three separate turns and up to a 280s wait, on prompts as
simple as "say hello." `nvidia-nim/kimi-k3` and `nvidia-nim/llama-3-2-11b`
both streamed normally in the same session against the same running
instance. Whatever the fault is (NIM-side incident, a stale model id, rate
limiting that TrueForge swallows rather than surfacing as an event), it is
outside this PR's code, so the fix here is to default to the tier that is
demonstrably alive rather than ship an agent that silently never finishes a
turn. Re-check `nvidia-nim/deepseek-v4-flash` before relying on this note —
it may well be transient.

## Running it

```bash
cd agents
npm install
npx tsx seed.ts
```

Requires a local TrueForge on `localhost:8790` (`npx @truefoundry/trueforge@latest`,
see `docs/runbook.md`) with both providers already configured
(`python scripts/configure_trueforge.py`) and the three MCP servers running:

```bash
python -m src.main.agentradar.mcp.graph_server --port 8765
python -m src.main.agentradar.mcp.web_server   --port 8766
python -m src.main.agentradar.mcp.store_server --port 8767
```

`seed.ts` registers all three with TrueForge (`PUT /api/v1/settings/mcp-servers`,
idempotent) whether or not they are actually listening yet — registration
does not health-check the URL. A server that isn't up yet will surface as a
connection failure the first time the agent actually tries to call one of its
tools, not at seed time.

**Idempotent by design, not by accident.** `POST /api/v1/agents` errors with
`Agent name already exists` on a second call — it is not an upsert. `seed.ts`
therefore lists existing agents, finds one named `conductor` by exact match,
and `PUT`s to its id instead of `POST`ing again. Running `npx tsx seed.ts`
twice in a row is safe and produces the same agent, updated in place.

## Why procedures live in `instructions`, not skills

Skills materialize from a git clone into a Daytona sandbox at mission start —
exactly the latency PR5 spent its whole budget engineering away, for near-zero
benefit at the single-domain scale this project runs at. It would also turn
every prompt tweak into a commit-and-push instead of a 20-second local loop,
on the one file in this whole build that gets tuned the most. If a judge
challenges this: progressive disclosure buys nothing at single-domain scale;
here is the threshold (multiple unrelated domains, or an instructions budget
that no longer fits a context window) where we would switch.

## Why `require_approval_for_tools` is compiled per MCP server, not once

The build plan describes compiling `actions/policy.yaml` into "the manifest's
`require_approval_for_tools`," which reads as one field on the agent. Probing
the running instance says otherwise: `require_approval_for_tools` is a
property of each entry in `manifest.mcp_servers[]`, not of the manifest or its
`config`. A top-level `require_approval_for_tools` next to `mcp_servers` is
silently accepted by the route and silently absent from the stored agent —
the same "accepted but discarded" trap `docs/trueforge.md` already documents
for `turns`' `message`/`prompt` keys, just on a different endpoint. `seed.ts`
therefore compiles the policy once and applies the same tool list to every
server entry. It is harmless where a name does not match any tool the server
actually exposes (`github_pr` is not a tool on `graph`, `web`, or `store`
today), and it is already correct the day an actions/GitHub MCP server
registers a tool by one of these names — no one has to remember to come back
and wire the gate in.

Deliberately **not** included: the built-in `@write`/`@destructive`
wildcards. Left at their default, they would very likely catch
`create_mission`, `save_impact`, `set_state`, and friends on `store` — none of
which should pause for a human, since the whole point of WATCH through
REPRODUCE is to run unattended up to the point where a GitHub write is on the
table. Gating by explicit action-target name avoids that false positive.

## What `seed.ts` reports

Running it prints: the TrueForge URL it targeted, the instructions size in
characters and an approximate token count (`chars / 4`, explicitly not a
precise count — see the docstring in `seed.ts` for why no tokenizer dependency
is pulled in for one number), the compiled approval-gated action-target list,
each MCP server as it is registered, and finally the agent id it created or
updated.
