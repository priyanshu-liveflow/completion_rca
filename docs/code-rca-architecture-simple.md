# Code-RCA: How It Works

## The Problem

You have an application log full of errors. You want to know **why** it's failing — not just what failed, but the root cause in the actual source code.

## The Idea

Think of it like a team of debuggers:
1. One person reads the log and figures out which code files are involved
2. A lead assigns different people to investigate different parts
3. Each person opens the codebase, traces the call chain, reads the source
4. They come back with findings
5. A panel reviews all findings and decides the root cause

That's exactly what this system does — but with AI agents instead of people, and a code graph instead of an IDE.

## The Two Layers

```
┌─────────────────────────────────────────────┐
│           CODE GRAPH (FalkorDB)             │
│                                             │
│  Classes ──CONTAINS──> Functions            │
│  Functions ──CALLS──> Functions             │
│  Classes ──INHERITS──> Classes              │
│  Classes ──INJECTS──> Classes (DI)          │
│                                             │
│  Every node has: name, path, source code    │
└─────────────────────────────────────────────┘
         ▲
         │ agents query this
         │
┌─────────────────────────────────────────────┐
│           RCA PIPELINE                       │
│                                             │
│  LOG → PREPROCESS → DECOMPOSE → TRACE      │
│                      → ROUTE → JUDGE → VERDICT │
└─────────────────────────────────────────────┘
```

**Layer 1: Code Graph** — Your codebase indexed into a graph database. Functions, classes, who-calls-who, inheritance, dependency injection. Built once, queried many times.

**Layer 2: RCA Pipeline** — Takes a log file, maps it to the graph, spins up AI agents to investigate, then judges their findings.

## The Pipeline (6 Steps)

### Step 1: PREPROCESS
**Input:** Raw log file
**Output:** "Walkable path" — a sequence of log entries mapped to actual functions in the code graph

The preprocessor reads each log line and figures out which function in your codebase produced it. Stack traces are easy (direct match). Log messages are matched against the graph using the static text portion.

```
Log line: "ERROR JwtTokenProvider - signature key cannot be null"
    → maps to: JwtTokenProvider.getUsername() in the code graph
```

### Step 2: DECOMPOSE
**Input:** The walkable path + error summary
**Output:** 3-5 agent assignments

An LLM looks at the error pattern and decides how to split the investigation. Each agent gets:
- A starting node in the code graph
- A scope (what to investigate)
- A direction (trace callers? callees? both?)
- A path slice (the specific execution path segment to walk)

```
Agent 1: "Investigate how the JWT signing key is configured"
         Start: JwtTokenProvider, Direction: both
Agent 2: "Trace how getLoggedInUser handles auth failures"  
         Start: TemplateUtil.getLoggedInUser, Direction: backward
```

### Step 3: TRACE (parallel)
**Input:** Agent assignments
**Output:** Investigation reports with findings

Each agent runs independently with tools to query the code graph:
- `read_function_source` — read the actual code of a function
- `get_callers` — who calls this function?
- `get_callees` — what does this function call?
- `get_class_info` — class fields, annotations, methods
- `get_call_chain` — shortest path between two functions
- `find_function_by_pattern` — search by name pattern

Agents do multi-turn investigation (up to 8 tool calls), walking the graph hop by hop, reading source code, forming hypotheses.

### Step 4: ROUTE
**Input:** All trace reports
**Output:** 3-4 evaluation "lenses"

A router LLM reads all findings and decides what angles to evaluate from. Examples:
- "auth_flow_integrity" — is the authentication chain correct?
- "config_dependency" — are all required configs present?
- "fault_classification" — is this actually a code bug or a config/infra issue?

### Step 5: JUDGE (parallel)
**Input:** All trace reports + assigned lens
**Output:** Verdict per lens

Each lens judge evaluates the evidence from a specific angle. They can conclude "no code defect found" — that's a valid answer.

### Step 6: FINAL JUDGE
**Input:** All lens verdicts
**Output:** Root cause verdict with confidence score

A meta-judge synthesizes everything into a final answer: what's the root cause, how confident are we, what's the evidence.

## The Code Graph

Built using `codegraphcontext` (tree-sitter based indexer). Supports:
- Java, Groovy, Python, Go, Rust, C++, TypeScript, and more
- Stored in FalkorDB (Redis-compatible graph database)
- Queried via Cypher

What gets indexed per function:
- Name, file path, line number
- Full source code
- Who it calls (CALLS edges)
- Who calls it (reverse CALLS)
- What class it belongs to (CONTAINS)
- Class inheritance (INHERITS)
- Dependency injection (INJECTS)

## Why a Graph?

Logs tell you WHAT failed. The graph tells you WHY by letting agents:
1. Follow the call chain backward from the error
2. Check if error handling exists at each hop
3. Read the actual implementation
4. Find missing configuration or validation
5. Detect circular dependencies or missing DI

Without the graph, an LLM would have to guess about code structure. With it, agents can verify every claim against real source code.

## Cost & Performance

- ~$0.50-0.80 per analysis (with prompt caching)
- 5 parallel agents, 8 turns each
- ~40-60K input tokens total
- 60%+ cache hit rate on repeated analyses
- End-to-end: ~2 minutes

## Supported Languages

Any language with a tree-sitter grammar. Currently tested:
- Java (full support via codegraphcontext)
- Groovy (custom parser we built on murtaza64/tree-sitter-groovy)
- Python, Go, Rust, C++, TypeScript, Kotlin, Scala, etc.

## Quick Start

```bash
# 1. Index your repo
codegraphcontext index /path/to/your/repo

# 2. Run analysis
uv run cua-analyzer run \
  --log /path/to/error.log \
  --mode code-rca \
  --repo /path/to/your/repo \
  --verbose
```
