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

### PR #12 — `reached_from` legibility versus the frozen contract
**Qodo said:** the IMPORTS walk stored contact-point *file paths* in `reached_from` while the CALLS walk stored *function names*, so a union mixed two identifier namespaces.
**We did:** fixed the inconsistency by moving IMPORTS onto function names, per `docs/build-plan.md:247` (`reached_from: list[str]  # contact point function names`). Also widened origin tracking from "first contact point to arrive" to the full set, since several contact points routinely share one module.
**Why:** worth recording that function names are the *less* legible choice here. For an import-shaped break the contact points are module-level import nodes, so the real graph reports `['<module>', 'register_tools', 'setup_api_client', 'start_server']` — the `<module>` entry says little on its own. File paths would read better in the UI, but the contract documents function names, PR9 persists this field, and one namespace that is consistent beats two that are not. Consumers that want the file already have `ContactPoint.file_path`.

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

### PR #7 — `ChatOpenAI` bypasses the Bright Data adapter
**Qodo said:** the provider makes an outbound HTTP request through
`ChatOpenAI.ainvoke()` outside `adapters/brightdata.py`, violating the rule that
all outbound HTTP goes through that adapter (compliance ID 2987720).

**We did:** declined.

**Why:** the rule exists to stop us fetching *web content* — release pages,
changelogs, migration guides — through anything but Bright Data. That is a data
provenance and anti-blocking concern, and it is the Bright Data track's whole
premise.

Model inference is not web content retrieval. Routing LLM calls through a
scraping proxy would break streaming and tool-calling, add a hop to every turn,
and mean nothing for provenance — we are not scraping the model, we are calling
a vendor API with our own credentials.

Applied literally the finding also forbids the GitHub API, Daytona's SDK, and
the FalkorDB connection, which is not what anyone intends by "all web access
goes through Bright Data".

**Consequence:** `CLAUDE.md` states the rule too absolutely, which is why a
reviewer reading it in good faith reached this conclusion. The rule is about
retrieving web content, and vendor SDKs called with our own credentials are out
of scope. Worth tightening the wording rather than re-arguing this per PR.
`scripts/check_layering.py` already encodes the intent correctly — it bans HTTP
*clients*, not vendor SDKs — and it passes on this PR.

