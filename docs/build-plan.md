# AgentRadar — Backend Build Plan (PR by PR)

**Audience: the coding agent implementing this.** Every section is executable. Do not improvise structure — it is specified below.

---

## Context

`PLAN.md` in the repo root is the product plan; read it once for the *why*. This file is the *how*.

AgentRadar answers: **"Does this dependency release break my code, where, and can you fix it?"**

```
WATCH  →  LOCATE  →  BLAST  →  REPRODUCE  →  PATCH  →  VERIFY  →  ACT
(web)     (graph)   (graph)   (sandbox)     (sandbox) (sandbox)  (approval)
```

The graph is a **cheap filter** (narrow millions of lines → 6 call sites for pennies). The sandbox is an **expensive prover** (run 4 tests, not 4000). Neither is useful alone.

**UI is on hold.** This plan builds the backend only. PR1 freezes the contracts the dashboard will later render, so the UI is unblocked without being built.

Two builders, two parallel PR chains, converging at PR10.

---

## Repo strategy (decided)

`graph_rca` history merges **into this repo**. Verified: zero filename collisions.

```bash
git remote add upstream ~/graph_rca
git fetch upstream
git merge --allow-unrelated-histories upstream/main
```

This repo keeps `.pr_agent.toml`, `PLAN.md`, `docs/`. It gains `src/main/`, `configs/`, `tests/`, `pyproject.toml`, `install.sh`, `README.md`.

**Language: Python everywhere, except `agents/seed.ts`.** The TrueForge SDK is TypeScript, so seeding uses it. Nothing else is TS while the UI is on hold.

---

## THE SPINE — read before writing any code

Every PR below places files inside this structure. **This is the code-quality thesis. Violating it is a review blocker.**

```
src/main/agentradar/
├─ contracts/     pydantic v2 models. Imports NOTHING from siblings. No logic.
├─ core/          pure functions over contracts. No I/O, no network, no subprocess, no clock.
├─ adapters/      the ONLY code that touches the outside world. Protocol + one impl each.
└─ mcp/           thin servers: parse → validate → call core/adapter → return contract.
```

### Four rules, mechanically enforced

| # | Rule | Enforced by |
|---|---|---|
| 1 | `core/` may not import `adapters/` or `mcp/` | `scripts/check_layering.py` in CI |
| 2 | Only `adapters/brightdata.py` may do network I/O — no `requests`, `httpx`, `urllib`, `aiohttp`, `curl`, `fetch` anywhere else, **including tests** | `scripts/check_layering.py` in CI |
| 3 | Every adapter is a `typing.Protocol` + one concrete impl. Consumers type-hint the Protocol, never the impl | code review + mypy |
| 4 | Every MCP handler's return type annotation is a contract model. No bare `dict` returns | mypy strict on `agentradar/` |

### Why this shape

- **Tests run offline.** `core/` is pure so it unit-tests with zero infra. Adapters have fakes in `tests/agentradar/fakes.py`. `pytest` never opens a socket — which it must not, because rule 2 forbids it.
- **Qodo can see it.** `.pr_agent.toml` already encodes these as review invariants. CI catches the mechanical half; the reviewer catches the rest.
- **Swappable.** The sandbox decision flipped once already (`fa73a12`, local Docker → harness-native Daytona) and cost one impl behind an unchanged Protocol. `BdataClient` → recorded fixtures is the same trade. Assume at least one more decision flips today.

### Conventions

- Branch: `feat/<slug>`, `fix/<slug>`, `chore/<slug>`.
- Commit + PR title: conventional commits. `feat(sandbox): docker test runner`.
- **One PR per section below. Merge before starting the next in your chain.** Never batch.
- Every PR: green CI, Qodo findings resolved or logged in `docs/decisions.md`.
- Type hints on every public function. Docstring one-liner on every module and public function.
- Pydantic v2 (`model_validate`, `model_dump`), not v1 idioms.

---

## Reuse — do not rewrite these

| Existing | Path | Use for |
|---|---|---|
| `find_by_pattern(pattern, repo, limit)` | `src/main/code_tools/queries.py:204` | **Searches function names OR source text** — this is what finds dependency contact points |
| `get_callers(function_name, repo, limit, fid)` | `queries.py:80` | Blast radius **and** test selection |
| `get_callees`, `get_call_chain`, `read_source` | `queries.py` | Context for patch-writing |
| `get_class_info`, `get_inheritance` | `queries.py:126,155` | Subclassing breakage (cut-listed) |
| `query(cypher, params)` / `get_graph()` | `code_tools/graph_conn.py` | FalkorDB over unix socket `~/.codegraphcontext/global/db/falkordb.sock`, graph `codegraph` |
| `TOOLS` list + `handle_tool_call` | `code_tools/trace_tools.py:9,117` | Tool schemas already written — adapt, don't retype |
| `BaseLLMProvider` (`get_tool_schemas`, `invoke`) | `shared/providers/base.py` | Extend for `openai_compat` |
| `make_provider()` | `shared/factory.py` | Add the `openai_compat` branch here |
| `get_analyzer_configs()` + `config/jsons/*.json` | `config/loader.py` | Env-var config pattern — follow it, add a new JSON file |

**Note:** `queries.py` takes `repo` as the *last path segment* (`repo_path.split("/")[-1]`), not a full path. Preserve that.

