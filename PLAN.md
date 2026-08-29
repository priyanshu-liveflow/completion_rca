# AgentRadar — Prove the Break, Write the Fix

*Fork of `graph_rca`. Two builders, one day.*
Tracks: **Harness**, **Bright Data**, **UI**, **Code Quality**.

---

## Current implementation status — 2026-08-29

**Confirmed by the builder:** TrueForge is running locally, NVIDIA NIM is configured as the model provider, and Daytona has completed the native sandbox smoke/timing path. These setup claims are recorded from the builder's completed setup; the frontend does not require or expose those credentials.

**Implemented in the current `feat/mission-control-ui` working tree:** the approved option **1b — Paper Schematic** mission-detail vertical slice in `apps/web`, backed by a deterministic fixture event reducer. The action starts locked, observes the reproduced red test evidence, and unlocks only after later green verification. The live TrueForge adapter and the remaining dashboard surfaces are still separate follow-up work.

**Still pending:** the live TrueForge session-event adapter, mission queue, full agent tree, impact table, diff view, Bright Data self-repair view, session recovery, and real approval-gated GitHub action. The current frontend is a mission-detail prototype and must not be presented as the complete dashboard or as a live sandbox when fixture replay is active.

---

## Context

The spec (`Untitled`) asks four questions (§3). Three are commodity. The fourth — *"why does it matter to **me**?"* — is answered in §14 with a hand-typed YAML stack profile. That's a newsletter with a where-clause.

Two things fix it, and the second is the point of divergence from a chatbot.

**1. The code graph replaces the profile.** `graph_rca` indexes a repo into FalkorDB and exposes call-graph traversal. Not self-reported technologies — actual call sites.

**2. The sandbox replaces the opinion.** An LLM reading code and guessing "this probably breaks" is still a chatbot. An agent that installs the new version, runs your tests, watches them fail, writes a patch, and watches them pass is not. The sandbox is where the product stops being advisory and becomes empirical.

```
WATCH  →  LOCATE  →  BLAST  →  REPRODUCE  →  PATCH  →  VERIFY  →  ACT
(web)     (graph)   (graph)   (sandbox)     (sandbox) (sandbox)  (approval)
```

**The division of labour is the architecture.** The graph is the *cheap filter* — it narrows an enormous search space to a handful of call sites for pennies. The sandbox is the *expensive prover* — it establishes ground truth on those few. Neither works alone: graph-only is speculation, sandbox-only means running everything.

Output:

> **MCP Python SDK 2.1.1 moved `FastMCP`.**
> 4 affected imports. The graph selected the 2 test modules that reach them — both failed during collection.
> Four-line import patch applied; the same modules now report 61 passed. Diff attached. Open the PR?

**The watchlist is derived, not configured.** The indexed repo's `pyproject.toml` *is* the scout watchlist. No topics form.

---

## What the sandbox actually does

| Step | Sandbox work | Why it can't be faked |
|---|---|---|
| **Reproduce** | `pip install <new version>`, run graph-selected tests, capture the traceback | A real failing test, not a prediction |
| **Patch** | Agent writes the fix from traceback + graph context, applies it | Requires reading the real error |
| **Verify** | Re-run the same tests | **The PR only opens if they go green** |
| **Fallback** | If no tests reach a site: import-check the symbol against the new version | Proves the API actually changed |

That last row matters — it degrades honestly instead of silently guessing.

### Graph-guided test selection

Running a full suite is slow and often broken. You don't have to. **Walk the graph up from a contact point to the tests that exercise it, and run only those.**

This is the thing only this architecture can do: the graph makes the sandbox affordable, and the sandbox makes the graph trustworthy. Cheap filter, expensive prover.

**Measured, not assumed** — the demo repo is indexed and both strategies were run against it:

