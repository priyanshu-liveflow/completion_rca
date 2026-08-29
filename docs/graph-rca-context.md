# graph_rca — Context Window (graph_rca only)

> **Scope:** `src/main/graph_rca/` only (~5k LOC). Not agent_analysis, eval, or MCP catalog.
> **Branch (as of last review):** `feat/branch-aware-alignment`
> **Your role:** Design-led, AI-assisted build — you guided architecture and review; implementation was AI-assisted.

---

## 1. What it does

**Topology-driven root cause analysis** for application logs:

1. Parse logs → structured `LogEntry` list  
2. **Resolve** each line to a code-graph function (deterministic, no LLM)  
3. Build a **WalkablePath** (timeline + error points + ambiguous branches)  
4. Optional **flow alignment** (expected vs actual logs on error threads)  
5. **Decompose** → parallel **trace agents** (graph tools) → **router** → **lens judges** → **final judge**

**CLI:** `uv run cua-analyzer run --mode code-rca --repo ecmv4-g2 --config configs/ecmv4.yaml --log /path/to.log`

---

## 2. Architecture (one diagram)

```
Log file
  → preprocess (parse | chunked+dedup)
  → resolve (tiers 1–4)
  → WalkablePath
  → [optional] align: cluster → merge_flow → compare
  → short-circuit? (no errors | obvious stack trace)
  → decompose (LLM plan)
  → trace agents (parallel, graph tools)
  → route → lens judges → final judge
```

**Two worlds:**

| World | Source |
|-------|--------|
| **A — Runtime** | Parsed log entries, threads, stack traces |
| **B — Code index** | FalkorDB: `Function`, `Class`, `CALLS`, `LogTemplate`, `exec_flow` |

Align/merger uses **B**; compare uses **resolved A** (+ trie cache for per-function logs).

---

## 3. Package map

| Path | Role |
|------|------|
| `pipeline.py` | Orchestrator |
| `models.py` | `LogEntry`, `WalkablePath`, `FlowGraph`, `MergedFlow`, `LogStep`, … |
| `config.py` | `DomainConfig` from YAML |
| `preprocess/parser.py` | Entry grouping, ignore_patterns, fields |
| `preprocess/chunked.py` | Parallel chunks, known_errors, `_dedup_entries` |
| `preprocess/stack_trace.py` | Frame parsing |
| `resolve/resolver.py` | Tier 1–4 + `_infer_neighbours` |
| `resolve/trie.py` | `FragmentTrie` (cache or graph) |
| `resolve/class_resolver.py` | Logger class → function |
| `align/clusterer.py` | Thread → clusters at entry/anchor |
| `align/merger.py` | Branch-aware inline → `log_tree` + cache |
| `align/comparator.py` | Per-entry fid match + divergences |
| `index/flow_extractor.py` | Static CFG / log nodes from source (~483 LOC) |
| `index/flow_builder.py` | Write `exec_flow` to graph |
| `index/lite_index.py` | LogTemplate extraction |
| `index/cache.py` | `.flow_cache/{repo}/` commit-gated |
| `index/indexer.py` | Build index CLI path |
| `decompose.py` | LLM → `AgentAssignment[]` |
| `trace_agent.py` | Graph-walking agent |
| `judges.py` | Router, lenses, final verdict |
| `prompts/*.md` | System prompts |
| `lang_support/groovy.py` | ECM/Groovy indexing helpers |

**Config:** `configs/ecmv4.yaml`, `configs/flow_patterns/*.yaml`

**Artifacts:** `.flow_cache/{repo}/trie_data.json`, `merged/*.json`, `commit.txt`, `meta.json`

---

## 4. Preprocess

### Parse (`parser.py`)

- Groups lines into `LogEntry` (level, thread, message, stack trace).  
- `ignore_patterns` in YAML drop noise at parse time (Kafka, Hibernate, etc.).  
- Continuation lines + K8s prefix strip on stack continuations.

### Chunked path (`chunked.py`)

