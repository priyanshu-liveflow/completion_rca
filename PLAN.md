# AgentRadar — Prove the Break, Write the Fix

*Fork of `graph_rca`. Two builders, one day.*
Tracks: **Harness**, **Bright Data**, **UI**, **Code Quality**.

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

> **LangGraph 0.3 changed checkpoint persistence.**
> 6 call sites. I ran the 4 tests that reach them — 3 failed.
> Patch applied, tests green. Diff attached. Open the PR?

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

Running a full suite is slow and often broken. You don't have to. **`get_callers` applied recursively from a contact point reaches the test functions that exercise it.** Run only those.

This is the thing only this architecture can do: the graph makes the sandbox affordable, and the sandbox makes the graph trustworthy. Cheap filter, expensive prover.

*Verify at H2 that `codegraphcontext` indexes test functions and that recursive callers actually reach them. If not, fall back to path-based selection (tests importing the touched modules) — still far better than the whole suite.*

### Pre-warmed image

Cloning and installing on stage is death. At H0, build a sandbox image with the demo repo cloned and dependencies installed at the *current pinned* version. On stage the sandbox only does: bump one package, run N tests. Seconds, not minutes.

---

## Honest assessment

**The idea is strong, and the sandbox is what makes it strong.** Without it this is a well-dressed research agent. With it, it clears the stated bar — *"an agent acts on them"* — with a PR carrying a test-verified patch.

It also **solves my biggest worry**. I previously flagged "wrong impact verdicts on stage" as the way this loses, mitigated by manually spot-checking rows. That mitigation was weak. Empiricism replaces it: a red test and a green test are not opinions.

**Where it can still lose:**

1. **Sandbox latency.** Mitigated by the pre-warmed image; still the thing most likely to make the demo drag.
2. **Demo repo has no usable test suite.** This is now a hard selection criterion, not a nice-to-have.
3. **Volume.** Still a lot for two people in a day. Phasing below is strict.

**One reframe I got wrong earlier:** I had a custom tiered dispatcher on the critical path. The prize text reads *"the harness is doing the work rather than sitting underneath a thin wrapper."* Deep native usage — sandbox, skills, dynamic subagents, approvals, sessions, MCP — **is** that. An orchestrator sitting above the harness is arguable at best. It moves to Phase 3.

---

## Phasing

| Phase | Contains | Gate |
|---|---|---|
| **1 — core** | WATCH → LOCATE → BLAST → **REPRODUCE** → brief → approval → PR | must ship |
| **2 — the moment** | **PATCH → VERIFY**, PR only opens on green | H7, ship if 1 is solid |
| **3 — upside** | Tiered dispatch + cost meter | H9, cut without regret |

If Phase 2 slips, the demo still works: *"here are 3 tests that fail under the new version — here's the issue."* If Phase 2 lands, it becomes: *"...and here's the patch that makes them pass."*

---

## Decisions locked

| | |
|---|---|
| Repo | **Fork of `graph_rca`**, history preserved, original untouched |
| Sandbox | **Load-bearing** — reproduce, patch, verify |
| Demo repo | Real OSS repo, real recent breaking change, **fast green test suite** |
| Primary UI | Ops dashboard — missions as jobs, drill into agent tree |
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
TrueForge — hosted mode on TrueFoundry (Postgres + Redis)
  │
  └── CONDUCTOR agent
        skills:  impact-analysis · repro-and-patch · evidence-verification · decision-brief
        tools:   mcp-graph (tunneled) · mcp-web · mcp-store · github/slack (catalog)
                 SANDBOX (native) ← pre-warmed image
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

**Infra:** FalkorDB runs over a unix socket at `~/.codegraphcontext/global/db/falkordb.sock` — not a container, not 6379. So `mcp/graph_server.py` runs where the graph is, **exposed to TrueForge via tunnel**. TrueForge takes remote MCP servers by URL.

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
├── sandbox/Dockerfile            # NEW — pre-warmed demo repo image
├── configs/runtime/nvidia.yaml
├── apps/web/                     # Next.js ops dashboard
├── packages/{mcp-web,mcp-store,contracts,dispatch}/   # dispatch = Phase 3
├── agents/                       # conductor manifest + seed.ts
├── skills/{impact-analysis,repro-and-patch,evidence-verification,decision-brief}/
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
| `tool.response` on sandbox test run | **test output pane: red → green** |
| `tool.response` on `save_patch` | diff view |
| `tool.response` on `run_collector` degraded | self-repair banner |
| `tool.approval_required` | approval queue item |

---

## Hour-by-hour

**H0 — together, 45 min.** Fork cloned and pushed. `contracts` frozen. `CLAUDE.md`. Branch protection.

**H0 — two background jobs, started immediately.**
- Index the demo repo (`pipx install codegraphcontext`). I/O-bound, blocks nothing.
- Build the pre-warmed sandbox image: repo cloned, deps installed at current pinned version, test suite confirmed green.

> **Demo repo criteria** — timebox to 30 min, all four required: Python; public; indexes well under an hour; **has a fast test suite that currently passes**; depends on something with a *real* recent breaking change. Verify the change is real before committing. Fallback: a deprecation rather than a break.

**H0.5–H1.5 — A: providers.** `openai_compat` + `configs/runtime/nvidia.yaml`. Verify `graph-rca query` runs standalone against NIM. *Proves the graph works before TrueForge exists.*

**H0.5–H2 — B: shell.** Next.js, mission queue, mission detail, agent tree, **test output pane** against fake events.