**Dead weight — leave in place, do not delete:** `graph_rca/trace_agent.py`, `decompose.py`, `judges.py`, `router.py`. They power the standalone CLI, which is the backup demo.

---

## H0 — local infra setup (no code, do this first)

None of this is a PR. It is machine setup, and it gates PR1/PR5. **Start 1, 2 and 3 in parallel — they are the long poles.**

| # | Task | Who | Time | Blocks |
|---|---|---|---|---|
| 1 | **Pick the demo repo.** Timebox 30 min, all four required: Python; public; indexes in well under an hour; **fast test suite that currently passes**; depends on something with a *real* recent breaking change. Verify the change is real before committing. Fallback: a deprecation rather than a break. Write the answer into `configs/demo.yaml` | human | 30m | PR5, PR7, PR8 |
| 2 | `pipx install codegraphcontext`, index the demo repo at a **pinned commit**. I/O-bound, blocks nothing else — start it and walk away | human | 5m + background | PR3, PR4 |
| 3 | **Daytona signup + API key**, wire it into TrueForge, and run a `sandbox.created` smoke test. Free tier, $200 compute, no credit card. **This is now on the demo path** — it is not optional | human | 20m | PR5, PR10, PR11 |
| 4 | **Prewarm the native sandbox** per `sandbox/PREWARM.md`: clone the pinned commit, install baseline deps, confirm the selected tests are green, keep the session alive. Set `auto_stop`/`auto_archive` intervals explicitly and confirm it survives an idle gap | human | 40m | PR5 |
| 5 | `BRIGHTDATA_API_KEY` — `bdata login`, confirm `bdata scraper run` works by hand once | human | 10m | PR6 |
| 6 | NVIDIA NIM key (`https://integrate.api.nvidia.com/v1`, ~1000 free credits, 40 RPM) + OpenAI key. Into `.env` | human | 5m | PR2 |
| 7 | Node 22.14+, then `npx @truefoundry/trueforge@latest` — confirm `localhost:8790` serves | human | 10m | PR10 |
| 8 | Install the Qodo GitHub App at `https://github.com/apps/qodo-merge-pro`, grant this repo. Enable branch protection on `main` | human | 5m | all PRs |
| 9 | `docker` running (rehearsal path only), `gh auth status` clean | human | 2m | PR5, PR12 |

**Two H0 items can lose the demo:**

- **The demo repo choice (1).** Everything downstream reads `configs/demo.yaml`, so code can be written before the choice lands — but do not let it slip past H0.5.
- **Sandbox survival (3 + 4).** With execution now harness-native and no custom image, a stopped or archived Daytona session between rehearsal and stage means cold-cloning on venue wifi in front of judges. Test the idle gap, not just the happy path.

---

## PR chains

```
PR1 ─┬─ A: PR2 → PR3 → PR4 → PR5 ──┐
     │                              ├─ PR10 → PR11 → PR12 → PR13
     └─ B: PR6 → PR7 → PR8 → PR9 ──┘
```

### Model assignment

Three tiers, matched to how much *judgment* the PR needs versus how much is transcription from this plan.

- **Composer** — mechanical and fully specified. Signatures, fields and file paths are all written below; the model is filling them in. Low judgment, high throughput.
- **Grok 4.6 (high)** — multi-file, some design latitude, but the shape is fixed here and the failure modes are visible in tests.
- **Sonnet 5** — correctness-critical or thesis-carrying. Wrong output here loses a track, and the bug would not be obvious in review.

| PR | Title | Chain | Model | Est | Gate |
|---|---|---|---|---|---|
| 1 | `chore: merge graph_rca, freeze contracts, CI` | both | **Grok 4.6** | 50m | blocks all |
| 2 | `feat(providers): openai-compatible LLM provider` | A | **Composer** | 40m | |
| 3 | `feat(mcp): code graph server` | A | **Grok 4.6** | 45m | |
| 4 | `feat(core): graph-guided test selection` | A | **Sonnet 5** | 40m | **thesis** |
| 5 | `feat(sandbox): native sandbox procedure + pytest parsing` | A | **Sonnet 5** | 55m | **thesis** |
| 6 | `feat(web): bright data adapter + search/scrape MCP` | B | **Grok 4.6** | 50m | Bright Data track |
| 7 | `feat(collectors): validate-then-heal` | B | **Sonnet 5** | 50m | Bright Data track |
| 8 | `feat(core): watchlist from dependency manifest` | B | **Composer** | 30m | |
| 9 | `feat(store): mission state + evidence` | B | **Composer** | 40m | |
| 10 | `feat(agents): conductor, prompts, seed` | both | **Sonnet 5** | 90m | Harness track |
| 11 | `feat(patch): patch-and-verify loop` | A | **Sonnet 5** | 60m | **Phase 1** |
| 12 | `feat(actions): github + approval policy` | B | **Grok 4.6** | 45m | |
| 13 | `chore(fixtures): event recorder` | either | **Composer** | 30m | cut if late |

**Why each Sonnet PR is Sonnet:**

