# AgentRadar — End-to-End Build Plan

Two builders, one day. Targeting four tracks: **Harness**, **Bright Data**, **UI**, **Code Quality**.

---

## 0. What changes from the spec

I verified TrueForge's actual API surface. Three things in `Untitled` are wrong and would cost you hours:

| Spec says | Reality | Consequence |
|---|---|---|
| `agents/news_scout/`, `agents/verifier/` … as code dirs | A TrueForge agent is a **declarative JSON manifest**: `{model, instructions, mcp_servers, skills, config}` | No agent code. Custom logic ships as **MCP servers** (actions/data) + **skills** (procedure) |
| Five named subagents with their own tools | Subagents are **dynamic only** — root calls built-in `create_sub_agent`, they inherit the root's toolset | The five scouts become a *skill-prescribed delegation pattern*, not five configs |
| FastAPI + Python backend | TrueForge is TS/Node (`npx @truefoundry/trueforge`), SDK is `@truefoundry/trueforge-sdk` | TypeScript end-to-end. No Python service |
| Build persistent sessions, approvals, sandbox | All native harness features | ~4 MVP items are config, not code |
| Today's Radar as custom cron | Harness has a **Schedules API** | Daily brief is a config row |

Net: your MVP list of 12 items has **4 you build**, 6 you configure, 2 you theme.

The reframe that wins the harness track: *we don't orchestrate the agents, the harness does.* Our delegation logic lives in a SKILL.md that tells the root agent how to fan out — the harness spawns, schedules, and joins. Judges explicitly said "harness doing the work rather than sitting underneath a thin wrapper." Any orchestration we write in our own API layer is a point against us.

---

## 1. Architecture

```
Next.js UI  ──SSE──>  TrueForge (hosted mode, on TrueFoundry)
  @truefoundry/trueforge-ui            │  Postgres + Redis
  custom theme + containers            │
                                       ├── model: GLM-5.2 via NVIDIA NIM (custom OpenAI-compatible)
                                       │           gpt-5.2 for the demo run
                                       │
                                       ├── skills (git-backed, our repo)
                                       │     research-methodology   ← prescribes the 5-scout fan-out
                                       │     evidence-verification  ← source tiers, conflict rules
                                       │     decision-brief         ← output contract + signal_score.py
                                       │
                                       ├── sandbox (Daytona) ← runs signal_score.py, dedup, evidence ranking
                                       │
                                       └── MCP servers
                                             agentradar-web    (WE BUILD — Bright Data)
                                             agentradar-store  (WE BUILD — evidence/brief persistence)
                                             github            (catalog, approval-gated)
```

**We build exactly two MCP servers and three skills.** Everything else is configuration.

### Why `agentradar-store` exists
It is both the persistence layer *and* the UI's render trigger. When the agent calls `save_brief({...})`, the UI sees that tool call in the event stream and renders the Decision Brief card. Deterministic rendering, no prompt-parsing, and the data is durable for session recovery. Same for `save_evidence` → evidence panel rows.

### The five scouts
`skills/research-methodology/SKILL.md` contains the instruction templates. The root agent reads the skill, then issues five `create_sub_agent` calls. Each `thread.created` event becomes a live row in the UI timeline; `thread.done` marks it complete. That is the Deep Research screen from spec §17 — driven entirely by harness events, no custom orchestration.

---

## 2. Repo layout

```
agentradar/
├── CLAUDE.md                  # Bright Data track: collector rules live here
├── PLAN.md
├── docs/architecture.md
├── apps/web/                  # Next.js + @truefoundry/trueforge-ui
├── packages/
│   ├── mcp-web/               # Bright Data MCP server
│   ├── mcp-store/             # evidence + brief MCP server
│   └── contracts/             # shared zod schemas — the interface between both builders
├── skills/
│   ├── research-methodology/SKILL.md
│   ├── evidence-verification/SKILL.md
│   └── decision-brief/{SKILL.md,scripts/signal_score.py}
├── collectors/                # version-controlled Bright Data collectors
│   ├── hn-frontpage.json
│   ├── gh-releases.json
│   └── _schema.md
├── agents/agentradar.json     # the TrueForge agent manifest
├── fixtures/                  # recorded event streams for offline UI dev + demo fallback
└── .github/workflows/ci.yml
```

