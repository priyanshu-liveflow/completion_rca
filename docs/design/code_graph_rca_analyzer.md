# Code-Graph-Aware Static Log Analyzer — Design Document

## Quick Start (for any agent or developer)

```bash
# 1. Prerequisites
brew install redis  # or ensure FalkorDB is available
pip install codegraphcontext  # or: pipx install codegraphcontext

# 2. Index the target repo (creates code graph + lite log index in FalkorDB)
codegraphcontext index /path/to/source/repo

# 3. Verify the graph is populated
redis-cli -s ~/.codegraphcontext/global/db/falkordb.sock \
  GRAPH.QUERY codegraph "MATCH (f:Function) RETURN count(f)"

# 4. Run the analysis
cd /path/to/cua-log-analyzer
export AWS_PROFILE=your-profile  # needs Bedrock access (Opus + Sonnet)
uv run cua-analyzer run \
  --log /path/to/application.log \
  --mode code-rca \
  --repo /path/to/source/repo \
  --verbose

# 5. Visualize the code graph (optional)
redis-cli -s ~/.codegraphcontext/global/db/falkordb.sock \
  GRAPH.QUERY codegraph "MATCH (n)-[r]->(m) RETURN n,r,m LIMIT 50"
# Or with FalkorDB Browser UI:
falkordb-browser --socket ~/.codegraphcontext/global/db/falkordb.sock --port 3000
open http://localhost:3000

# 6. Run tests
uv run pytest tests/ -v

# 7. Generate test log (idwms JWT failure scenario)
cp /tmp/idwms_test.log tests/fixtures/idwms_jwt_failure.log
uv run cua-analyzer run \
  --log tests/fixtures/idwms_jwt_failure.log \
  --mode code-rca \
  --repo /path/to/idwms \
  --verbose
```

**What you need:**
- Python 3.11+ with `uv`
- AWS credentials with Bedrock access (Claude Opus 4 + Sonnet 4)
- FalkorDB running (via codegraphcontext)
- A source repo indexed with `codegraphcontext index`
- A log file from that application

**What happens:**
1. PREPROCESS: parses log → resolves each line to a function in the code graph
2. DECOMPOSE: LLM plans 3-5 independent trace agents
3. TRACE: agents walk the code graph with tools (read_function_source, get_callers, get_callees, etc.)
4. ROUTE: selects 3-4 evaluation lenses based on findings
5. LENS JUDGES: evaluate from different angles (auth flow, error handling, config deps)
6. FINAL JUDGE: synthesizes verdict with confidence score + suggested fix

**Expected output:** Root cause node, confidence %, evidence chain, category, suggested fix.
**Expected cost:** ~$0.50-1.00 per analysis (with prompt caching).
**Expected time:** 2-5 minutes depending on agent count and model latency.

---

## Overview

A generic static log analyzer that converts log files into walkable graph paths, links them to actual code structure (FalkorDB), spins up independent unbiased agents to trace failure paths through the code graph, and uses multi-lens judges to determine root cause. Works like a human debugger: follow the threads, explore the code paths, form independent hypotheses, converge on the answer.

**Not** the CUA agent pipeline. No goals/sub-goals/judge-pass-fail. This is topology-driven, not step-driven.

---

## Core Principles

1. **The log file becomes a walkable graph** — every log entry is a node linked to the actual function node in the code graph. Agents walk the graph, not read text.
2. **Graph = topology, Logs = actual path** — the code graph shows what CAN connect; logs show what DID execute.
3. **Branch at ambiguity, don't force** — if a log line could come from multiple functions, create parallel paths. Both get explored. The judge decides.
4. **Unbiased parallel investigation** — trace agents don't see each other's work. No contamination.
5. **Proof required** — every agent and judge must cite specific log lines, specific code paths, specific nodes. No unsupported opinions.
6. **Generic** — domain knowledge is YAML config, not code. Swap config for different apps/languages.
7. **Graceful degradation** — code graph and JIRA KB are both optional. Works with whatever is available.

---

## Data Sources

| Source | Storage | Role | Required? |
|--------|---------|------|-----------|
| Code Graph | FalkorDB (CodeGraph) | Structure — classes, functions, CALLS/INJECTS/INHERITS edges, full source code | No (enrichment) |
| Lite Log Index | FalkorDB (same graph) | Bridge — maps static log text → function nodes, stores variable types/names/regex | No (built from code graph) |
| JIRA KB | ChromaDB | History — past RCAs with MENTIONS edges to code nodes | No (enrichment) |
| Runtime Log | Input file | Evidence — the actual execution trace to analyze | **Yes** |
| Domain Config | YAML | Knowledge — log format, ignore patterns, entry points, models | **Yes (minimal)** |

---

## Supported Languages

Built-in stack trace detection and log pattern recognition:

| Language | Stack Trace Pattern | Log Patterns |
|----------|-------------------|--------------|
| Java | `at pkg.Class.method(File.java:42)` + `Caused by:` chains | SLF4J, Log4j, java.util.logging |
| Python | `File "/path/file.py", line 42, in func` + `Traceback` | logging, structlog, loguru |
| C++ | `#0 0x... in func at /path/file.cpp:42` (gdb/asan) | spdlog, glog, std::cerr |
| Rust | `thread 'main' panicked at 'msg', src/file.rs:42` | tracing, log crate, println! |
| Go | `goroutine N [running]:` + `pkg/file.go:42 +0x...` | log, zap, logrus |
| PowerShell | `At C:\path\script.ps1:42 char:5` + CategoryInfo | Write-Host, Write-Error, Write-Verbose |