- **PR4** — the algorithm *is* the product thesis. A subtly wrong BFS silently returns the wrong tests and the demo proves nothing while looking fine.
- **PR5** — Docker lifecycle, warm-container reuse, and pytest output parsing. Three ways to be wrong that all still "run".
- **PR7** — the heal loop is the Bright Data track. Symptom-string quality determines whether healing works at all, and poll-to-completion has real edge cases.
- **PR10** — prompt engineering plus a TrueForge API surface with parts still unverified. Highest judgment content in the build.
- **PR11** — `can_act` is the single most important assertion in the codebase. If it is wrong, the product lies on stage.

**One caveat on PR1:** the contracts block every other PR, so **read the generated models by hand before merging** even though a mid-tier model wrote them. A wrong field name costs a rewrite in four downstream PRs.

---

## PR1 — `chore: merge graph_rca, freeze contracts, CI`

Branch `chore/foundation`. **Both builders wait on this.** Do it together.

### Files

```
CLAUDE.md                                    NEW
pyproject.toml                               EDIT — add deps, ruff/mypy config
.github/workflows/ci.yml                     NEW
scripts/check_layering.py                    NEW
scripts/export_schemas.py                    NEW
src/main/agentradar/__init__.py              NEW
src/main/agentradar/contracts/__init__.py    NEW
src/main/agentradar/contracts/dependency.py  NEW
src/main/agentradar/contracts/impact.py      NEW
src/main/agentradar/contracts/evidence.py    NEW
src/main/agentradar/contracts/patch.py       NEW
src/main/agentradar/contracts/collector.py   NEW
src/main/agentradar/contracts/mission.py     NEW
src/main/agentradar/{core,adapters,mcp}/__init__.py  NEW
tests/agentradar/__init__.py                 NEW
tests/agentradar/test_contracts.py           NEW
contracts/schemas/*.json                     GENERATED
configs/demo.yaml                            NEW
```

### Contracts — exact fields

All models: `pydantic.BaseModel`, `model_config = ConfigDict(frozen=True)` unless noted.

```python
# dependency.py
class Dependency(BaseModel):
    name: str                    # "langgraph"
    current_spec: str            # ">=0.2.0,<0.3"
    current_version: str | None   # resolved, if known
    source: str                  # "pyproject.toml"

class Watchlist(BaseModel):
    repo: str
    dependencies: list[Dependency]

class ReleaseEvent(BaseModel):
    dependency: str
    version: str
    published_at: str            # ISO8601
    title: str
    body: str
    url: str
    breaking_hint: bool = False  # heuristic from body text
    source_collector: str | None # collector id that produced it

# impact.py
class ContactPoint(BaseModel):
    symbol: str                  # dependency symbol referenced
    function_name: str
    fid: int
    file_path: str
    line: int | None

class BlastRadius(BaseModel):
    contact_point: ContactPoint
    callers: list[str]           # function names, BFS-ordered
    depth_reached: int

class Verdict(StrEnum):
    UNKNOWN = "unknown"          # not yet proven
    BROKEN = "broken"            # a selected test failed under the new version
    SAFE = "safe"                # selected tests passed under the new version
    UNCOVERED = "uncovered"      # no test reaches it; import-check fallback used

class ImpactRow(BaseModel):
    contact_point: ContactPoint
    verdict: Verdict
    why: str                     # one sentence, human-readable
    evidence_ref: str | None     # TestReport id

# evidence.py
class TestSelection(BaseModel):
    tests: list[str]             # pytest node ids, e.g. "tests/test_x.py::test_y"
    strategy: Literal["callers", "path", "manual"]
    reached_from: list[str]      # contact point function names
    truncated: bool = False

class TestCase(BaseModel):
    node_id: str
    outcome: Literal["passed", "failed", "error", "skipped"]
    duration_s: float
    traceback: str | None

class TestReport(BaseModel):
    id: str
    package: str                 # "langgraph"
    version: str                 # version under test
    cases: list[TestCase]
    passed: int
    failed: int
    duration_s: float
    raw_tail: str                # last ~2000 chars of output, for the UI pane

    @property
    def is_green(self) -> bool: return self.failed == 0 and self.passed > 0

# patch.py
class Patch(BaseModel):
    diff: str                    # unified diff
    files: list[str]
    rationale: str

class VerifyResult(BaseModel):
    patch: Patch
    before: TestReport           # red
    after: TestReport            # must be green to pass the gate
    verified: bool               # after.is_green and before.failed > 0

# collector.py
class CollectorSpec(BaseModel):
    id: str                      # "c_..."
    url: str
    description: str
    required_fields: list[str]
    min_rows: int = 5
    max_missing_field_ratio: float = 0.2

class HealthVerdict(BaseModel):
    healthy: bool
    rows_returned: int
    missing_field_ratio: float
    missing_fields: list[str]
    symptom: str | None          # fed verbatim to `bdata scraper heal`

class CollectorRun(BaseModel):
    spec_id: str
    rows: list[dict]
    health: HealthVerdict
    healed: bool = False
    health_after_heal: HealthVerdict | None = None

# mission.py
class MissionState(StrEnum):
    WATCHING = "watching"; LOCATING = "locating"; REPRODUCING = "reproducing"
    PATCHING = "patching"; AWAITING_APPROVAL = "awaiting_approval"
    DONE = "done"; FAILED = "failed"

class Mission(BaseModel):
    model_config = ConfigDict(frozen=False)
    id: str
    release: ReleaseEvent
    state: MissionState
    impact_rows: list[ImpactRow] = []
    selection: TestSelection | None = None
    reports: list[TestReport] = []
    verify: VerifyResult | None = None

class ActionPlan(BaseModel):
    target: Literal["github_pr", "github_issue", "slack", "export"]
    summary: str
    payload: dict
    requires_approval: bool
```

