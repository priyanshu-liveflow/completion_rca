# Publication cleanup verification

Checked on 2026-10-13. These results concern this cleanup branch, not a fresh certification of every historical demo claim.

## Passed

| Check | Result |
| --- | --- |
| Backend tests, existing environment | 443 passed, 3 live-graph tests skipped |
| Backend tests, freshly installed CI dependencies | 443 passed, 3 live-graph tests skipped |
| Ruff lint and format | Passed |
| Layering check | Passed |
| Strict mypy, fresh cache | Passed for 42 AgentRadar source files; inherited modules outside strict scope |
| Exported JSON schemas | Match the models |
| Frontend ESLint | Passed |
| Frontend unit tests | 94 passed across 10 files |
| Next.js production build | Passed on Next.js 16.4.0 |
| Chromium browser E2E | 5 passed against the production server |
| Minimal browser-CI Python runtime | Real local repair: 2 failures → 2 passes |
| Production npm audit | 0 reported vulnerabilities |
| Local links in the current guides | Resolved |

The browser suite covers replay gate ordering, confirmation and denial, sandbox controls/pop-out, a simulated service failure, and a real local repair followed by persistence and reload. It caught the fresh-install `/reviews` bug: the empty-history branch hid the controls needed to create the first run. The fixed version passes that same test.

The real local repair uses a temporary billing package, a manually selected test module, and a fixed patch. It exercises Python, Git, pytest, the HTTP stream, storage, and the browser; it does not exercise dependency release discovery or model-generated patching.

## Real Daytona dependency experiment

The existing `sandbox/timing_probe.py` was run with the configured Daytona account and the pinned external demo repository. It observed baseline exit 0, upgraded the dependency, observed exit 2, applied the probe's known patch, and observed exit 0 again. The temporary sandbox was deleted by the probe.

Measured setup was 10.3 seconds and the upgrade/red/patch/green path was 5.7 seconds. These are observations from one run, not latency guarantees. The probe runs tests directly and applies a known patch; it does not test the conductor's discovery or patch generation.

## Not verified end to end

The complete release-discovery → graph → agent-authored repair → approved GitHub PR path was **not** revalidated in this cleanup session:

- Bright Data returned an empty active-zone list, and the configured `c_mcp_releases` collector returned HTTP 404, `Collector not found`.
- The local indexer fell back to KùzuDB. AgentRadar requires the FalkorDB socket, and a separate Lite worker attempt failed to start its Redis server. The three live graph tests remained skipped.
- The existing TrueForge harness started and reported a ready Daytona provider and configured conductor/model, but readiness alone is not a successful mission.
- No dependency-repair PR was opened against the external demo repository during testing. The publication-cleanup PR is a separate code-review action.

To close these gaps, configure working release collectors/zones, restore a compatible FalkorDB Lite runtime, and rerun the [connected E2E checklist](testing.md#connected-dependency-e2e).

## Remaining audit findings

Five high-severity npm audit entries remain in the **development-only** ESLint chain (`braces` → `micromatch` → `fast-glob` → Next.js ESLint tooling). npm proposes an incompatible downgrade to Next.js 14 tooling; that downgrade was not applied. No production dependency advisories remain in the audit performed here.

A pattern scan of tracked text found no matches for private-key blocks or the checked GitHub/provider token formats. This is a limited content check, not a full-history secret audit or a security certification. Host-specific paths were removed from the published pytest fixtures without changing their outcomes.