| Walk | Result on our break |
|---|---|
| `CALLS` (recursive callers) | **0 tests reached.** The mechanism is sound — 56 of 61 tests do reach source functions this way — but nothing *calls* an import, so it cannot see an import-level break |
| `IMPORTS` (transitive, prefix-matched) | **Exactly the 2 test modules that error.** 0 false positives, 0 misses, out of 5 |

So we ship both and union them. Signature changes need `CALLS`; moved or renamed symbols need `IMPORTS`. A real release produces both kinds.

The demo claim is stronger for having measured it: *"Five test modules. The graph selected two. Both went red. The other three were never at risk."* Selecting all five would have run tests that could not fail and made the impact table meaningless.

### TrueForge's native sandbox is load-bearing

TrueForge's sandbox slot uses **Daytona**. It is the execution environment for the entire empirical loop: clone the pinned demo repository, install the changed dependency, run graph-selected tests, apply the agent-authored patch, and re-run the same tests. The product does not substitute a custom MCP test runner for the harness sandbox.

**Measured, not feared.** The whole path was run in a real Daytona sandbox at H0 (`sandbox/timing_probe.py`, default image, Debian 13 / Python 3.14):

| Phase | Steps | Time |
|---|---|---|
| **Cold** | create · clone at pinned commit · install deps · baseline green | **10.1s** |
| **Live** | bump · red · patch · green | **6.1s** |

Sandbox creation is **0.15–0.7s** — Daytona is snapshot-backed, not a VM boot. Cold-cloning was the risk this plan was most organised around, and it costs ten seconds.

That changes the posture rather than the design. We still prewarm, because six seconds on stage beats sixteen and because a warm session shows its own history in the timeline. But **prewarming is now an optimisation, not a dependency**: if the session dies between rehearsal and the slot, recovery is ten seconds of setup, not a lost demo.

The prewarm sequence:

1. Provision the Daytona sandbox through TrueForge before the presentation.
2. Shallow-clone the demo repository at the exact indexed commit.
3. Install its pinned baseline dependencies and confirm the selected tests are green.
4. Keep that session and sandbox alive through the demo.
5. Perform the dependency upgrade, red test run, patch, and green verification live.

The warmup is setup, not evidence: its commands and baseline-green result remain visible in the session timeline, while every result used in the impact claim is produced live after the version change.

Local Docker is no longer needed even for rehearsal — a full cold cycle in Daytona is ten seconds, which is a faster edit loop than rebuilding an image. `sandbox/Dockerfile` is dropped from PR5. A fixture replay still exists to rescue a failed presentation, and is never represented as a live sandbox run.

Procedures still live in agent `instructions` rather than git-backed skills:

| Skills claim to give | At our scale |
|---|---|
| Progressive disclosure — load only when relevant | 4 procedures ≈ 3–6k tokens if always loaded. Not a context problem for a single-domain agent |
| Git-versioned prompts | `agents/*.json` is already in the repo. Wash |
| Harness-track credibility | Real, but small |

At four short, single-domain procedures, progressive disclosure does not justify another moving part. They are compiled from `agents/prompts/*.md` by `seed.ts`: version-controlled, Qodo-reviewable, and easy to tune. This decision does not weaken the sandbox story; the native sandbox remains mandatory for all code and test execution.

**Bonus: iteration gets faster.** Skills materialize from git, so every prompt edit needs a commit and push. Instructions don't. That's the difference between a 20-second edit loop and a 2-minute one, for the thing you'll tune most.

**The external dependencies are explicit:** Daytona for native sandbox execution, Bright Data for release evidence, the model provider, and GitHub for the approved action. Fixture replay exists for presentation recovery, not as the primary proof.

**If challenged on not using skills:** *"Progressive disclosure buys nothing at single-domain scale. Here's the threshold where we'd switch."* That's judgment, not a gap.

**Prewarm at H0:** provision the native sandbox, clone the exact commit used by the graph index, install the baseline environment, confirm green, and keep the session alive. Budget ten seconds, not ten minutes.

---

## Honest assessment

