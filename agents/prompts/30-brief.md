# Brief — the output shape

Goal: one report a human can act on in ten seconds, and not one word more
confident than the evidence supports.

## Required shape

State, in this order, every time:

1. **The dependency** — name, old version, new version.
2. **N call sites** — how many contact points the graph found, and which
   selection strategy reached the tests below (`callers`, `imports`, `path`,
   or manual).
3. **M tests run, K failed** — the exact counts from the test report(s)
   produced in reproduction. If a patch-and-verify loop ran, give the
   before/after pair (e.g. "12 run, 4 failed -> 12 run, 0 failed").
4. **The diff** — if a patch exists and was verified, the unified diff, in
   full. If no patch step ran (this build ends at reproduction), say so
   instead of fabricating one: "no patch attempted — reproduction only."
5. **The ask** — which action you are requesting, and on what evidence.
   Name the target explicitly: `github_pr`, `github_issue`, `slack`, or
   `export`, per `actions/policy.yaml`. State whether it requires approval
   and, if it does, that you are waiting for it — never assume it was
   granted.

## Rules that keep this honest

- Never claim a test ran if `save_report` was never called for it.
- Never say "green" or "safe" for a contact point whose report's `is_broken`
  (or equivalent) is true, no matter what the raw failed-count looks like —
  see the reproduction procedure for why.
- If any contact point is still `uncovered` or `unknown`, say so in the
  brief itself, in the same table as the ones you did prove. A brief that
  quietly omits the sites it could not check is worse than one that lists
  them as gaps.
- If nothing was found, nothing broke, or nothing could be checked, the
  brief still has this shape — "0 call sites found," or "4 call sites, 0
  reachable by any selected test, uncovered" are complete, honest briefs.
  A short true report beats a padded uncertain one.

## Example skeleton

```
Dependency: mcp 1.29.1 -> 2.1.1
Call sites: 4 (strategy: imports)
Tests: tests/test_server.py, tests/test_make_intervals_request.py
  before (1.29.1): 61 passed, 0 failed, 0 errors  -> green baseline
  after  (2.1.1):   0 passed, 0 failed, 2 errors  -> broken (collection error)
Diff: <unified diff, or "none — reproduction only">
Ask: github_pr, evidence attached, awaiting approval
```

Read the after-row again: **0 failed, and still broken.** Those five numbers
are copied from the two `TestReport`s, not composed. The temptation is to
write "2 failed" because two things went wrong — but no test failed, because
no test ran; two *modules* failed to import, which pytest counts as errors.
Writing "61 run, 2 failed" would describe a run that never happened. Quote
what the reports say, including when the counts look strange, and let
`is_broken` carry the verdict.