Language is auto-detected from `f.lang` on function nodes in the code graph. Stack trace patterns are built-in — user does NOT configure these.

---

## Indexing (per repo, updated on changes)

### Step 1: Code Graph (codegraphcontext — existing)

```bash
codegraphcontext index /path/to/repo
```

Creates:
- Node types: Repository, Directory, File, Class, Function, Interface, Enum, ExternalClass, DbTable, Parameter, Property, Annotation
- Relationships: CONTAINS, CALLS, INJECTS, INHERITS, IMPORTS, READS, WRITES, HAS_PARAMETER
- Stores full source code on Function nodes (`f.source`)
- Stores file path, line numbers, language, bases, decorators

### Step 2: Lite Log Index (our custom layer)

Scans every `f.source` in the graph for the indexed repo. For each log statement found:

Creates `LogTemplate` nodes:
```
(:LogTemplate {
  static_fragments: ["Converting Map to ", ""],
  full_static_text: "Converting Map to SCIMSecuritySystemDTO",
  line_in_function: 3,
  log_level: "info",
  language: "java",
  dynamic_parts: [
    {variable: "map", type: "Map<String, Object>", position: "suffix"}
  ],
  regex_pattern: "Converting Map to .+"
})
```

Creates edges:
```
(:LogTemplate)-[:EMITTED_BY]->(:Function)
(:Function)-[:CONTAINED_IN]->(:File)
```

Handles duplicates: same static text from multiple functions → multiple `EMITTED_BY` edges. The graph structure preserves all possibilities.

**Variable metadata stored per dynamic part:**
- Variable name (from source)
- Variable type (from declaration/signature)
- How it's logged (concatenation, format string, interpolation)
- Expected pattern (regex derived from type — UUID, email, numeric, etc.)

**For concatenated/interpolated logs:**
- Extract the **longest static fragments** (parts between variables)
- `log.info("User " + userId + " accessed " + resource)` → fragments: `["User ", " accessed "]`
- At match time, look for lines containing ALL fragments in order

### Step 3: JIRA Linking (if KB populated)

Parse JIRA tickets → extract code references (function names, class names, file paths, error patterns mentioned in RCA text).

Create edges:
```
(:Ticket)-[:MENTIONS]->(:Function)
(:Ticket)-[:MENTIONS]->(:Class)
```

### Step 4: Repository Metadata

Stored on Repository node:
```
(:Repository {
  name: "idwms",
  path: "/path/to/repo",
  branch: "eic-trunk",
  commit_hash: "abc123f",
  indexed_at: "2026-05-27T16:08:00Z"
})
```

---

## Staleness Check (before every analysis)

1. Read `commit_hash` from Repository node
2. Run `git rev-parse HEAD` on the actual repo
3. If different → prompt user: "Repo has new commits. Reindex?"
4. If yes → `git pull` + reindex (incremental: only rebuild LogTemplate nodes for functions whose source changed)
5. If no → proceed with warning flag
6. Always confirm branch with user before first index

---

## Domain Config (YAML)

### Minimum viable (user must provide):

```yaml
repo: "idwms"
log_format:
  entry_start: "^\\d{4}-\\d{2}-\\d{2}"
```

### Full config:

```yaml
repo: "idwms"
branch: "eic-trunk"

log_format:
  entry_start: "^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}"

ignore_patterns:
  - "HealthCheck.*status=UP"
  - "ScheduledTask.*heartbeat"
  - "metrics\\.export"
  - "HikariPool.*statistics"

error_markers:
  - level: "ERROR"
  - pattern: "Exception|NullPointer|Timeout|Failed|refused"

entry_points:
  - ".*Controller"
  - ".*Listener"
  - ".*Scheduler"

threading:
  thread_id_pattern: "\\[([^\\]]+)\\]"
  # OR
  request_id_pattern: "requestId=([\\w-]+)"

multi_service:
  service_id_pattern: "\\[([\\w-]+)\\]"
  service_map:
    "idwms": { repo: "idwms", branch: "eic-trunk" }
    "connectorms": { repo: "connectorms", branch: "main" }
    "cua-agent": { repo: "agenticai", branch: "master" }

models:
  light: "us.anthropic.claude-sonnet-4-20250514-v1:0"
  default: "us.anthropic.claude-sonnet-4-20250514-v1:0"
  heavy: "us.anthropic.claude-opus-4-6-v1"

cost_limits:
  max_trace_agents: 5
  max_turns_per_agent: 8
  max_lens_judges: 4
  budget_cap_usd: 5.00
  skip_judges_if_single_trace: true
  skip_heavy_model_if_obvious: true
  early_exit_confidence: 0.95

prompt_caching: true
```

---

## Log Line Resolution Algorithm

The most critical component. Uses **sequential constrained walk with graph reachability scoring** — not binary match/no-match.

### Confidence Tiers