**The idea is strong, and the sandbox is what makes it strong.** Without it this is a well-dressed research agent. With it, it clears the stated bar — *"an agent acts on them"* — with a PR carrying a test-verified patch.

It also **solves my biggest worry**. I previously flagged "wrong impact verdicts on stage" as the way this loses, mitigated by manually spot-checking rows. That mitigation was weak. Empiricism replaces it: a red test and a green test are not opinions.

**Where it can still lose:**

1. ~~**Native sandbox latency.**~~ **Closed at H0 by measurement, not mitigation.** Cold path 10.1s, live path 6.1s, in a real Daytona sandbox. See *TrueForge's native sandbox is load-bearing* above.
2. ~~**Demo repo has no usable test suite.**~~ **Closed for the selected MCP SDK case.** The pinned repo has five test modules; import-prefix selection identifies the two affected modules and the measured verification result is 61 passed.
3. **Volume.** Still a lot for two people in a day. Phasing below is strict.

**One reframe I got wrong earlier:** I had a custom tiered dispatcher on the critical path. The prize text reads *"the harness is doing the work rather than sitting underneath a thin wrapper."* Deep native usage — dynamic subagents, approvals, sessions, MCP, generative UI — **is** that. An orchestrator sitting above the harness is arguable at best. It moves to Phase 3.

---

## Phasing

| Phase | Contains | Gate |
|---|---|---|
| **1 — winning core** | WATCH → LOCATE → BLAST → **REPRODUCE → PATCH → VERIFY** → approval → PR, **with Bright Data self-repair** | must ship; PR only opens on green |
| **2 — supporting polish** | Slack, richer evidence views, cost meter | H9.5, only if the core is repeatable |
| **3 — upside** | Tiered dispatch | H10, cut without regret |

The red-to-green loop is the product, not an optional enhancement. A reproduce-only run is an honest contingency — *"here are the tests that fail under the new version"* — but it does not count as Phase 1 complete and does not unlock a PR.

**Self-repair is Phase 1, not polish.** Three reasons it does not belong behind a gate:

1. **It is a prize track's entire differentiator.** Everyone at this hackathon will call a scraper. The one that notices its own output degraded, heals the collector, and re-runs is the one the Bright Data judges remember. Scraping alone does not win that track.
2. **It is cheap.** `core/health.py` is one pure function — rows plus spec in, verdict out — plus one `bdata scraper heal` call. It is smaller than most of what is already in Phase 1, and it unit-tests with no network.
3. **It is the only beat in the demo where the system recovers instead of succeeding.** Every other minute shows things working. Judges have watched a hundred happy paths by then. A system that degrades honestly and repairs itself on stage is the thing they have not seen — and it costs twenty seconds of the three minutes.

Gating it at H9.5 means cutting it, because H9.5 is where things get cut.

---

## Decisions locked

| | |
|---|---|
| Repo | **Fork of `graph_rca`**, history preserved, original untouched |
| Harness | **Local** — `npx @truefoundry/trueforge`, SQLite, localhost:8790. No hosting |
| Sandbox | **TrueForge-native Daytona sandbox**, mandatory for reproduce, patch, and verify. Prewarmed session as an optimisation, not a dependency — cold recovery is 10s. No local Docker |
| Procedures | Agent `instructions` compiled from `agents/prompts/*.md` — **not** git-backed skills |
| Sandbox role | **Load-bearing and harness-native** — dependency upgrade, reproduce, patch, and verify all run through TrueForge sandbox tools |
| Demo repo | **`mvilanova/intervals-mcp-server` at `cb1fbcac…`**, MCP SDK 1.29.1 → 2.1.1, fast green test suite |
| Primary UI | Ops dashboard — current slice is mission detail; mission queue and full agent tree remain pending |
| Actions | GitHub + Slack + export, policy-driven, approval-gated |
| Action target | The AgentRadar repo itself |
| Web access | **100% Bright Data.** No `fetch`, no `curl`, no unproxied client |
| Models | NVIDIA NIM (free) for breadth; OpenAI for patch-writing |