- Files **> 50MB** (pipeline) or explicit chunked API: parallel workers, merge, dedup.  
- `known_errors`: drops benign errors (chunk path checks `is_error`; small-file path filters all matching entries).

### Dedup (`_dedup_entries`)

- Signature: `level` + message skeleton (timestamps, numbers, quotes stripped).  
- **One copy per signature** → main reason 150k lines → ~3k entries on ECM test.  
- **Tradeoff:** loses frequency; repeated ERRORs collapse to one line.

---

## 5. Resolve (tiers)

### Tier 1 — Stack trace

- App frames only (framework filtered via YAML + hardcoded JDK/Groovy prefixes).  
- `originated_from[0]` = crash point; **`trace_path`** = first 2 + last 2 app frames.  
- Confidence ~0.95.

### Tier 2 — FragmentTrie (unique match)

- Templates from graph: static fragments around `{}` placeholders.  
- Trie keyed by `frags[0]`; verify remaining fragments in log text.  
- Loads **`FragmentTrie.from_cache(repo)` first**, else `from_graph`.  
- Sets `originated_from_ids`, `originated_line`, `originated_class`.

### Tier 3 — Ambiguous trie (multiple matches)

**Not** when trie fails — when trie returns **2+ functions** for same template.

1. Previous resolved function on **same thread** (`prev_by_thread`) — one line back, not ±3 cluster.  
2. For each candidate: **shortest CALLS path** prev → candidate (**max 6 hops**).  
3. Pick closest; may create `BranchPoint` if scores too close.

**Fixed bug:** `_score` uses `extract_method_name()` (short names) for FalkorDB queries.

**Not:** same class check, not align “cluster”, not 3 hops.

### Tier 3 — Logger class (trie returned 0)

- `extract_logger_class` from log line pattern → `find_by_class` (+ source fragment verify).  
- No graph hops.

### Tier 4 — Unresolved

- Marked tier 4; may flag `is_framework`.

### Second pass — `_infer_neighbours`

- Only tier 4 entries.  
- Looks ±3 neighbors on same thread that are resolved (tiers 1–3) — **gate only**.  
- Retries logger class lookup.  
- **Does not** run graph hops from anchors (name is misleading).

### Fields stored, underused downstream

- `trace_path`, `originated_class`, `originated_line` — agents mostly see function name + tier in `_build_log_context` (first 30 entries).

---

## 6. Align layer

### Clusterer

- Splits thread at functions whose `node_class` is `entry` or `anchor`.  
- Unmapped lines (`function: None`) attach to current/pending cluster.  
- **TODO:** all-unmapped pending → no cluster → dropped from align.

### Merger (branch-aware, ~280 LOC)

- DFS inline callees from anchor; builds:
  - **`log_tree`**: `LogStep` tree (`log` | `branch` | `loop` | `exit`)  
  - **`log_sequence`**: flat fallback (backward compat)  
- Disk cache: `.flow_cache/{repo}/merged/{func}.json`  
- `find_entry_for()`: walk up CALLED_BY to entry function  
- Respects branch edges (`branch_true`, `branch_false`, `exception`, …)

### Comparator (~130 LOC)

- Each entry matched against **its own `fid`** logs from `trie_data.json`.  
- Fallback: anchor’s flat `log_sequence`.  
- **`log_tree` is built but not walked for compare yet** (main WIP gap).  
- Coverage = matched entries / entries with function.

### Pipeline wiring

- Only **error threads** aligned.  
- Divergences fed to decomposer as `flow_context` string.

---

## 7. LLM layer

| Stage | Strength | Notes |
|-------|----------|-------|
| **Decompose** | Weakest | One-shot plan; optional flow divergences in prompt |
| **Trace agent** | Strong | Evidence, don’t stop at throw, verify callers |
| **Router + lenses + final** | Strong | `fault_classification`, `observability_alignment` |
| **Context limit** | Gap | ~30-entry log slice shared across agents; judges don’t see raw logs |

**Short-circuits:**

- No errors → exit  
- Obvious: all errors tier 1 + single root in `trace_path` / `originated_from` (uses filtered app frames)

---

## 8. Index & cache