| Tier | Confidence | Source | Example |
|------|-----------|--------|---------|
| 1 (HIGH) | >0.9 | Stack trace frames | `at c.s.s.idwms.service.EntitlementService.getPrivilegesList(EntitlementService.java:45)` — exact class+method+file+line |
| 2 (MEDIUM) | 0.6-0.9 | Unique static text match | `"Converting Map to SCIMSecuritySystemDTO"` — only one function has this |
| 3 (LOW) | 0.3-0.6 | Contextual disambiguation | `"Processing request"` — 5 functions have it, but graph reachability from previous anchor narrows to 1 |
| 4 (UNMAPPED) | <0.3 | Can't resolve | Framework logs, completely generic text |

### Algorithm

```
Input: ordered log entries (partitioned by thread/service), lite log index, code graph

1. SEED
   Find first line with unique static text match (Tier 1 or 2)
   OR use entry_points from config as starting constraint
   → This is your first anchor in the graph.

2. FOR each subsequent line:
   a. Get candidate functions from static text match (lite index lookup)
   b. If 0 candidates → mark UNMAPPED, classify as framework/unknown, continue
   c. If 1 candidate → anchor (Tier 2), update previous_anchor
   d. If N candidates → SCORE each:

      score(candidate, previous_anchor) =
          static_match_quality    (0-1: fragment coverage of static text)
        + reachability_score      (0-1: 1/hop_distance from previous anchor via CALLS edges)
        + variable_hint           (0-0.3: type/pattern match on dynamic values)
        + thread_continuity       (0-0.2: same thread/request as previous anchor)

   e. If top score > 0.5 AND gap to second > 0.2 → anchor to top candidate
   f. If top two scores within 0.2 → BRANCH (create parallel paths, both explored)
   g. If no score > 0.5 → mark UNMAPPED
   h. Update previous_anchor for next iteration

3. RETURN PATHS
   If resolved function is an ancestor of previous anchor (not a callee),
   mark as "returned to" — execution went back up the stack.

4. JUMPS
   If resolved function is reachable but N hops away,
   insert implicit nodes for intermediate functions (they executed but didn't log).

5. COVERAGE REPORT
   Report: "Mapped X% of log entries to code graph nodes (N/M entries)"
   If < 20%: warn "Insufficient coverage for reliable analysis"
```

### Max Hops

Configurable, default 6 (matches deepest DI chain found in real codebases). Beyond that, reachability_score = 0.

### First Line Problem

Use `entry_points` from YAML config as initial constraint. If first matchable line is in a Controller/Listener/Scheduler, that's the seed. Fallback: first unique static text match anywhere.

### Framework/Library Logs

Lines from Spring, Hibernate, Tomcat, etc. won't be in the code graph. They become:
- **Framework nodes** — recognized by built-in patterns, labeled with framework name
- **Pass-through** in the walkable path — agents know framework is in the middle but don't debug it
- **Context** between application-level anchors

Typical Java app: 30-50% of lines are framework. The system works with the 50-70% that ARE application code as anchors, and treats framework lines as context.

### What Makes This Work

You don't need 100% mapping. You need enough **anchors** (Tier 1+2) to establish the path skeleton. Gaps between anchors are inferred from graph structure. If you have anchor at FuncA and next anchor at FuncC, and the graph shows A→B→C, you know B executed even without a log line for it.

Stack traces are the highest-value input — they give you the exact execution path with zero ambiguity. Most ERROR paths will have stack traces. The resolution algorithm is mainly for INFO/DEBUG lines that establish the flow leading up to the error.

---

## Multi-Threading Support

### Detection

If `threading.thread_id_pattern` is in config, extract thread/request ID from each log line.

### Processing

1. **Partition** log entries by thread/request ID
2. **Run resolution algorithm independently** per thread
3. Each thread gets its own walkable path
4. Cross-thread interactions (shared resources, locks) become `CROSS_THREAD` edges if detectable

### Without Thread IDs

If no thread identifier available:
- System flags: "Log appears multi-threaded but no thread identifier found"
- Resolution algorithm still runs but with lower confidence
- Reachability scoring may pick wrong candidate when threads interleave
- Parallel paths (branching) handles some of this — both possibilities explored

---

## Multi-Service Support

For aggregated logs containing lines from multiple services (ELK, CloudWatch, k8s).

### Detection

Service identifier extracted via `multi_service.service_id_pattern`:
```
2026-05-27 10:15:04 [idwms-pod-abc] ERROR c.s.s.idwms.service.EntitlementService - Failed
2026-05-27 10:15:04 [connectorms-pod-xyz] INFO c.s.s.connector.ConnectorController - Received
```

### Processing

1. **Partition** by service ID first
2. Each service resolves against its **own repo/graph/lite-index** (from `service_map` config)
3. **Cross-service edges**: when service A logs "calling endpoint X" then service B logs "received request" → create `CROSS_SERVICE_CALL` edge between the two paths
4. Correlation via: request ID matching, temporal proximity, API endpoint matching
5. **Trace agents can span services** — switch which graph they query based on which service the path enters
6. **Root cause may be in a different service** — idwms fails because connectorms returned error. Propagation crosses service boundary.

### Staleness

Each service's repo checked independently. One stale repo doesn't block analysis of others.

### Walkable Path (multi-service)

```
idwms path:        Controller → Service → ECMRestClient ──CROSS_SERVICE_CALL──┐
                                                                               │
connectorms path:                     ConnectorController → getConnector ←─────┘ (error here)
```

---

## Analysis Pipeline

### Phase 0: PREPROCESS (log → walkable graph path)