### `scripts/check_layering.py`

Zero dependencies, stdlib only. Exits non-zero with the offending `file:line` on violation.

1. Walk `src/main/agentradar/core/` — fail on any `import`/`from` naming `adapters` or `mcp`.
2. Walk all of `src/` and `tests/` — fail on `requests`, `httpx`, `urllib.request`, `aiohttp`, `subprocess` invoking `curl`/`wget`, outside `src/main/agentradar/adapters/brightdata.py`.
3. Print `OK: layering clean` on success.

### `.github/workflows/ci.yml`

Python 3.11, `uv` or pip. Steps, in order:
1. `ruff check src/main/agentradar tests/agentradar`
2. `ruff format --check src/main/agentradar tests/agentradar`
3. `python scripts/check_layering.py`
4. `mypy --strict src/main/agentradar`
5. `pytest tests/agentradar -q`

**Scope new tooling to `agentradar/` only.** Inherited `graph_rca` code is not held to ruff/mypy strict — do not reformat it, it creates review noise.

### `configs/demo.yaml`

The demo repo is chosen at H0, not now. Everything reads it from here:

```yaml
demo:
  repo_url: ""          # TBD at H0
  repo_key: ""          # last path segment — what queries.py expects
  commit: ""            # the commit that was indexed AND baked into the image
  dependency: ""        # the package with the breaking change
  from_version: ""
  to_version: ""
  test_root: "tests"
```

### `CLAUDE.md`

Must state, concisely: the spine and its four rules; **all web access goes through Bright Data**, no exceptions including tests and scripts; the collector JSON format and heal procedure; that secrets never enter the sandbox (the harness holds credentials, the sandbox gets code/files/shell only); commit conventions. `.pr_agent.toml` already points Qodo at this file — keep them consistent.

### Acceptance
- `pytest tests/agentradar -q` green; every contract has a round-trip test.
- `python scripts/check_layering.py` exits 0.
- `python scripts/export_schemas.py` writes `contracts/schemas/*.json`.
- `git log` shows graph_rca's commits.

---

## Chain A

### PR2 — `feat(providers): openai-compatible LLM provider`

Branch `feat/openai-compat`. ~40 lines of real change.

| File | Change |
|---|---|
| `pyproject.toml` | add `langchain-openai>=0.2` |
| `src/main/config/jsons/openai_compat.json` | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` — follow the existing `aws.json` shape |
| `src/main/config/loader.py` | add `"openai_compat.json"` to `_CONFIG_FILES` |
| `src/main/shared/factory.py` | allow `openai_compat` in the provider set |
| `src/main/shared/providers/langchain.py` | branch constructing `ChatOpenAI(base_url=…, api_key=…, model=…)` |
| `configs/runtime/nvidia.yaml` | copy `configs/runtime/bedrock.yaml`, map tiers to NIM + OpenAI models |
| `.env.example` | document the three vars |
| `tests/shared/test_openai_compat.py` | factory returns the provider for `CLOUD_PROVIDER=openai_compat`; unknown value still raises |

NVIDIA NIM: `https://integrate.api.nvidia.com/v1`, OpenAI-compatible, 40 RPM.

**Acceptance:** `CLOUD_PROVIDER=openai_compat graph-rca query "<question>"` returns an answer against NIM with **no AWS credentials present**. This proves the graph works before TrueForge exists, and leaves a working CLI as backup demo.

---

### PR3 — `feat(mcp): code graph server`

Branch `feat/mcp-graph`.

```
src/main/agentradar/adapters/graph.py     NEW
src/main/agentradar/mcp/_server.py        NEW
src/main/agentradar/mcp/graph_server.py   NEW
tests/agentradar/fakes.py                 NEW
tests/agentradar/test_graph_adapter.py    NEW
pyproject.toml                            EDIT — add `mcp>=1.0`
```

**`adapters/graph.py`** — Protocol + FalkorDB impl. Delegate to `code_tools.queries`; do not write new Cypher.

```python
class CodeGraph(Protocol):
    def find_contact_points(self, symbol: str, repo: str, limit: int = 15) -> list[ContactPoint]: ...
    def callers_of(self, fid: int, repo: str, limit: int = 25) -> list[dict]: ...
    def call_chain(self, frm: str, to: str, repo: str, max_hops: int = 4) -> list[dict]: ...
    def read_source(self, fid: int, repo: str, max_chars: int = 1500) -> str: ...

class FalkorCodeGraph:   # wraps queries.find_by_pattern / get_callers / ...
```

`find_contact_points` calls `queries.find_by_pattern` — it matches **source text**, which is how a dependency symbol is found. Map its `[{name, fid}]` rows into `ContactPoint`.

**`mcp/_server.py`** — shared plumbing every MCP server reuses:
- `def tool(name, description, schema)` decorator registering handlers
- input validation against the declared JSON schema before dispatch
- uniform error envelope `{"error": {"type": ..., "message": ...}}` — never raise across the MCP boundary
- `def serve(name: str, port: int)` entrypoint