1. **Lite index:** `LogTemplate` nodes + `EMITTED_BY` → `Function`  
2. **Flow index:** `exec_flow` JSON on `Function` (from `flow_extractor`)  
3. **Cache:** commit hash in `.flow_cache/{repo}/commit.txt`

Resolve: trie from cache if present.  
Compare: per-fid logs from `trie_data.json`.  
Merge: separate merged JSON cache.

---

## 9. ECM benchmark (typical test)

```
~150k lines (ecm.log)
  → parse + ignore  → many entries
  → dedup           → ~3369 signatures
  → resolve         → ~2836/3369 (~84%) in ~5s
```

Primary config: `configs/ecmv4.yaml` (Groovy/Grails, huge `ignore_patterns`, `known_errors`).

---

## 10. Interview pitch (graph_rca only)

**Lead with:**

1. Deterministic **resolve** (trie + graph hops) → high coverage without LLM  
2. **WalkablePath** as execution timeline grounded in code graph  
3. Parallel **unbiased trace agents** + multi-lens **judges**  
4. **Observability alignment** (did logs match what code should emit?)

**Skip unless asked:** merger branch trees, flow_extractor internals, comparator fid details.

**Honest line:** Align/compare is evolving; RCA value scales with index/template coverage (~84% on ECM deduped set is decent).

**Differentiators vs generic LLM RCA:** FalkorDB grounding, tool-using agents, repeatable resolve tiers, flow divergence signal for decompose.

---

## 11. Resolved vs open issues

### Fixed (on recent branches)

- `_score` short function names  
- `_is_obvious` uses `trace_path`  
- `_extract_app_frames` uses `config.language`  
- `known_errors` on small-file parse path  
- Dead monoliths removed (`preprocessor.py`, `flow_graph.py`, …)  
- Trie `from_cache` at resolve  
- Pipeline passes **`fid`** into align thread dict  
- All resolved entries should have fids (recent commit)

### Still open

| Issue | Detail |
|-------|--------|
| Compare vs `log_tree` | Merger builds tree; comparator doesn’t walk it |
| `_infer_neighbours` | No hop scoring from anchors |
| Dedup | All levels; ERROR frequency lost |
| Orphan unmapped clusters | clusterer TODO |
| `budget_cap_usd` | Not enforced |
| Test scripts | `test_flow.py` etc. may still import removed modules |
| Docs | wiki may reference old `preprocessor` |

### Planned (discussed)

- Branch-aware **compare** (walk `log_tree` vs actual log)  
- Dedup only non-ERROR levels  
- Wire `trace_path` / line into agent context  

---

## 12. Key types (cheat sheet)

```python
LogEntry          # one log record + resolution metadata
WalkablePath      # entries[], branches[], error_points[], coverage_pct
BranchPoint       # ambiguous trie: candidates + scores at entry_index
FragmentTrie      # static fragment prefix match
MergedFlow        # log_sequence (flat) + log_tree (LogStep[])
LogStep           # type: log | branch | loop | exit
AlignmentResult   # divergences[], coverage, matched_flow
AgentAssignment   # decompose output: starting_node, direction, model, path_slice
TraceReport       # agent output: path_walked, evidence, confidence
FinalVerdict      # root_cause, category, winning_lens
```

---

## 13. Commands

```bash
# Full RCA
uv run cua-analyzer run --mode code-rca \
  --log ~/Downloads/ecm.log \
  --repo ecmv4-g2 \
  --config configs/ecmv4.yaml \
  --verbose

# Index build (when stale)
# See README / indexer entry points — requires FalkorDB + repo path
```

---

## 14. Complexity (graph_rca only)

| Dimension | ~Rating |
|-----------|---------|
| LOC | ~5k — **medium** for one subsystem |
| Hardest modules | `flow_extractor`, `merger`, `pipeline` |
| Cognitive load | **6–7/10** — align/index WIP adds surface area |
| Explainable core | **resolve → path → agents → judges** stays clean |

---

*End of graph_rca context document. Paste into a new chat or save as a Cursor rule for graph_rca work.*
