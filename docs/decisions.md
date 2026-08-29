# Decisions

Findings we consciously declined, and why. One entry per decision, newest first.

An empty section here is fine. An unresolved Qodo comment with no entry here is not — see
[qodo.md](qodo.md).

## Format

```
### PR #<n> — <one-line finding>
**Qodo said:** what it flagged, briefly.
**We did:** declined / deferred / partially addressed.
**Why:** the actual reasoning. "No time" is a legitimate answer if it is the true one.
```

---

### PR #4 — timing probe labels every exec failure as auto-stop
**Qodo said:** The idle probe caught all exceptions from `process.exec` and reported auto-stop recovery even for unrelated API or network failures.
**We did:** declined — reverted the auto-stop recovery block in `886ae57` (`182df98`). The probe now only checks whether `true` still runs after the idle gap.
**Why:** Recovery semantics need a specific stopped-sandbox signal from the Daytona SDK, not a broad `except Exception`. Until that exists, overstating auto-stop is worse than reporting a simple alive/dead check.

### PR #4 — MCP handlers returned bare lists instead of contract models
**Qodo said:** Graph MCP tools returned raw `list[ContactPoint]`, `list[dict]`, and `str` instead of designated response models.
**We did:** added `ContactPointList`, `GraphNodeList`, and `FunctionSource`; handlers now return those models.

### PR #4 — tool failures surfaced as MCP successes
**Qodo said:** Error envelopes from `dispatch` were returned with `isError=false`.
**We did:** `format_tool_result` sets `isError=true` when the payload contains `error`.

### PR #4 — invalid numeric MCP inputs accepted
**Qodo said:** Booleans were accepted as integers and bounds were not enforced.
**We did:** reject non-strict ints (`type(value) is int`) and enforce JSON Schema `minimum` / `maximum` on tool fields.

### PR #4 — synchronous graph I/O blocked the event loop
**Qodo said:** `dispatch` ran synchronously inside the async MCP handler.
**We did:** wrap `dispatch` in `asyncio.to_thread`.

### PR #4 — source-only contact points omitted when a name match exists
**Qodo said:** `find_by_pattern` skipped source search when any name row matched.
**We did:** union name and source hits with fid deduplication up to `limit`.

<!-- entries go here -->