**`mcp/graph_server.py`** — exposes `find_contact_points`, `get_callers`, `get_call_chain`, `read_function_source`. Adapt the schemas already in `code_tools/trace_tools.py:9`.

Runs on the **same machine as FalkorDB**. TrueForge calls MCP from its own process, so localhost works — **no tunnel**.

**`tests/agentradar/fakes.py`** — `FakeCodeGraph` returning canned nodes. Every downstream test uses it.

**Acceptance:** `find_contact_points("<dep symbol>")` returns real call sites from the indexed demo repo; the same call succeeds through a TrueForge session with the server registered at a localhost URL.

---

### PR4 — `feat(core): graph-guided test selection`

Branch `feat/test-selection`. **This PR carries the thesis and needs zero infrastructure to test.** Give it the most care.

```
src/main/agentradar/core/selection.py         NEW
tests/agentradar/test_selection.py            NEW
```

Pure. Takes a `CodeGraph` **Protocol** — tests pass `FakeCodeGraph`, so no FalkorDB.

```python
def select_tests(
    graph: CodeGraph,
    contact_points: list[ContactPoint],
    repo: str,
    *,
    max_depth: int = 4,
    max_tests: int = 12,
    test_root: str = "tests",
) -> TestSelection:
    """Walk callers breadth-first from each contact point; collect test functions."""

def is_test_node(name: str, file_path: str, test_root: str) -> bool:
    """A node is a test if its file is under test_root and its name starts with 'test_'."""

def select_tests_by_path(
    contact_points: list[ContactPoint], repo_files: list[str], test_root: str
) -> TestSelection:
    """Fallback: tests whose module path shares a package with a touched module."""

def to_node_ids(functions: list[dict]) -> list[str]:
    """Graph nodes → pytest node ids 'path::name'."""
```

Requirements:
- BFS, not DFS. Cycle-safe — track visited `fid`s.
- Stop at `max_depth`; set `truncated=True` if `max_tests` clipped the result.
- Deterministic ordering (sort by `fid`) so runs are reproducible on stage.
- `strategy` field records which path was taken. **Never silently fall back** — the UI shows it.

**Verify at H2 against the real graph:** does `codegraphcontext` index test functions, and does recursive `get_callers` reach them? If no → `select_tests_by_path` is the primary, and say so in the demo. Do not fake it.

**Acceptance:** unit tests cover — reaches a test 3 hops up; cycles terminate; `max_tests` sets `truncated`; empty contact points → empty selection, not a crash; path fallback returns a strict superset of nothing.

---

### PR5 — `feat(sandbox): native sandbox procedure + pytest parsing`

Branch `feat/sandbox`. The demo's most latency-sensitive component.

**Decision, per `PLAN.md` as of `fa73a12`: the repro loop runs in TrueForge's native Daytona sandbox, not a custom MCP test runner.** The agent drives it with the harness's built-in shell/file tools. Our Python code is *not* in the execution loop — which makes this PR smaller than it looks, and moves the real work into (a) the prewarm procedure and (b) parsing what comes back.

```
sandbox/PREWARM.md                            NEW  — the runbook, executed by hand at H0
sandbox/Dockerfile                            NEW  — rehearsal only, NOT the demo path
src/main/agentradar/adapters/sandbox.py       NEW
src/main/agentradar/core/testreport.py        NEW
fixtures/pytest_output_red.txt                NEW  (captured by hand)
fixtures/pytest_output_green.txt              NEW
tests/agentradar/test_testreport.py           NEW
tests/agentradar/test_sandbox_adapter.py      NEW
```

**`sandbox/PREWARM.md`** — the exact command sequence, so it is repeatable under pressure:

1. Provision the Daytona sandbox through TrueForge (a real turn — `sandbox.created` must fire).
2. Shallow-clone the demo repo at `configs/demo.yaml:commit` — the *same* commit the graph indexed.
3. Install pinned baseline deps; run the selected tests; **confirm green**.
4. Keep the session and sandbox alive through the demo.
5. On stage: bump the version, run the tests, patch, re-run.

The warmup is setup, not evidence. Every number in the impact claim comes from a run *after* the version change.

> **Verify at H0 and again at H8:** TrueForge's Daytona provider config carries `auto_stop_interval_in_minutes`, `auto_archive_interval_in_minutes`, `auto_delete_interval_in_minutes`. A "kept alive" session can be stopped out from under you between rehearsal and stage. Set these explicitly and confirm the sandbox survives an idle gap at least as long as the wait before your slot. **This is the single highest-risk item created by the native-sandbox decision — do not assume, test it.**

**`core/testreport.py`** — pure parser, no subprocess. This is where the value of this PR actually lives, and it is runner-agnostic by construction:

```python
def parse_pytest(stdout: str, package: str, version: str, report_id: str,
                 *, duration_s: float = 0.0) -> TestReport: ...
```

Parse the short-summary block (`PASSED`/`FAILED`/`ERROR` node ids), per-test durations when `--durations` is present, and capture the failing traceback. Tests read `fixtures/pytest_output_*.txt` — **this is why the fixtures are captured by hand first.** It takes a plain string, so it parses output from the native sandbox, from Docker, or from a fixture, unchanged.