`packages/contracts` is the seam. Freeze it at hour 0; both builders code against it and never block each other.

---

## 3. The Bright Data pipeline (track win)

The judging criteria are: pipeline lives *inside* the agentic workflow, config is version-controlled and reusable, and it **detects and recovers when a site changes**. A one-shot scrape loses.

### Version-controlled collectors
Each file in `collectors/` is the durable artifact — Collector IDs survive healing, so they're stable handles:

```json
{
  "id": "c_mpohus372o5tmid1jk",
  "url": "https://news.ycombinator.com",
  "description": "Extract top stories: title, url, points, author, comment_count",
  "required_fields": ["title", "url", "points"],
  "health": { "min_rows": 15, "max_missing_field_ratio": 0.2 }
}
```

### Self-repair loop (this is the demo moment)
`run_collector` in `packages/mcp-web` does not just call `bdata scraper run`. It:

1. Runs the collector.
2. Validates rows against `required_fields` and `health`.
3. If degraded → returns a **structured degradation report**, and auto-invokes `bdata scraper heal <id> "<symptom>" --url <url>`, polling to completion.
4. Re-runs and re-validates. Emits before/after field coverage.

The agent sees this as a tool result and narrates it. The UI shows a "scraper self-repaired" event. **Rehearse this on stage** by pointing a collector at a page whose structure you've changed — that's the differentiator the brief explicitly asks for.

### CLAUDE.md rule (required for the track)
`CLAUDE.md` must state: *all web access goes through Bright Data — never `fetch`, never `curl`, never an unproxied HTTP client*; plus the collector file format and the heal procedure. This is checked, and it also keeps your own coding agent honest.

### Coverage
- Bright Data SERP → `web_search` (news, community discovery)
- Bright Data Web Unlocker → `scrape_page` (docs, blogs, papers as markdown)
- Scraper Studio collectors → `run_collector` (HN, GitHub releases — the structured, healable ones)

---

## 4. Model routing and the credit budget

Subagents inherit the root agent's model, so there is **no per-scout routing**. Pick one model per agent manifest.

- **Dev/default:** GLM-5.2 via NVIDIA NIM — custom OpenAI-compatible provider, `https://integrate.api.nvidia.com/v1`. Free tier is ~1000 credits, 40 RPM. TrueForge's own benchmark ran GLM-5.2 at ~75% below Claude Managed Agents, so this doubles as a talking point.
- **Demo run:** `openai/gpt-5.2` on your $50 OpenAI credits. Better synthesis quality where it's visible.

**Budget reality:** one deep-research run with five subagents is roughly 50–100 model calls. That's ~10–15 full runs on free NVIDIA credits. So:

> **Build the fixture recorder in hour 3, before anything else gets expensive.** Every run writes its full event stream to `fixtures/`. The UI developer then works entirely offline against replayed streams, burning zero credits. It is also your stage fallback if the venue wifi dies — which it will.

---

## 5. Two workstreams

### Track A — Harness, data, action *(builder 1)*
Owns: TrueFoundry deployment, agent manifest, both MCP servers, skills, collectors, GitHub action.

### Track B — UI *(builder 2)*
Owns: Next.js app, theme, timeline, evidence panel, brief card, approval modal, session recovery.

**The contract between them (freeze at hour 0):**

| Harness event | UI renders |
|---|---|
| `turn.created` | mission header |
| `thread.created` / `thread.done` | scout row appears / completes in timeline |
| `model.message.delta` | streaming text |
| `tool.response` on `save_evidence` | evidence panel row (source, tier, claim) |
| `tool.response` on `run_collector` degraded | "self-repair" banner |
| `tool.response` on `save_brief` | **Decision Brief card** |
| `tool.approval_required` | approval modal — Cancel / Approve |
| `tool.response_required` | clarifying-question card |
| `sandbox.created` | "running analysis in isolated sandbox" badge |
| `turn.done` | mission complete summary |

Track B builds all of this against `fixtures/` from hour 3 onward and never waits on Track A.

---

## 6. Hour-by-hour

**H0 — together (45 min).** Create repo, push skeleton, freeze `packages/contracts`, write `CLAUDE.md`, agree the event table above. Both of you should be able to state the demo's 13 success checks from spec §43 out loud.

