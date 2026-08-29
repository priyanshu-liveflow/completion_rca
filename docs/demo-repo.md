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