Wire it into `save_report` in PR9's store server: the agent hands back raw output, the store parses it into a `TestReport`. Parsing stays in `core/`, never in a prompt.

**`adapters/sandbox.py`** — the Protocol survives; only the primary impl changes.

```python
@dataclass(frozen=True)
class RawRun:
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float

class SandboxRunner(Protocol):
    def run_tests(self, node_ids: list[str], *, timeout_s: int = 180) -> RawRun: ...
    def set_package_version(self, package: str, version: str) -> RawRun: ...
    def apply_patch(self, diff: str) -> RawRun: ...
    def import_check(self, symbol: str, package: str) -> RawRun: ...   # UNCOVERED fallback

class DockerRunner:  # rehearsal + CI timing only. `docker exec` into a warm container.
```

**`DockerRunner` is not the demo path and must not be presented as one.** It exists so you can iterate on selection and parsing without burning Daytona minutes or venue wifi, and so PR11's gate tests run in CI. If the native path is timed at H10 and drags, this is the one line you flip — the Protocol is what makes that a decision rather than a rewrite.

**Do this by hand before any agent touches it:** in the native sandbox, bump the version → run the graph-selected tests → get a real traceback. Time it.

**Acceptance:**
- The native sandbox runs the green suite in **under 15s** on a prewarmed session — measured, not assumed.
- The sandbox survives an idle gap longer than your wait before the slot.
- **Repro is honest:** revert the bump, run the same tests, assert they pass. A repro that fails either way proves nothing — write this as a test.
- Parser tests pass on both captured fixtures, with no runner involved.
- No secrets are passed into the sandbox. Ever.

---

## Chain B

### PR6 — `feat(web): bright data adapter + search/scrape MCP`

Branch `feat/mcp-web`. **`adapters/brightdata.py` is the only module in the repo permitted to reach the network.** `scripts/check_layering.py` enforces it.

```
src/main/agentradar/adapters/brightdata.py    NEW
src/main/agentradar/mcp/web_server.py         NEW
fixtures/bdata_search.json                    NEW  (recorded)
fixtures/bdata_scrape.json                    NEW  (recorded)
tests/agentradar/test_brightdata_adapter.py   NEW
```

```python
class WebClient(Protocol):
    def search(self, query: str, *, limit: int = 10) -> list[dict]: ...          # SERP
    def scrape(self, url: str) -> str: ...                                       # Web Unlocker
    def run_collector(self, spec: CollectorSpec) -> list[dict]: ...              # Scraper Studio
    def heal_collector(self, spec_id: str, symptom: str, url: str) -> bool: ...

class BdataClient:   # shells out to the `bdata` CLI
```

CLI surface: `bdata scraper run <collector-id> <url> --pretty`, `bdata scraper heal <id> "<symptom>" --url <url> --auto-approve`, `bdata scraper approve <id>`. Auth via `BRIGHTDATA_API_KEY`.

Every subprocess call: explicit timeout, non-zero exit → typed error, **never** a silent empty list.

`mcp/web_server.py` exposes `web_search` and `scrape_page`. Migration guides fetched via `scrape_page` feed patch-writing in PR11.

**Tests use recorded fixtures — no live calls in CI.** Record them once by hand into `fixtures/`.

**Acceptance:** `web_search` and `scrape_page` return real content through Bright Data; `check_layering.py` passes; CI is green with no network.

---

### PR7 — `feat(collectors): validate-then-heal`

Branch `feat/collectors`. This is the Bright Data track's differentiator: **the scraper repairs itself on stage.**

```
collectors/<dep>-releases.json                NEW
collectors/<dep>-changelog.json               NEW
src/main/agentradar/core/health.py            NEW
src/main/agentradar/mcp/web_server.py         EDIT — add run_collector
tests/agentradar/test_health.py               NEW
```

**`core/health.py`** — pure, the whole reason self-repair is deterministic:

```python
def evaluate(rows: list[dict], spec: CollectorSpec) -> HealthVerdict:
    """Rows + spec → verdict. No I/O. `symptom` is fed verbatim to `bdata scraper heal`."""
```

`symptom` must be specific — `"3 of 5 rows missing 'tag'; 1 row returned, expected >= 5"` — not `"scraper broken"`. Heal quality depends entirely on this string.

**`run_collector` flow, in `mcp/web_server.py`:**
1. run → 2. `evaluate` → 3. if unhealthy: return the structured report **and** invoke `heal_collector(spec.id, verdict.symptom, spec.url)`, polling to completion → 4. re-run → 5. emit `CollectorRun` with `health` **and** `health_after_heal`.

Collector IDs (`c_*`) survive healing — never regenerate them.

**Acceptance:** structurally changed page → degradation detected → heal → restored coverage, with before/after in one `CollectorRun`. Rehearse until deterministic.

---

### PR8 — `feat(core): watchlist from dependency manifest`

Branch `feat/watchlist`. Small, pure, high leverage — **it removes the last piece of manual config from the product.**

```
src/main/agentradar/core/watchlist.py         NEW
fixtures/manifests/pyproject_sample.toml      NEW
fixtures/manifests/requirements_sample.txt    NEW
tests/agentradar/test_watchlist.py            NEW
```

