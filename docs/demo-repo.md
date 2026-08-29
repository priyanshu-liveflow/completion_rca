# Demo target: `intervals-mcp-server` × MCP SDK v1 → v2

Chosen at H0 and verified by hand before any code was written. Machine-readable
form lives in `configs/demo.yaml`; this file records *why* and *what was proven*.

## The repo

[`mvilanova/intervals-mcp-server`](https://github.com/mvilanova/intervals-mcp-server)
at `cb1fbcac81095cf3e094e995decf04b8b1f259f8`.

| Criterion | Result |
|---|---|
| Python, public | yes, GPL-3.0 |
| Indexes fast | 20 source files, ~1400 LOC |
| Runtime deps | three: `mcp[cli]`, `httpx`, `python-dotenv` |
| **Test suite currently passes** | **61 tests, 0.50s, no credentials, no network** |
| Real recent breaking change | MCP Python SDK v1 → v2 |

The repo already pins `mcp[cli]>=1.4.0,<2.0.0`. It capped itself below the
breaking release, which is the exact situation the product addresses: the pin
is a deferral, not an answer, and nobody knows what lifting it costs.

## The break

MCP Python SDK v2 renamed `FastMCP` to `MCPServer` and removed the
`mcp.server.fastmcp` module. Four files import it.

```
ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x,
where FastMCP was renamed to MCPServer (from mcp.server.mcpserver import
MCPServer) and other APIs changed; see the migration guide at
https://py.sdk.modelcontextprotocol.io/v2/migration/ or pin 'mcp<2' to keep
running v1 code.
```

Three properties make this demo well, and they were the selection criteria:

1. **The failure lands in the repo's own code**, not deep in site-packages. The
   traceback names `src/intervals_mcp_server/api/client.py:17`. There is
   something to point at and something to patch.
2. **The symbol appears in source text**, so `find_by_pattern("FastMCP")` finds
   every contact point without needing a resolved import graph.
3. **The patch is four identical one-line changes.** A model gets this right on
   the first pass, on stage, under time pressure.

`mcp_instance.py` is imported by every tool module, so `get_callers` from the
contact point fans out to a genuine blast radius rather than a single leaf.

## What was proven by hand

Run in a throwaway venv, before committing to the repo:

| Step | Command | Result |
|---|---|---|
| Baseline green | `pytest -q` at `mcp 1.29.1` | **61 passed in 0.50s** |
| Bump | `uv pip install "mcp[cli]>=2.0.0"` | resolves `mcp 2.1.1` |
| Red | `pytest -q` | **2 collection errors, exit 2** |
| Patch | rename the import in 4 files | — |
| Green | `pytest -q` | **61 passed** |

Captured as `fixtures/pytest_output_green.txt` and `pytest_output_red.txt`.
These are what `core/testreport.py` parses against in CI, so the parser is
tested on real output rather than invented output.

**Verification item 7 (*"repro is honest"*) is satisfied by construction:**
reverting the bump returns the suite to green, so the failure is attributable
to the version change and nothing else.

## The one wrinkle — read this before writing the parser

The red case is a **collection error, not a test failure.** Both test modules
fail at import, so pytest reports:

```
ERROR tests/test_make_intervals_request.py
ERROR tests/test_server.py
!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!
```

There are **zero per-test node ids** in that output, because nothing ran.

A parser that only scans for `FAILED` lines will read this as a green run. That
turns the product into a liar at the single most important moment of the demo —
it would report "no impact" on a repo that cannot even import. `parse_pytest`
must treat a non-zero collection-error count as failure, and
`fixtures/pytest_output_red.txt` must be a test case in PR5.

The demo line changes accordingly, and lands harder:

> *"Four call sites. I ran the tests that reach them — the module doesn't even
> import under the new version."*

## Alternatives considered

**Pandas 3.0** (Jan 2026) — hundreds of removals, but copy-on-write is a
*behavioural* break. No traceback, subtle patches, and a large install. Wrong
shape for a three-minute demo.

**NumPy 2.0** — clean `AttributeError`s and trivial renames, but it is 2024. The
WATCH story wants a release the scouts can plausibly have just found.

MCP SDK v2 also carries a narrative advantage at *this* hackathon: every MCP
server on GitHub is on v1, and some of the judges maintain one.

## Graph verification — run at H0, not deferred to H2

Indexed with `cgc index intervals-mcp-server` (FalkorDB Lite, `cgc doctor` all green).

```
Total scanned files    38
Function nodes         210
Class nodes            15
CALLS edges            749
IMPORTS edges          114
Index time             2.28 seconds
```

`IGNORE_TEST_FILES=false`, so test functions are indexed — 109 nodes under `tests/`.

### Contact points

`f.source CONTAINS 'FastMCP'` returns **7 nodes**: four `<module>` nodes, one per
importing file, plus `setup_api_client`, `start_server`, and `register_tools`.
This is the `find_by_pattern` path — it matches source text, which is why an
import-only symbol is findable at all.

### The finding that changed PR4

Two selection strategies were run against the real graph.

**`CALLS` reaches zero.** Not a broken mechanism: 56 of 61 tests do reach source
functions through `CALLS`, and the tests call `format_*` helpers exactly as you
would hope. But nothing *calls* an import statement, so a recursive caller walk
from these contact points reaches nothing. For a signature change it would work;
for this break it cannot.

**`IMPORTS` reaches exactly the right two.**

| Test module | Imports | Selected |
|---|---|---|
| `test_server.py` | `intervals_mcp_server.tools` | **yes** — exact match |
| `test_make_intervals_request.py` | `intervals_mcp_server.api` | **yes** — dot-boundary prefix of `...api.client` |
| `test_formatting.py` | `utils.formatting` | no |
| `test_validation.py` | `utils.validation` | no |
| `test_value.py` | `utils.types` | no |

Those two are precisely the modules that error under `mcp 2.x`. Zero false
positives, zero misses.

**Both strategies ship, unioned.** Import breaks need `IMPORTS`; signature
changes need `CALLS`. A real dependency release produces both.

### The catch to implement around

`IMPORTS` edges run **file → module-name string**, and module-name nodes are
leaves. `test_server.py -IMPORTS-> "intervals_mcp_server.server"` does not
connect to the `server.py` file node, so a transitive Cypher walk dies after one
hop. The name-to-file join happens in `core/selection.py`, in pure code.

Prefix matching must respect dot boundaries: `intervals_mcp_server.api` matches
`intervals_mcp_server.api.client`, but `intervals_mcp_server.apiclient` must not.
Naive equality misses `test_make_intervals_request.py` entirely — half the
selection.

### What this buys the demo

> *"Five test modules. The graph selected two. Both went red. The other three
> were never at risk."*

Precision is the claim, not recall. Selecting all five would have run tests that
could not fail and made the impact table meaningless.

## Sandbox verification — run at H0 in a real Daytona sandbox

`sandbox/timing_probe.py` against the default Daytona image (Debian 13,
Python 3.14, ships `git`, `pip`, `uv`). Default image only — TrueForge's Daytona
provider config exposes no image field, so measuring a custom one would measure
a path we cannot take.

```
COLD PATH — what a judge sees if the prewarmed session died
     0.32s  create sandbox                     ok
     0.86s  clone at pinned commit             ok
     6.48s  install baseline deps              ok
     2.44s  baseline tests (expect GREEN)      ok

LIVE PATH — what runs on stage
     0.94s  bump to breaking version           ok
     2.46s  tests (expect RED)                 exit 2
     0.12s  apply patch                        ok
     2.61s  tests (expect GREEN)               ok

  COLD (prewarm, off-stage)     10.1s
  LIVE (on stage)                6.1s
```

**Red → green proven in the real execution environment before a line of
product code existed.**

### What this closes

Sandbox latency was the risk this plan was most organised around. Two full
revisions argued about local Docker versus Daytona on the assumption that
cold-cloning on stage would be minutes. It is **ten seconds**, and sandbox
creation alone is 0.15–0.7s because Daytona is snapshot-backed rather than
booting a VM.

Consequences:

- **`sandbox/Dockerfile` is cut.** A cold Daytona cycle is faster than
  rebuilding a local image, so Docker earns nothing even as a rehearsal path —
  and it removes a file that had to stay in sync with the indexed commit.
- **Prewarming is an optimisation, not a dependency.** We still do it: 6s on
  stage beats 16s, and a warm session shows its own history in the timeline.
  But a session that dies between rehearsal and the slot costs ten seconds, not
  the demo.
- **The `auto_stop` / `auto_archive` worry is defanged.** Still set them
  explicitly; `--idle-minutes N` tests survival directly. It is no longer the
  highest-risk item on the board.

### The lesson worth keeping

Three of this plan's largest risks — no usable demo repo, callers not reaching
tests, sandbox too slow — were closed at H0 by measuring rather than
mitigating. Each measurement took minutes and each replaced a paragraph of
hedging with a number. The one remaining unmeasured dependency on the demo path
is TrueForge itself.