**Input:** Raw log file + repo name + domain config

**Process:**

1. **Parse log entries** — use `entry_start` to identify entry boundaries. Everything between one match and the next = one log entry (handles multi-line stack traces, JSON dumps).
2. **Partition** — by service (if multi-service), then by thread (if thread IDs available)
3. **Filter** — remove entries matching `ignore_patterns`
4. **Auto-detect structure** — identify stack traces, levels, class references using built-in language patterns
5. **Run resolution algorithm** — per partition, sequential constrained walk with scoring
6. **Build walkable path** — LogEntry nodes linked by NEXT edges, ORIGINATED_FROM edges to Function nodes, JUMP_TO for execution jumps, branching at ambiguity points

**Output:** Walkable graph path(s) overlaid on code graph. Error points flagged. Coverage report.

**LogEntry node structure:**
```
(:LogEntry {
  line_number: 4523,
  line_end: 4535,
  raw_text: "...",
  timestamp: "2026-05-27T10:15:04",
  level: "ERROR",
  static_text: "Failed to process",
  dynamic_values: ["user-123", "entitlement-456"],
  service: "idwms",
  thread_id: "http-thread-1",
  resolution_confidence: 0.85,
  resolution_tier: 2,
  has_stack_trace: true
})

Edges:
  -[:NEXT]-> (next LogEntry in same thread/service)
  -[:ORIGINATED_FROM]-> (Function node(s) in code graph — SAME nodes, not copies)
  -[:JUMP_TO]-> (LogEntry where execution jumps)
  -[:HAS_STACK_FRAME]-> (stack frame entries linking to Function nodes)
  -[:CROSS_SERVICE_CALL]-> (LogEntry in different service's path)
  -[:CROSS_THREAD]-> (LogEntry in different thread's path, if interaction detected)
```

**Node classification:**
- **Mapped** — linked to application code graph node
- **Framework** — recognized as Spring/Django/etc, not in graph, labeled
- **Unknown** — can't identify, kept as context

---

### Phase 1: DECOMPOSE

**Input:** Preprocessed walkable path(s) + error points + coverage report

**Process:** LLM-driven (default model). Examines the path and decides investigation strategy.

**Decisions:**
- How many trace agents to spin up
- What each investigates (scope + starting node + direction)
- **Shared parent agents** — if multiple errors branch from common ancestor, one agent for shared root, child agents for diverging paths
- Model assignment per agent (light/default/heavy based on complexity)
- Tool access per agent (graph_only vs graph_plus_codebase) based on graph coverage
- Which paths are independent (parallel) vs dependent (sequential)
- Flag error log lines for investigation (respecting ignore patterns)

**Output:** N agent assignments:
```
AgentAssignment:
  id: str
  starting_node: str
  scope: str
  direction: "backward" | "forward" | "both"
  model: "light" | "default" | "heavy"
  tools: "graph_only" | "graph_plus_codebase"
  parent_agent: str | None
  context_from_parent: str | None
```

---

### Phase 2: TRACE (N agents, parallel, isolated, unbiased)

**Default toolset:**
- `query_code_graph` — Cypher queries on FalkorDB
- `read_function_source` — get `f.source` from graph node
- `walk_log_path` — follow NEXT/ORIGINATED_FROM edges
- `get_callers` — who calls this function
- `get_callees` — what does this function call
- `get_injections` — what services does this class depend on
- `get_inheritance` — parent/child class chain

**Extended toolset (opt-in):**
- `grep_codebase` — search actual source files
- `read_file` — read full source file from disk
- `find_references` — where is this symbol used
- `list_directory` — explore file structure

**Agent behavior:**
1. Start at assigned node
2. Navigate edges (CALLS, INJECTS, INHERITS) — decision tree traversal
3. Use log evidence to determine which branch was taken
4. Read `f.source` for implementation detail when needed
5. Extended tools when graph has gaps
6. Cycle detection — flag and stop if revisiting nodes
7. Consider: could this be input/data issue, not code bug?

**Rules:**
- Do NOT see other agents' work (except parent→child context)
- Must provide proof: specific log lines, code path, node, WHY
- No opinions without evidence

**Output:**
```
TraceReport:
  agent_id: str
  path_walked: list[NodeReference]
  evidence: list[Evidence]
  assessment: str
  root_cause_node: str | None
  is_input_issue: bool
  confidence: float
  dead_ends: list[str]
```

---

### Phase 3: JUDGE (multiple lenses, dynamic)

**Router agent** examines all trace reports, decides which lenses to apply. Dynamic, not fixed:
- Code defect (logic error, NPE, wrong condition)
- Input/data issue (bad data, missing field, wrong format)
- Config/infra (wrong config, service down, timeout)
- Integration/dependency (downstream failure, API contract broken)
- Concurrency (race condition, deadlock, thread safety)
- State corruption (stale cache, dirty read)
- Others generated based on evidence

**Each lens judge (heavy model):**
- Receives ALL trace reports
- Receives JIRA/RCA context (MENTIONS edges to relevant nodes)
- Evaluates from specific angle
- Must cite evidence, provide convincing proof

**Output:**
```
LensVerdict:
  lens: str
  verdict: str
  root_cause: str
  confidence: float
  cited_evidence: list[Evidence]
  reasoning: str
  contradicts: list[str]
```