```python
def from_pyproject(text: str, repo: str) -> Watchlist: ...
def from_requirements(text: str, repo: str) -> Watchlist: ...
def detect_and_parse(files: dict[str, str], repo: str) -> Watchlist:
    """{filename: contents} → Watchlist. Prefers pyproject.toml."""
def is_newer(current: str, candidate: str) -> bool:
    """PEP 440 comparison. Use packaging.version — do not hand-roll."""
```

Handle `[project].dependencies`, `[dependency-groups]`, and poetry's `[tool.poetry.dependencies]`. Skip `python` itself. Use stdlib `tomllib`.

**Acceptance:** parsing this repo's own `pyproject.toml` yields the real dependency list; `is_newer("0.2.9", "0.3.0")` is true and `is_newer("0.10.0", "0.9.0")` is false.

---

### PR9 — `feat(store): mission state + evidence`

Branch `feat/mcp-store`.

```
src/main/agentradar/adapters/store.py         NEW
src/main/agentradar/mcp/store_server.py       NEW
tests/agentradar/test_store.py                NEW
```

```python
class MissionStore(Protocol):
    def create_mission(self, release: ReleaseEvent) -> Mission: ...
    def save_impact(self, mission_id: str, row: ImpactRow) -> None: ...
    def save_selection(self, mission_id: str, sel: TestSelection) -> None: ...
    def save_report(self, mission_id: str, report: TestReport) -> None: ...
    def save_verify(self, mission_id: str, result: VerifyResult) -> None: ...
    def get_mission(self, mission_id: str) -> Mission: ...
    def set_state(self, mission_id: str, state: MissionState) -> None: ...

class SqliteStore:   # single file, path from env; JSON columns for contract payloads
```

Tests use `:memory:`. `mcp/store_server.py` exposes these as tools — **these tool responses are what the dashboard renders later**, so return contract models verbatim.

**Acceptance:** full mission round-trip persists and reloads with every field intact.

---

## Converge

### PR10 — `feat(agents): conductor, prompts, seed`

Branch `feat/conductor`. **Both builders.** This is the Harness track.

```
agents/conductor.json                         NEW
agents/prompts/00-conductor.md                NEW
agents/prompts/10-impact-analysis.md          NEW
agents/prompts/20-repro.md                    NEW
agents/prompts/30-brief.md                    NEW
agents/seed.ts                                NEW
agents/package.json                           NEW
actions/policy.yaml                           NEW
agents/README.md                              NEW
```

TrueForge facts, verified — build to these, do not guess:

- Local mode: `npx @truefoundry/trueforge@latest`, Node 22.14+, SQLite, `localhost:8790`. UI + backend + SDK in one process. No Postgres, no Redis, no hosting.
- Agents are **declarative JSON manifests**: `{model, instructions, mcp_servers, skills, config}`. There is no agent code.
- **Subagents are dynamic-only**, via the built-in `create_sub_agent`. They inherit the root's toolset *and* model. Per-task model tiering does not exist natively — that is Phase 3, cut without regret.
- MCP servers are called from the **harness process**, so localhost URLs work with no tunnel.
- Approvals: `require_approval_for_tools`, accepting `@write`, `@destructive`, or explicit tool names.
- Sandbox slot accepts **Daytona only**, cloud-only, no custom image. Configure it so it demonstrably works if a judge probes — but **nothing on the demo path may depend on it.**

**Procedures live in `instructions`, not skills.** `seed.ts` concatenates `agents/prompts/*.md` in filename order into the manifest's `instructions`, and compiles `actions/policy.yaml` into `require_approval_for_tools`. Rationale: skills materialize from a git clone into a Daytona sandbox — that reintroduces exactly the latency PR5 engineered away, for near-zero gain at single-domain scale. It also makes every prompt edit a commit-and-push instead of a 20-second local loop, on the thing you will tune most.

*If a judge challenges it:* "Progressive disclosure buys nothing at single-domain scale. Here's the threshold where we'd switch."

**Prompt content:**
- `10-impact-analysis.md` — locate contact points → walk callers → select tests. **Must state that a graph hit is a hypothesis, not a verdict.**
- `20-repro.md` — bump version → run selected tests → read the traceback → report. **Must state: report `UNCOVERED`, never guess, when no test reaches a site.**
- `30-brief.md` — the output shape: dependency, N call sites, M tests run, K failed, the diff, the ask.

`actions/policy.yaml`:

