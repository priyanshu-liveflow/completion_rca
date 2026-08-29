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

### PR #18 — `gh pr create` does not apply the verified patch onto a new branch
**Qodo said:** `github_pr` takes a caller-supplied `branch` (and used to take a separate `diff`), so a verified patch A can still open a PR from unrelated commits already on branch B.
**We did:** partially addressed. The embedded diff is now always `mission.verify.patch.diff`; a payload diff that disagrees is a closed gate, and the MCP tool no longer accepts a caller `diff` or `VerifyResult` dump. We did not make `GhClient` `git apply` / commit / push.
**Why:** `CodeHost.open_pr(branch, title, body, diff)` is the PR12 contract — `gh pr create --head` submits an already-pushed branch. Applying the patch in the adapter would mutate the harness checkout, and secrets must not enter the sandbox to push from there. The human approval pause is the remaining check that `--head` is the branch that actually carries the repair. Binding the write to a commit minted from the patch is follow-up work, not a silent extra git write in this PR.

### PR #18 — sandbox-signed verification ids versus store-backed reports
**Qodo said:** recomputing `verified` from caller-authored `TestReport` counts does not prove the tests ran; bind the write to an immutable run id produced by the sandbox.
**We did:** partially addressed. `github_pr` now takes `mission_id` and reads `mission.verify` from the store — a fabricated dict on the tool call cannot open the gate. We did not add a signed run id to the frozen contracts.
**Why:** `save_verify` already persists a `VerifyResult` whose `verified` field is computed, and `save_report` already parses pytest stdout rather than trusting a `failed=` integer. A cryptographic run id would reopen `contracts/patch.py` and `contracts/evidence.py`, which later PRs have been treating as frozen. The remaining hole (an agent posting invented pytest stdout through `save_report`) is the same one the rest of the pipeline lives with; closing it belongs with a sandbox-emitted artifact, not a GitHub-adapter special case.

### PR #12 — `reached_from` legibility versus the frozen contract
**Qodo said:** the IMPORTS walk stored contact-point *file paths* in `reached_from` while the CALLS walk stored *function names*, so a union mixed two identifier namespaces.
**We did:** fixed the inconsistency by moving IMPORTS onto function names, per `docs/build-plan.md:247` (`reached_from: list[str]  # contact point function names`). Also widened origin tracking from "first contact point to arrive" to the full set, since several contact points routinely share one module.
**Why:** worth recording that function names are the *less* legible choice here. For an import-shaped break the contact points are module-level import nodes, so the real graph reports `['<module>', 'register_tools', 'setup_api_client', 'start_server']` — the `<module>` entry says little on its own. File paths would read better in the UI, but the contract documents function names, PR9 persists this field, and one namespace that is consistent beats two that are not. Consumers that want the file already have `ContactPoint.file_path`.
### PR #11 — collector manifests are absent from a built wheel
**Qodo said:** `COLLECTOR_DIR` resolves beside the installed package, but `[tool.hatch.build.targets.wheel] packages = ["src"]` ships only `src`, so in a wheel install every `run_collector` lookup returns `unknown_collector` while source-checkout tests pass.
**We did:** declined for this phase.
**Why:** the finding is technically correct — nothing ships `collectors/`. But nothing installs a wheel either: all four MCP servers run as `python -m src.main.agentradar.mcp.*`, CI runs from a checkout, and `uv run` installs the project editable so `__file__` resolves to the repo root. Adding `collectors/` to the wheel would place it at the wheel root, which `parents[4]` still would not find — the honest fix is relocating the manifests to package data under `src/main/agentradar/`, and that is a packaging change this PR should not carry. Revisit if anything ever installs this non-editable.

### PR #11 — `health_after_heal` is not set on every run
**Qodo said:** the healthy and refused-heal paths leave `health_after_heal` unset, violating a requirement that every run record both health fields.
**We did:** declined.
**Why:** `CollectorRun.health_after_heal` is `HealthVerdict | None = None` in the frozen contract, and `None` is the correct value: no heal ran, so there is no "after". Populating it by copying `health` would assert a heal happened and produce a run that claims before/after parity it never measured. The demo beat is *degraded then repaired* — a run that was healthy the first time must be distinguishable from one that was healed into health, and the null is what distinguishes them.

### PR #11 — a failed heal raises instead of returning the degradation report
**Qodo said:** after degradation is detected, a `BdataError` from heal raises `ToolError` rather than returning a structured report carrying id, url, symptom, heal status and heal error.
**We did:** partially addressed — the raised error now names the collector id, its url and the verbatim symptom, so nothing is lost. Still raises.
**Why:** `CollectorRun` has no field for *why* a heal failed, so returning one would make a crashed `bdata` indistinguishable from a heal that was cleanly refused — and refusal already returns a report with `healed=False`. Collapsing a dead CLI into that same shape is the silent-degradation failure the Bright Data rule exists to prevent. Adding a `heal_error` field to the frozen contract is the real fix, and it belongs with whichever PR next needs to reopen `collector.py`.

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


---

## PR #15 — `agents/seed.ts` lives outside `src/main/agentradar` — **declined**

**Finding:** *"Agentradar tooling outside allowed directories."* `CLAUDE.md`
says to scope new tooling to `src/main/agentradar` and `tests/agentradar`;
the conductor seeding tool sits in `agents/` instead.

**Declined.** `agents/` is not tooling in the sense that rule governs. It holds
TrueForge's declarative artifacts — a JSON agent manifest, four prompt markdown
files, and the TypeScript SDK script that uploads them. `src/main/agentradar`
is a Python package tree: `scripts/check_layering.py` walks it as Python AST,
`mypy --strict` types it, and the four spine rules (`contracts`/`core`/
`adapters`/`mcp`) describe Python import layering. A `.ts` file and its
`package.json`/`package-lock.json` would be invisible to every one of those
checks while sitting inside the subtree they exist to guard — the rule's intent
is inverted, not served, by moving it there.

The build plan (`docs/build-plan.md`, PR10) specifies these exact paths and
states "Language: Python everywhere, except `agents/seed.ts`," because the
TrueForge SDK is TypeScript and nothing else in the build is.

**Consequence:** same root cause as the PR #7 entry — `CLAUDE.md` states a rule
about the *Python* package layout without saying so, so a reviewer reading it
literally applies it to every new file. Worth one clarifying clause in
`CLAUDE.md` rather than re-arguing per PR.