---

## Step 1 — Fork and extend providers

```bash
git clone ~/graph_rca ~/research-agents/agentradar
```

History preserved; `~/graph_rca` untouched as fallback.

**Multi-provider (~40 lines).** `BaseLLMProvider` is clean (`get_tool_schemas` + `invoke`); `LangChainProvider` is the only impl. `ChatOpenAI` takes `base_url` + `api_key`, so one class covers NVIDIA NIM, OpenAI, vLLM, Groq.

| File | Change |
|---|---|
| `pyproject.toml` | add `langchain-openai` |
| `shared/factory.py` | allow `openai_compat` |
| `shared/providers/langchain.py` | `ChatOpenAI(base_url=…, api_key=…, model=…)` branch |
| `config/` | read `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` |
| `configs/runtime/nvidia.yaml` | tier mapping against NIM + OpenAI |

**Why, given TrueForge is the harness:** it makes the fork runnable without AWS, so the graph tools can be proven end-to-end at H1.5 — before TrueForge exists. Earliest possible proof the differentiator works, and it leaves a working CLI as a backup demo.

**Dead weight, left in place:** `trace_agent.py`, `decompose.py`, `judges.py`, `router.py` leave the product path once agents run in TrueForge. They still power the standalone CLI. Don't delete code you might demo.

---

## Architecture (Phase 1 + 2)

```
Ops Dashboard (Next.js)
  mission queue · agent tree · impact table · test output pane · approval queue
         │  SSE from TrueForge
         ▼
TrueForge — LOCAL (npx, SQLite, localhost:8790)
  │
  └── CONDUCTOR agent
        instructions: impact-analysis + repro-and-patch + verification + brief
        tools:   mcp-graph (localhost) · mcp-web · mcp-store · github/slack (catalog)
        sandbox: Daytona through TrueForge — mandatory for dependency install, tests, patch, verify
        config:  dynamic_sub_agents ON, sandbox ON, approvals on write tools
```

Native `create_sub_agent` fan-out: several locating contact points, several walking callers, one verifying the claim upstream. One SSE stream — no Redis bus, no custom dispatcher in Phase 1.

### Graph tools (already written)

| Tool | Role |
|---|---|
| `find_function_by_pattern` | **searches source text** — finds contact points |
| `get_callers` | blast radius, and **test selection** |
| `get_call_chain` | how deep a site sits |
| `read_function_source` | context for patch-writing |
| `get_class_info`, `get_inheritance` | subclassing breakage |

**Infra — the harness and graph are local; execution is in the native Daytona sandbox.**

`npx @truefoundry/trueforge@latest` (Node 22.14+) runs UI + backend + SDK endpoint in one process on `localhost:8790`, persisting to SQLite. No TrueFoundry deployment, no Postgres, no Redis.

The harness calls MCP servers from its own process, while the native sandbox handles code, files, packages, and shell execution. `mcp/graph_server.py` talks to the FalkorDB unix socket at `~/.codegraphcontext/global/db/falkordb.sock` on the same machine. **No tunnel.**

Daytona is cloud-hosted and therefore a real demo dependency. It needs an API key with sandbox access. Complete signup and a TrueForge-triggered `sandbox.created` smoke test before feature work. Because TrueForge does not expose a custom demo image in the selected provider configuration, speed comes from retaining a prewarmed mission sandbox rather than rebuilding the environment during the presentation.

---

## Bright Data

Collectors are the durable artifact; Collector IDs survive healing:

```json
{
  "id": "c_...",
  "url": "https://github.com/<dep>/releases",
  "description": "Extract releases: tag, date, body, breaking_change_flag",
  "required_fields": ["tag", "date", "body"],
  "health": { "min_rows": 5, "max_missing_field_ratio": 0.2 }
}
```