| Target | Approval |
|---|---|
| `github_pr` — PR with test-verified patch | required |
| `github_issue` — affected sites | required |
| `slack` | required (wired in `policy.yaml`, unwired in code — cut item #2) |
| `export` — markdown report | none |

**Acceptance:** one end-to-end mission through the harness produces an impact table and a test report; `tool.approval_required` fires before any write; measure the instructions token count (budget 3–6k — if it hurts, that is the threshold where skills earn their keep).

---

### PR11 — `feat(patch): patch-and-verify loop` — **Phase 1, must ship**

Branch `feat/patch-verify`.

**Reclassified per `PLAN.md` as of `fa73a12`:** the red-to-green loop is Phase 1, not a gated upside. A reproduce-only run is an honest contingency, not a completed Phase 1, and it does not unlock a PR. Plan the day so this lands.

Patch application runs through the **native sandbox's file/shell tools**, driven by the agent — same as PR5. Our code owns validation and the gate, not execution.

```
src/main/agentradar/core/patch.py             NEW
agents/prompts/25-patch.md                    NEW
tests/agentradar/test_patch.py                NEW
tests/agentradar/test_gate.py                 NEW
```

```python
def parse_diff(diff: str) -> Patch: ...
def validate_patch(patch: Patch, allowed_files: list[str]) -> tuple[bool, str]:
    """Reject patches touching files outside the blast radius, or test files themselves."""
def build_verify_result(patch: Patch, before: TestReport, after: TestReport) -> VerifyResult: ...
```

**`validate_patch` must reject edits to test files.** An agent that "fixes" a failure by editing the test has defeated the entire product.

**The gate — the single most important assertion in the codebase:**

```python
def can_act(verify: VerifyResult | None) -> bool:
    """PR tools are unreachable unless a real red→green transition was proven."""
    return verify is not None and verify.verified
```

`tests/agentradar/test_gate.py` asserts: `verify is None` → False; `before` green (nothing was broken) → False; `after` red → False; red→green → True. Wire `can_act` into the action layer in PR12 so a failing verification makes the GitHub tools genuinely unreachable, not merely discouraged.

**Cut item #3:** patch **one** call site well rather than six badly.

**Acceptance:** red → patch → green, end to end; the gate test suite passes; a patch touching a test file is rejected.

---

### PR12 — `feat(actions): github + approval policy`

Branch `feat/actions`.

```
src/main/agentradar/adapters/github.py        NEW
src/main/agentradar/core/policy.py            NEW
tests/agentradar/test_policy.py               NEW
```

```python
class CodeHost(Protocol):
    def open_pr(self, branch: str, title: str, body: str, diff: str) -> str: ...
    def open_issue(self, title: str, body: str) -> str: ...

class GhClient:   # shells out to `gh` — already authenticated on this machine

# core/policy.py — pure
def load_policy(text: str) -> dict[str, bool]: ...
def approval_tool_list(policy: dict[str, bool]) -> list[str]:
    """→ TrueForge `require_approval_for_tools`."""
```

Action target is **this repo**. PR body must embed the before/after test reports — the evidence is the product.

**Acceptance:** deny → zero writes reach GitHub. Approve → the PR and issue exist. `can_act` false → the tool is not reachable at all.

---

### PR13 — `chore(fixtures): event recorder`

Branch `chore/fixtures`. Cut if time is short — but it is the offline demo fallback.

```
scripts/record_fixtures.py                    NEW
fixtures/missions/<name>.jsonl                GENERATED
```

Subscribe to a TrueForge turn, write every event to JSONL. Replays the whole mission with no network — the keyboard-shortcut escape hatch if the live demo fails on stage.

Event names, verified: `turn.created`, `turn.done`, `model.message`, `model.message.delta`, `tool.response`, `tool.approval_required`, `tool.response_required`, `thread.created`, `thread.done`, `mcp.initialize`, `mcp.auth_required`, `sandbox.created`.

---

## Verification — end to end

Run in order. Each maps to a PR.

| # | Check | PR |
|---|---|---|
| 1 | `CLOUD_PROVIDER=openai_compat graph-rca query` works with no AWS credentials | 2 |
| 2 | `find_contact_points("<dep symbol>")` returns real call sites | 3 |
| 3 | Recursive `get_callers` reaches test functions — **or** the path fallback is honestly labelled | 4 |
| 4 | `npx @truefoundry/trueforge@latest` serves `localhost:8790`; the SDK streams a trivial turn | 10 |
| 5 | `mcp-graph` at a localhost URL returns real results from a TrueForge session — **no tunnel** | 3 |
| 6 | Prewarmed **native** sandbox runs the green suite in under 15s — timed, and re-timed after an idle gap | 5 |
| 7 | **Repro is honest:** revert the bump, same tests pass | 5 |
| 8 | `sandbox.created` fires; test output appears in a tool result | 10 |
| 9 | `run_collector` returns rows **plus** a health verdict | 7 |
| 10 | Broken page → degradation → heal → restored coverage | 7 |
| 11 | **Gate:** the PR tool is unreachable while tests are red | 11 |
| 12 | Deny → zero GitHub writes. Approve → PR and issue exist | 12 |
| 13 | Every merged PR reviewed by Qodo; findings resolved or logged in `docs/decisions.md` | all |

---

## Cut list, in order

1. PR13 fixtures recorder
2. Slack target — stays in `policy.yaml`, unwired
3. Multi-site patching — one call site well beats six badly
4. `get_class_info` / inheritance — callers + chains carry it
5. Phase 3 tiered dispatch — already gated, cut without regret

**Never cut:** the sandbox test run, the impact table, self-repair, the approval pause.

---

## Cleanup (part of PR1)

1. Commit **this file** as `docs/build-plan.md` — it is what each PR's coding model is handed as context.
2. `Untitled` and `dumpplan.md` are untracked duplicates of the original product spec. Commit one as `docs/product-spec.md`, delete the other.

**How to hand a PR to a model:** give it `docs/build-plan.md` plus `CLAUDE.md`, and point it at exactly one PR section. The spine rules, the reuse table, and the acceptance criteria are all it needs — do not paste extra context, and do not let one model take two PRs at once.