---

### Phase 4: FINAL JUDGE (meta-scorer)

**Input:** All lens verdicts + trace reports

**Scoring criteria:**
- Evidence strength — specific, verifiable citations?
- Logical consistency — reasoning chain holds?
- Coverage — explains ALL symptoms, not just some?
- Parsimony — simpler explanation preferred

**Output:**
```
FinalVerdict:
  root_cause: str
  root_cause_node: str
  category: "code" | "input" | "config" | "infra" | "integration" | "concurrency"
  confidence: float
  evidence_chain: list[Evidence]
  historical_matches: list[Ticket]
  explanation: str
  suggested_fix: str | None
```

---

## Cost Control

### Model Assignment

| Component | Model | Reasoning |
|-----------|-------|-----------|
| Decompose | Opus | Strategic decisions — what to investigate, how to split work |
| Trace agents | Sonnet | Structured work — follow edges, read source, collect evidence |
| Router | Sonnet | Pattern matching — pick lenses based on trace outputs |
| Lens judges | Opus | Deep reasoning — synthesize traces, weigh contradictions |
| Final judge | Opus | Meta-reasoning — score judges on merit |

### Token Discipline

**The cost driver is input tokens, not output.** Opus = $15/M input ($3/M cached), Sonnet = $3/M input ($0.60/M cached). Strategy:

1. **Outputs are strict and small** — BAML-enforced structured data, not prose. Node IDs, edge paths, confidence floats, line number references. No explanations unless required.
2. **Never send full log file to LLM** — preprocessing is deterministic (zero LLM cost). Agents only see their relevant slice.
3. **Concat small reports over runs** — judges receive concatenated structured outputs from agents, not raw transcripts.
4. **Subgraph slicing** — each trace agent gets ONLY their starting node + N-hop neighborhood + relevant log entries. Not the full graph.
5. **Prompt caching on everything** — system prompt + graph context + domain knowledge is the cached prefix. Only the specific query varies per turn.

### Token Budgets

| Component | Max input | Max output | Cached portion | Effective input (after cache) |
|-----------|-----------|------------|----------------|-------------------------------|
| Decompose | 5K | 500 | System prompt + walkable path summary (~4K cached) | ~1K |
| Trace agent (per turn) | 3K | 300 | System prompt + subgraph slice (~2.5K cached) | ~500 |
| Router | 2K | 200 | System prompt (~1.5K cached) | ~500 |
| Lens judge | 4K | 500 | System prompt + domain context (~2K cached) | ~2K |
| Final judge | 3K | 600 | System prompt (~1.5K cached) | ~1.5K |

### Prompt Caching Strategy

Every LLM call structured as:
```
[CACHED PREFIX — same across turns/agents]
  - System prompt (role, rules, output format)
  - Domain knowledge (from YAML config)
  - Graph context (relevant subgraph structure)
  - BAML type definitions

[UNCACHED SUFFIX — varies per call]
  - Specific assignment/query
  - Current evidence/findings
```

Bedrock prompt caching: first call pays full price, subsequent calls to same agent pay ~20% for the cached prefix. Multi-turn trace agents benefit most (3-5 turns, prefix cached after turn 1).

### Realistic Cost Estimates (with caching)

| Scenario | Components | Effective tokens (post-cache) | Est. Cost |
|----------|-----------|-------------------------------|-----------|
| Obvious (stack trace) | Preprocess only | 0 LLM tokens | $0.00 |
| Simple | Decompose + 1 agent (3 turns) + 1 judge | ~8K in, ~1K out | ~$0.08 |
| Medium | Decompose + 3 agents (3 turns each) + router + 2 judges + final | ~20K in, ~3K out | ~$0.25 |
| Complex | Decompose + 5 agents (5 turns each) + router + 4 judges + final | ~45K in, ~5K out | ~$0.55 |

### Circuit Breakers

```yaml
cost_limits:
  max_trace_agents: 5
  max_turns_per_agent: 8
  max_lens_judges: 4
  budget_cap_usd: 2.00
  skip_judges_if_single_trace: true
  skip_heavy_model_if_obvious: true
  early_exit_confidence: 0.95
```

### Cheap Path (short-circuit)

If preprocessing finds a stack trace that maps directly to graph nodes with zero ambiguity → skip decompose/trace/judges entirely. Report the mapped path + root cause. Cost: $0.

Most real failures WILL have stack traces. The expensive multi-agent path is for subtle failures (silent errors, wrong behavior without exceptions, performance degradation).

### Cost Reduction Summary

| Strategy | Savings |
|----------|---------|
| Prompt caching (Bedrock) | ~80% on cached prefix per turn |
| Preprocess is deterministic | Zero LLM cost for path construction |
| Strict BAML outputs | Output tokens capped at 300-600 per call |
| Subgraph slicing | Agents see 1-3K context, not full graph |
| Early exit at 0.95 confidence | Skip remaining agents/judges |
| Skip judges for obvious cases | Single confident trace = done |
| Model tiering | Sonnet for traces ($3/M), Opus only for judges ($15/M) |

---

## Shared State & Data Models

### Graph (FalkorDB) — persistent shared state