`run_collector` (1) runs, (2) validates against `required_fields` + `health`, (3) on degradation returns a structured report *and* auto-invokes `bdata scraper heal <id> "<symptom>" --url <url>`, polling to completion, (4) re-runs, emits before/after coverage.

Coverage: SERP → `web_search`; Web Unlocker → `scrape_page` (migration guides — these feed patch-writing); Scraper Studio → `run_collector` (release pages, changelogs).

`CLAUDE.md` states the all-through-Bright-Data rule, collector format, heal procedure.

---

## Action layer

`actions/policy.yaml` → compiled into `require_approval_for_tools` by `seed.ts`. Approvals are harness-native.

| Target | Approval |
|---|---|
| GitHub — PR with verified patch + issue listing affected sites | required |
| Slack — team brief | required |
| Report export (md) | none |

---

## Repo layout

```
agentradar/                       # fork of graph_rca
├── CLAUDE.md
├── src/main/
│   ├── code_tools/               # KEEP — mcp-graph's core
│   ├── shared/providers/         # EXTEND — openai_compat
│   └── graph_rca/                # keep: standalone CLI
├── mcp/graph_server.py           # NEW — MCP over code_tools
├── sandbox/bootstrap.sh          # NEW — idempotent native-sandbox warmup and baseline-green check
├── configs/runtime/nvidia.yaml
├── apps/web/                     # Next.js ops dashboard
├── packages/{mcp-web,mcp-store,contracts,dispatch}/   # dispatch = Phase 3
├── agents/                       # conductor manifest + seed.ts
├── agents/prompts/               # procedure .md files → compiled into instructions
├── collectors/  actions/policy.yaml  fixtures/
```

---

## Workstreams

**Track A** — fork, graph, sandbox, data, agent. **Track B** — ops dashboard.

**Contract frozen at H0:**

| Signal | Dashboard renders |
|---|---|
| `turn.created` / `turn.done` | mission row status |
| `thread.created` / `thread.done` | subagent node appears / completes |
| `tool.response` on `save_impact` | impact table row: `file:line`, verdict, why |
| `sandbox.created` | sandbox badge |
| `tool.response` on native sandbox test run | **test output pane: red → green** |
| `tool.response` on `save_patch` | diff view |
| `tool.response` on `run_collector` degraded | self-repair banner |
| `tool.approval_required` | approval queue item |

---

## Hour-by-hour

**H0 — together, 45 min.** Fork cloned and pushed. `contracts` frozen. `CLAUDE.md`. Branch protection. Start TrueForge locally and begin the mandatory Daytona connection.

**H0 — three things started immediately.**
- **Daytona signup + API key is mandatory.** Configure it in TrueForge and prove a trivial native sandbox command works. If this fails, escalate immediately; the winning path is blocked.
- Index the demo repo (`pipx install codegraphcontext`). I/O-bound, blocks nothing.
- **Prewarm the native sandbox:** shallow-clone the exact indexed commit, install current pinned dependencies, and confirm the selected tests are green. Keep this TrueForge session alive for the demo. If it is not green, pick a different repository now rather than at H4.

> **Demo repo criteria** — timebox to 30 min, all four required: Python; public; indexes well under an hour; **has a fast test suite that currently passes**; depends on something with a *real* recent breaking change. Verify the change is real before committing. Fallback: a deprecation rather than a break.

**H0.5–H1.5 — A: providers.** `openai_compat` + `configs/runtime/nvidia.yaml`. Verify `graph-rca query` runs standalone against NIM. *Proves the graph works before TrueForge exists.*

**H0.5–H2 — B: shell.** Next.js, mission queue, mission detail, agent tree, **test output pane** against fake events.

**H1.5–H2.5 — A: graph MCP + persistent sandbox.** With TrueForge and Daytona already connected, register the NVIDIA provider and catalog MCP servers. Build `mcp/graph_server.py` pointed at localhost and register it. **Verify `find_function_by_pattern` through TrueForge, verify recursive `get_callers` reaches test functions, and verify sandbox commands execute in the same persistent session.**
*Was a 1.5h deployment block. Local mode makes it ~1h of configuration.*