**H1.5–H3 — A: deploy + graph MCP.** TrueForge hosted on TrueFoundry; NVIDIA provider, sandbox enabled, catalog MCP servers. Build `mcp/graph_server.py`, tunnel, register. **Verify `find_function_by_pattern` through TrueForge, and verify recursive `get_callers` reaches test functions.**
*Hard timebox — not green by H3, fall back to local mode.*

**H3 — A: fixture recorder.** Hand B a real stream. *Non-negotiable.*

**H3–H4 — A: sandbox loop.** Wire the pre-warmed image. Prove by hand: bump version → run graph-selected tests → capture traceback. **Before any agent touches it.**

**H4–H5 — A: Bright Data.** Collectors for the dependency's release pages; `mcp-web` with validate-then-heal.

**H5–H7 — A: skills + conductor.** `impact-analysis/SKILL.md` (locate → blast → select tests) and `repro-and-patch/SKILL.md` (run → read traceback → patch → re-run → only report green). Conductor manifest, `seed.ts`. Iterate until reproduce lands reliably.

**H4–H8 — B: the whole dashboard** against fixtures — agent tree, impact table, **test output pane**, diff view, approval queue, brief card, self-repair banner, session recovery via `subscribe-to-a-running-turn`.

**H7 — GATE: Phase 2.** Reproduce solid? Then patch + verify until H8.5. If not, skip and harden reproduce.

**H7–H8 — A: actions.** `actions/policy.yaml` compiled; verify the pause, and that denial blocks the write.

**H8.5–H10 — integrate.** Dashboard against the live agent. Fix contract drift.

**H10–H11 — rehearse failure beats.** Break the scraper on purpose until self-repair is deterministic. Run the full demo path five times; **time the sandbox steps** and trim anything over 15s.

**H11–H11.5 — Qodo pass.** Clear findings, merge.

**H11.5–H12 — rehearse the three minutes, out loud, three times.** Stop.

---

## Qodo

Trunk-based, small PRs, one per slice, **merged continuously**. Every PR through Qodo; findings fixed before merge. Declined findings logged in `docs/decisions.md` with reasoning. Scope Qodo to new work so it isn't reviewing inherited `graph_rca` history.

---

## Demo, three minutes

1. **0:00–0:20 — problem.** *You can't tell whether a release breaks you without running your code against it. So nobody does, until it breaks.*
2. **0:20–0:35 — setup.** Indexed repo; watchlist came from its dependency manifest.
3. **0:35–1:05 — outward + graph.** Scouts find the change. Agent tree fills. Impact table populates with 6 call sites. *"That's a guess so far. Watch."*
4. **1:05–1:20 — self-repair.** "That release page changed its markup this morning." Degradation → heal → restored coverage.
5. **1:20–1:50 — REPRODUCE.** Sandbox bumps the version, runs 4 graph-selected tests. **Three go red on screen.** Real traceback.
6. **1:50–2:20 — PATCH + VERIFY.** Agent writes the fix, re-runs. **Green.** This is the moment.
7. **2:20–2:45 — approval.** Read the action plan aloud. Let the silence sit. Approve. PR opens against this repo, with a diff whose tests passed.
8. **2:45–3:00 — close.** *"It didn't tell me it might break. It broke it, fixed it, and proved the fix."*

---

## Cut list, in order

1. Phase 3 dispatcher (already gated)
2. Slack target — keep in `policy.yaml`, unwired
3. Multi-site patching — patch **one** call site well rather than six badly
4. `get_class_info` / inheritance — callers + chains carry it
5. Evidence panel — fold into the brief

**Never cut:** the sandbox test run, the impact table, self-repair, the approval pause, session recovery.

---

## Risks

| Risk | Mitigation |
|---|---|
| **Sandbox too slow on stage** | Pre-warmed image at H0; graph-selected tests only; time every step at H10 |
| **Demo repo tests don't pass to begin with** | Hard selection criterion; confirm green at H0 before committing to the repo |
| **Recursive callers don't reach tests** | Verify at H2; fall back to path-based test selection |
| Indexing fails or is slow | Start H0 background; small repo; checkpoint H2 |
| No clean real breaking change | 30-min timebox; fall back to a deprecation |
| Patch step unreliable | Phase 2 is gated — reproduce alone still demos |
| Tunnel to graph MCP flaky | Test at H3; local-mode TrueForge needs no tunnel |
| TrueFoundry deploy eats the morning | Hard timebox H3, fall back to local |
| NVIDIA credits exhausted | Fixture replay from H3; OpenAI for patch-writing only |
| Live demo fails on stage | Fixture replay behind a keyboard shortcut |

---

## Verification

1. **Standalone:** `graph-rca query` runs against NVIDIA NIM with no AWS credentials.
2. **Graph:** `find_function_by_pattern("<dep symbol>")` returns real contact points.
3. **Test selection:** recursive `get_callers` from a contact point reaches test functions.
4. **Through the harness:** same calls via `mcp-graph` from a TrueForge session.
5. **Sandbox by hand:** bump the version, run selected tests, get a real traceback — before any agent is involved.
6. **Sandbox by agent:** `sandbox.created` fires and test output appears in a tool result.
7. **Reproduce is honest:** revert the version bump; assert the same tests pass. A repro that fails either way proves nothing.
8. **Patch gate:** assert the PR tool is **unreachable** while tests are red.
9. **Bright Data:** `run_collector` returns rows plus a health verdict.
10. **Self-repair:** structurally changed page → degradation → heal → restored coverage. Rehearse until deterministic.
11. **Approval blocks:** deny → zero writes hit GitHub. Approve → PR and issue exist.
12. **Recovery:** hard-refresh mid-mission; queue, agent tree, impact table, test pane restore.
13. **CI/Qodo:** every merged PR reviewed, findings resolved or logged.