**H0.5–H2 — Track A: deploy first.**
Get TrueForge hosted mode running on TrueFoundry (Postgres + Redis, Helm or Compose) *before* writing any feature code. Register the NVIDIA NIM custom provider, enable the sandbox, connect the GitHub MCP server from catalog. Verify a trivial agent answers over SSE.
*This is the single highest-risk item. If it isn't green by H2, fall back to TrueForge local mode on a tunnel and keep going — do not let deployment eat the day.*

**H0.5–H2 — Track B: shell.** Next.js + `@truefoundry/trueforge-ui`, custom theme, three-pane layout (timeline | transcript | evidence). Point at a stub SSE stream.

**H2–H4 — Track A: Bright Data.** `bdata login`, create 2–3 collectors, commit their JSON. Build `mcp-web` with `web_search` / `scrape_page` / `run_collector` / `heal_collector` including the validate-then-heal loop. Build `mcp-store`.

**H3 — Track A: fixture recorder.** Hand Track B the first real event stream. *Non-negotiable checkpoint.*

**H4–H6 — Track A: skills.** Write all three SKILL.md files, push, register pinned to a branch. Run the MCP question end-to-end. Iterate the delegation prompt until you reliably see five `thread.created` events.
*Gotcha: skills are materialized from git, so every skill edit needs a push. Pin to a branch during dev; pin to a tag for the demo.*

**H4–H8 — Track B: the whole UI** against fixtures. Timeline, evidence panel, brief card, approval modal, sandbox badge. Session recovery via `subscribe-to-a-running-turn` with resume.

**H6–H8 — Track A: sandbox + action.** `signal_score.py` executing in the sandbox for real. GitHub MCP with `require_approval_for_tools: ["create_pull_request","create_issue","create_or_update_file"]` — the approval pause is config, not code.

**H8–H9 — integrate.** Point UI at the live harness. Fix the contract drift you'll inevitably find.

**H9–H10 — break the scraper on purpose.** Rehearse the self-repair demo until it's reliable. Record a fresh fixture of a perfect run.

**H10–H11 — Qodo pass.** Open PRs, clear findings, merge.

**H11–H12 — rehearse the three minutes.** Out loud. Three times. Then stop building.

---

## 7. Qodo workflow (required for that track)

Trunk-based, small PRs, one per workstream slice. Every PR runs through Qodo and you **fix what it finds before merging** — the track is judged on dealing with findings, not on having run the tool. Keep a `docs/decisions.md` noting anything Qodo flagged that you consciously declined, with reasoning; that reads as engineering judgment rather than an ignored warning.

Enable branch protection early so you can't accidentally push to main at hour 11.

---

## 8. Demo deltas from spec §37

Your script is good. Three changes:

- **Add a self-repair beat** at ~1:10, before verification. Ten seconds: "the HN layout changed this morning — watch." It's the only moment that demonstrates the Bright Data track, and no other team will have it.
- **Cut the personalization beat to five seconds.** It's a stack-impact number on the brief card, not its own screen.
- **The approval pause is the emotional beat.** Let the silence sit. Read the action plan aloud before clicking Approve.

The PR opens against the AgentRadar repo itself — say that out loud. "The agent is proposing an experiment in the repo you're about to review." That lands well with a Qodo judge in the room.

---

## 9. Cut list, in order

When you're behind, drop in this order — decide now so you don't debate at hour 9:

1. Community Scout (four scouts demo identically to five)
2. Knowledge Map (already deferred in your spec — keep it deferred)
3. Today's Radar / Schedules (cheap, but only if H10 is clear)
4. Conflict detection UI (keep it in the brief text, drop the dedicated panel)
5. Paper Scout

Never cut: the approval pause, the self-repair beat, the sandbox execution, session recovery.

---

## 10. Top risks

| Risk | Mitigation |
|---|---|
| TrueFoundry deployment eats the morning | Timebox to H2, fall back to local + tunnel |
| NVIDIA free credits exhausted mid-afternoon | Fixture replay from H3; switch to OpenAI for demo only |
| Skill iteration is slow (needs a git push per edit) | Pin to branch in dev; get skill text ~right on the first pass |
| Agent doesn't reliably fan out to five subagents | Make the fan-out explicit and numbered in SKILL.md; verify by H6 |
| Live demo fails on stage | Recorded fixture replay behind a keyboard shortcut |
| Qodo pass discovers something structural at H10 | Small PRs merged continuously, not one big PR at the end |