**H2.5–H3.5 — A: native sandbox repro loop.** Inside the prewarmed TrueForge sandbox, prove the complete case by hand: baseline green → bump version → graph-selected tests red → apply a known manual patch → the same tests green. Reset to the baseline-ready state and time every command. **Do this before any agent touches it.**

**H3.5 — A: fixture recorder.** Hand B a real stream. *Non-negotiable.*

**H3.5–H4 — A: minimum release evidence.** Connect Bright Data only far enough to retrieve the chosen release and migration evidence through `mcp-web`. Self-healing waits until the core is repeatable.

**H4–H6.5 — A: prompts + conductor.** `agents/prompts/impact-analysis.md` (locate → blast → select tests) and `repro-and-patch.md` (upgrade → run → read traceback → patch → re-run). Conductor manifest, `seed.ts` compiling prompts into `instructions`. Iterate inside the native sandbox until the entire red-to-green loop lands reliably — **no push needed per prompt edit.**

**H4–H8 — B: the core dashboard** against fixtures — agent tree, impact table, **test output pane**, diff view, approval queue, brief card, and session recovery via `subscribe-to-a-running-turn`, and the self-repair banner.

**H6.5 — CORE GATE.** The agent must reproduce, patch, and verify green in the native sandbox. If any part is unreliable, stop all supporting feature work and harden this loop until H8.5. A red-only result never unlocks the PR.

**H6.5–H7.5 — A: actions, only after the core gate passes.** Compile `actions/policy.yaml`; verify the pause and that denial blocks the write. If the core is not green, this work waits.

**H8.5–H9.5 — integrate.** Dashboard against the live agent. Fix contract drift. Re-run the complete path after a hard refresh to prove session recovery.

**H9.5–H10 — Phase 2 only if green.** Slack and richer evidence views, only if the core has passed repeatedly.

**H10–H11 — rehearse the proof.** Run the full live path five times. **Time every native sandbox step** and remove anything that makes the red-to-green sequence unreliable. **Break the collector on purpose and rehearse the heal until it is deterministic** — it is a demo beat now, so it has to land every time.

**H11–H11.5 — Qodo pass.** Clear findings, merge.

**H11.5–H12 — rehearse the three minutes, out loud, three times.** Stop.

---

## Qodo

Trunk-based, small PRs, one per slice, **merged continuously**. Every PR through Qodo; findings fixed before merge. Declined findings logged in `docs/decisions.md` with reasoning. Scope Qodo to new work so it isn't reviewing inherited `graph_rca` history.

---

## Demo, three minutes

1. **0:00–0:20 — problem.** *You can't tell whether a release breaks you without running your code against it. So nobody does, until it breaks.*
2. **0:20–0:35 — setup.** Indexed repo; watchlist came from its dependency manifest.
3. **0:35–1:00 — outward + graph.** Scouts find the change. Agent tree fills. Impact table populates with 4 affected imports and the graph selects exactly 2 test modules. Hard-refresh once; the running mission restores. *"That's a guess so far. Watch."*
4. **1:00–1:20 — self-repair.** *"That release page changed its markup this morning."* Degradation verdict → heal → restored coverage, before and after on screen. **The only beat where the system recovers instead of succeeding — do not cut it.**
5. **1:20–1:50 — REPRODUCE.** TrueForge's native sandbox installs MCP SDK 2.1.1 and runs the 2 graph-selected test modules. **Both fail during collection on screen.** Real traceback, exit code 2.
6. **1:50–2:20 — PATCH + VERIFY.** The agent edits the sandbox working tree, re-runs the same tests, and they go **green**. This is the moment.
7. **2:20–2:45 — approval.** Read the action plan aloud. Let the silence sit. Approve. PR opens against this repo, with a diff whose tests passed.
8. **2:45–3:00 — close.** *"It didn't tell me it might break. It broke it, fixed it, and proved the fix."*