All agents read from same graph. Preprocessor writes LogEntry nodes. Two layers:
- **Bottom:** Code structure (codegraphcontext)
- **Top:** Log flow + templates (our layer, edges point into bottom layer's nodes)

### Pydantic — typed interface between blocks

```python
class LogEntry(BaseModel):
    line_number: int
    line_end: int
    raw_text: str
    level: str
    static_text: str
    dynamic_values: list[str]
    timestamp: datetime
    originated_from: list[str]
    resolution_confidence: float
    resolution_tier: int
    service: str | None
    thread_id: str | None
    stack_trace: StackTrace | None

class WalkablePath(BaseModel):
    entries: list[LogEntry]
    branches: list[BranchPoint]
    error_points: list[int]
    coverage_pct: float
    service: str

class AgentAssignment(BaseModel):
    id: str
    starting_node: str
    scope: str
    direction: Literal["backward", "forward", "both"]
    model: Literal["light", "default", "heavy"]
    tools: Literal["graph_only", "graph_plus_codebase"]
    parent_agent: str | None
    context_from_parent: str | None

class TraceReport(BaseModel):
    agent_id: str
    path_walked: list[str]
    evidence: list[Evidence]
    assessment: str
    root_cause_node: str | None
    is_input_issue: bool
    confidence: float
    dead_ends: list[str]

class LensVerdict(BaseModel):
    lens: str
    verdict: str
    root_cause: str
    confidence: float
    cited_evidence: list[Evidence]
    reasoning: str

class FinalVerdict(BaseModel):
    root_cause: str
    root_cause_node: str
    category: Literal["code", "input", "config", "infra", "integration", "concurrency"]
    confidence: float
    evidence_chain: list[Evidence]
    historical_matches: list[str]
    explanation: str
    suggested_fix: str | None
```

### BAML — structured LLM output validation

Every LLM call uses BAML type definitions to enforce output structure at generation time.

---

## Escape Character Handling

Log lines can contain: nested JSON, regex patterns, Unicode, null bytes, control characters, multi-line stack traces.

- Log format from YAML defines entry boundaries only
- Message portion treated as raw bytes
- Template matching uses static portions — dynamic sections captured as opaque strings
- FalkorDB storage uses proper escaping
- Multi-line entries grouped by entry boundary detection, not line-by-line

---

## What Exists Today

- FalkorDB: 4 repos indexed (CUA/Python, ConnectorMS/Java, WindowsConnectorMS/PS1, idwms/Java)
- idwms: branch `eic-trunk` tagged, 530 non-test classes, 73% connected, 6-hop DI chains, 2314 CALLS, 173 INJECTS, circular deps present
- Full source code on function nodes (`f.source`) — contains log statements
- JIRA KB: ChromaDB `jira_conn`, 518 issues
- codegraphcontext CLI + FalkorDB writable via Python client
- Existing block library infrastructure (Block protocol, BlockContext, RunMetrics)

---

## What Needs to Be Built

| # | Component | Priority | Status |
|---|-----------|----------|--------|
| 1 | Lite Log Index Builder (parse f.source → LogTemplate nodes) | High | ✅ Done (codegraphcontext handles this) |
| 2 | Log Resolution Algorithm (sequential constrained walk + scoring) | High | ✅ Done (resolve/resolver.py — tier 1-4 resolution) |
| 3 | Log Preprocessor (entry parsing, partitioning, walkable path construction) | High | ✅ Done (preprocess/parser.py + resolve/resolver.py) |
| 4 | Staleness Checker (commit hash + user prompt + incremental reindex) | High | ✅ Done (staleness.py) |
| 5 | Domain Config Schema (YAML validation + defaults) | High | ✅ Done (config.py — DomainConfig dataclass) |
| 6 | BAML Type Definitions (output schemas) | High | ⚠️ Skipped — using parse_json with fallback instead |
| 7 | Multi-line Entry Parser (stack traces, JSON dumps, continuations) | High | ✅ Done (preprocess/stack_trace.py + parser.py) |
| 8 | Language-specific Detectors (Java/Python/C++/Rust/Go/PS1) | Medium | ⚠️ Partial — Java done, others TODO |
| 9 | Decompose Block (LLM investigation strategy) | High | ✅ Done (decompose.py) |
| 10 | Trace Agent (graph walk + source read + evidence collection) | High | ✅ Done (trace_agent.py — 9 tools, multi-turn) |
| 11 | Router Agent (dynamic lens selection) | Medium | ✅ Done (judges.py — route function) |
| 12 | Lens Judges (angle-specific evaluation) | Medium | ✅ Done (judges.py — run_lens_judge) |
| 13 | Final Judge (meta-scoring) | Medium | ✅ Done (judges.py — run_final_judge) |
| 14 | JIRA→Graph Linker (MENTIONS edges) | Medium | ❌ TODO |
| 15 | Multi-service Partitioner + cross-service linking | Medium | ❌ TODO |
| 16 | Cost Tracker + Circuit Breakers | Medium | ⚠️ Partial — budget nudge + early exit, no USD tracking |

---

## Visualization

Users can visualize and persist the walkable path + code graph traversal as SVGs.

### What gets visualized

1. **Walkable Path** — the log-derived execution flow with nodes colored by resolution tier:
   - Green: Tier 1 (stack trace, high confidence)
   - Blue: Tier 2 (unique static match)
   - Yellow: Tier 3 (contextual disambiguation)
   - Gray: Tier 4 (unmapped/framework)
   - Red border: error points
   - Dashed edges: JUMP_TO (execution jumps)
   - Forked paths: ambiguity branches

2. **Code Graph Subgraph** — the relevant portion of the code graph that the walkable path touches:
   - Function nodes with CALLS/INJECTS/INHERITS edges
   - ORIGINATED_FROM edges linking LogEntry → Function
   - MENTIONS edges from JIRA tickets (if present)
   - Highlighted: the actual path taken (bold edges)
   - Dimmed: available but not-taken edges (context)

3. **Trace Agent Paths** — per-agent visualization of their graph walk:
   - Starting node marked
   - Path walked (ordered, numbered)
   - Dead ends marked with X
   - Root cause node highlighted

4. **Final RCA Summary** — combined view:
   - Failure propagation tree (root cause → symptoms)
   - Cross-service edges (if multi-service)
   - JIRA ticket links overlaid

### Implementation

Uses `graphviz` Python library (already available). SVGs persisted to configurable output directory with timestamps:

```
output/
  {run_id}/
    walkable_path_{timestamp}.svg
    code_subgraph_{timestamp}.svg
    trace_agent_{agent_id}_{timestamp}.svg
    rca_summary_{timestamp}.svg
```

### CLI flag

```bash
uv run cua-analyzer run --log /path/to/log --mode code-rca --visualize --output ./output/
```

`--visualize` generates SVGs at each phase. Without it, no visualization overhead.

---

## Open Design Decisions

1. **LogEntry nodes — persistent or ephemeral?** Keep walkable paths for re-analysis or delete after each run?
2. **JIRA parsing — regex or LLM?** Extracting function/class names from ticket text.
3. **Graph isolation per run** — multiple concurrent analyses. Namespace LogEntry nodes by run ID?
4. **Agent memory across runs** — remember findings from previous analyses of same repo?
5. **Confidence calibration** — thresholds for model assignment need empirical tuning.
6. **Cross-service correlation** — request ID matching vs temporal proximity vs API endpoint matching. Which is primary?

---

## Architecture Diagram

See: `docs/design/code_graph_rca_architecture.svg` (generated 2026-05-27T18:28)

---

## Static Fragment Extraction: Research & Implementation Approach

### The Problem

Extracting static text templates from log statements in source code requires handling per-language, per-framework logging styles:

```java
// Java - multiple styles in one codebase
log.info("User " + userId + " accessed " + resource);           // concatenation
log.info("User {} accessed {}", userId, resource);              // SLF4J placeholders
log.info(String.format("User %s accessed %s", userId, resource)); // format
logger.log(Level.INFO, "User {0} accessed {1}", new Object[]{userId, resource}); // MessageFormat
```

### Existing Open Source Tools

| Tool | Approach | Relevance |
|------|----------|-----------|
| [PlatformLab/Log-Analyzer](https://github.com/PlatformLab/Log-Analyzer) | **Source-code static analysis** of log statements in Spark/C/RAMCloud. Heuristic-based: splits on `+` and `)` at depth 0, handles `s"$var"` interpolation, `%` format specifiers, triple quotes. Python scripts. | **Directly relevant** — same problem, heuristic approach for Java/Scala/C. Reference implementation for our fragment extraction. |
| [logpai/Drain3](https://github.com/logpai/Drain3) | **Runtime log template mining** — clusters log messages by token similarity using a parse tree. No source code needed. | Useful as **fallback** when source-based extraction fails. Can mine templates from the log file itself, then we match mined templates to functions. |
| [SRT-Lab/ULP](https://github.com/SRT-Lab/ULP) | **Runtime log parsing** — pattern matching + frequency analysis on log data. 89.2% accuracy on LogPai benchmark. | Fallback/validation — can verify our source-extracted templates against actual log output. |
| [LLM-SrcLog](https://arxiv.org/html/2512.04474) (2024 paper) | **Hybrid**: cross-function static code analyzer + LLM-based white-box template extractor + black-box clustering for unmatched. Post-processing to distinguish constants from variables. | **Most relevant research** — exactly our problem. Their approach: static analysis first, LLM for hard cases, clustering for remainder. |
| [semgrep](https://github.com/semgrep/semgrep) | AST-based pattern matching. Can write rules like `log.info($MSG)` to find all log calls and extract `$MSG`. | **Tool for extraction** — use semgrep patterns to find log statements, then parse the matched arguments. |
| [tree-sitter](https://github.com/tree-sitter/tree-sitter) + [py-tree-sitter](https://github.com/tree-sitter/py-tree-sitter) | Incremental AST parser for 100+ languages. Python bindings. Can extract string literals, method invocations, concatenation expressions. | **Primary implementation tool** — parse `f.source` into AST, walk to find log calls, extract string literal nodes vs expression nodes. |
| [logparser3](https://pypi.org/project/logparser3/) (logpai toolkit) | 13 log parsing algorithms (Drain, Spell, AEL, LenMa, etc.) benchmarked on 16 datasets. | Reference for **runtime template mining** accuracy benchmarks. |

### Recommended Implementation: tree-sitter + heuristics

**Why tree-sitter over regex:**
- Handles nested expressions, multi-line statements, string concatenation AST properly
- Language grammars already exist for all 6 target languages
- Can distinguish `string_literal` nodes from `identifier`/`method_invocation` nodes in the AST
- Handles edge cases regex can't: ternary operators in log args, method chains, etc.

**Algorithm per language:**

1. Parse `f.source` with tree-sitter (language from `f.lang`)
2. Find all method invocations matching log patterns (e.g., `log.info(...)`, `logger.error(...)`)
3. Extract the argument AST subtree
4. Walk the argument tree:
   - `string_literal` nodes → static fragment
   - `binary_expression` with `+` operator → recurse left/right, collect string_literal children
   - `method_invocation` on String (`.format()`) → extract format string, mark `%s`/`{}` as dynamic
   - Everything else (identifiers, method calls, ternaries) → dynamic placeholder
5. Output: ordered list of static fragments + dynamic slot metadata

**Fallback for unparseable cases:**
- If tree-sitter can't parse (malformed source, unsupported construct) → skip that log statement
- If < 50% of log statements in a function are parseable → flag function as "low coverage"
- Use Drain3 as runtime fallback: mine templates from the actual log file, then fuzzy-match mined templates to functions by co-occurrence

### Per-Language Patterns

| Language | Log call patterns | String construction |
|----------|------------------|---------------------|
| Java | `log.{info,debug,warn,error}(...)`, `logger.{...}(...)`, `LOG.{...}(...)` | `+` concat, SLF4J `{}`, `String.format("%s")`, `MessageFormat` |
| Python | `logging.{info,debug,...}(...)`, `logger.{...}(...)`, `log.{...}(...)` | f-strings `f"...{var}..."`, `.format()`, `%` operator, `+` concat |
| C++ | `LOG(INFO) << ...`, `spdlog::info(...)`, `fmt::format(...)` | `<<` stream, `fmt::format("{}")`, `printf("%s")` |
| Rust | `info!(...)`, `error!(...)`, `tracing::info!(...)`, `log::info!(...)` | `format!("...{}")`, string interpolation in macros |
| Go | `log.Printf(...)`, `zap.Info(...)`, `logrus.Info(...)` | `fmt.Sprintf("%s")`, string concat `+` |
| PowerShell | `Write-Host ...`, `Write-Error ...`, `Write-Verbose ...` | `"text $var"` interpolation, `-f` format operator |

---

## Known Limitations & Mitigations

### 1. Resolution algorithm — minor concern in practice

The reachability scoring formula (`1/hop_distance`) initially seemed problematic in a dense graph. However, the static text match pre-filters candidates to 1-5 functions per log line (not hundreds). Reachability is just a tiebreaker for the rare case where 2-3 functions share the same log message.

**Resolution power breakdown:**
- Static text match: ~90% (narrows to 1-5 candidates)
- Sequential context (previous anchor): ~9% (constrains reachability)
- Reachability scoring: ~1% (tiebreaker for rare ties)

Simple `1/hop_distance` is likely sufficient. `--debug-resolution` flag available if tuning ever needed.

### 2. JUMP_TO implicit nodes are hypotheses, not observations

Inserting intermediate nodes between two anchors risks hallucinating execution paths (dynamic dispatch, reflection, multiple possible paths).

**Mitigation:**
- Implicit nodes marked: `is_inferred: true, inference_confidence: 0.6`
- Only insert if there's a **single** path between anchors at that distance
- If multiple paths exist → mark as jump with "path ambiguous", don't insert
- Trace agents give inferred nodes low weight in reasoning

### 3. Persistence & isolation — decided

**Ephemeral + namespaced by run ID.**
```
(:LogEntry { run_id: "run_2026-05-27_abc123", ... })
```
Cleanup after analysis completes or after configurable TTL. Persistence is v2.

### 4. Evaluation plan (v2)

One manually-annotated log as ground truth:
```yaml
# eval/ground_truth/idwms_sample.yaml
log_file: "idwms.log"
entries:
  - line: 1
    function: "EntitlementsController.getPrivilegesList"
  - line: 2
    function: "EntitlementService.getPrivilegesList"
expected_root_cause: "AccountsFilterValueStrategy.apply:38"
expected_path: ["EntitlementsController", "EntitlementService", "AccountsFilterValueStrategy"]
```

Metrics: resolution accuracy (% lines correctly mapped), path accuracy, RCA accuracy.

### 5. Static fragment extraction is non-trivial but solvable

See "Static Fragment Extraction" section above. tree-sitter + per-language heuristics handles 80%+ of cases. Drain3 as runtime fallback for the rest. Accept partial coverage — 70% correctly indexed is better than 100% with errors.

---

## References

- [PlatformLab/Log-Analyzer](https://github.com/PlatformLab/Log-Analyzer) — Static analysis of log statements in source code
- [logpai/Drain3](https://github.com/logpai/Drain3) — Streaming log template miner
- [SRT-Lab/ULP](https://github.com/SRT-Lab/ULP) — Universal Log Parsing (ICSME'22)
- [LLM-SrcLog](https://arxiv.org/html/2512.04474) — Proactive log template extraction via LLMs + static analysis
- [logpai/logparser](https://github.com/logpai/logparser) — 13 log parsing algorithms benchmarked
- [tree-sitter/py-tree-sitter](https://github.com/tree-sitter/py-tree-sitter) — Python bindings for AST parsing
- [semgrep](https://github.com/semgrep/semgrep) — AST-based pattern matching for code
- [Salesforce/LogAI](https://github.com/salesforce/logai) — Log analytics and intelligence library