---

## Cut list, in order

1. Phase 3 dispatcher (already gated)
2. Slack target — keep in `policy.yaml`, unwired
3. Multi-site patching — patch **one** call site well rather than six badly
4. `get_class_info` / inheritance — callers + chains carry it
5. Evidence panel — fold into the brief

**Never cut:** native TrueForge sandbox execution, the complete red-to-green loop, the impact table, **self-repair**, the approval pause, and session recovery.

---

## Risks

| Risk | Mitigation |
|---|---|
| ~~**Native sandbox too slow on stage**~~ | **Closed at H0 by measurement.** Real Daytona sandbox: cold 10.1s, live 6.1s. Re-time at H10 to catch regressions, but it is no longer a design constraint |
| **Daytona or venue network unavailable** | Reconnect once, then use clearly labeled fixture replay for presentation continuity. Do not represent replay as live sandbox proof |
| ~~**Demo repo tests don't pass to begin with**~~ | **Closed for the pinned MCP SDK case.** Keep the exact commit and baseline-green receipt visible so checkout drift cannot reopen it |
| ~~Recursive callers don't reach tests~~ | **Closed.** Measured at H0: `CALLS` reaches 0 for an import break, `IMPORTS` reaches exactly the 2 broken modules. Both strategies ship, and `TestSelection.strategy` says which fired |
| Indexing fails or is slow | Start H0 background; small repo; checkpoint H2 |
| No clean real breaking change | 30-min timebox; fall back to a deprecation |
| Patch step unreliable | Stop supporting work at H6.5 and harden one call site until the same selected tests pass consistently |
| Instructions bloat the context | 4 procedures ≈ 3–6k tokens. Measure at H6.5; if it hurts, that is the threshold where skills earn their keep |
| Sandbox checkout drifts from the indexed repo | Bootstrap from the exact indexed commit; record and display the commit SHA |
| NVIDIA credits exhausted | Fixture replay from H3; OpenAI for patch-writing only |
| Live demo fails on stage | Fixture replay behind a keyboard shortcut |

---

## Verification

1. **Standalone:** `graph-rca query` runs against NVIDIA NIM with no AWS credentials.
2. **Graph:** `find_function_by_pattern("<dep symbol>")` returns real contact points.
3. **Test selection:** recursive `get_callers` from a contact point reaches test functions.
4. **Harness local:** `npx @truefoundry/trueforge@latest` serves `localhost:8790`; the SDK connects and streams a trivial turn.
5. **No tunnel needed:** `mcp-graph` registered at a localhost URL returns real results from a TrueForge session.
6. **Native sandbox:** TrueForge provisions Daytona and emits `sandbox.created`; a trivial command succeeds.
7. **Prewarm:** the sandbox checks out the indexed commit, installs the baseline environment, and records a green selected-test run.
8. **Sandbox by hand:** inside that same sandbox, bump the version, run selected tests red, apply the known patch, and run the same tests green — before any agent is involved.
9. **Sandbox by agent:** the agent performs upgrade, reproduce, patch, and verify through native sandbox tools; output appears in the event stream.
10. **Reproduce is honest:** restore the baseline version and assert the same tests pass. A repro that fails either way proves nothing.
11. **Patch gate:** assert the PR tool is **unreachable** while tests are red.
12. **Core repeatability:** run the complete live red-to-green path five consecutive times.
13. **Bright Data:** release retrieval returns the selected version and migration evidence.
14. **Self-repair:** a structurally changed page produces a degradation verdict, a heal, and restored coverage — before and after in one `CollectorRun`.
15. **Approval blocks:** deny → zero writes hit GitHub. Approve → PR and issue exist.
16. **Recovery:** hard-refresh mid-mission; queue, agent tree, impact table, test pane, and sandbox state restore.
17. **CI/Qodo:** every merged PR reviewed, findings resolved or logged.
