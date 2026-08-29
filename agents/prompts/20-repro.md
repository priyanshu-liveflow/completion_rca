# Reproduce — turn a hypothesis into evidence

Goal: convert every `unknown` row from impact analysis into `broken`, `safe`,
or `uncovered`, each backed by a real test run. This is the only step allowed
to write those words.

## Procedure

1. **Baseline first.** With the dependency still at the *original* version,
   run exactly the tests the impact-analysis step selected and call
   `save_report` on that output. This run must come back green.
2. If the baseline is **not** green, stop. Those tests were already failing
   before the release existed, so nothing you observe after the bump can be
   attributed to it. Report that the baseline is red, name the failures, and
   mark the contact points `unknown` — never `broken`. A reproduction with
   no green baseline proves nothing, and claiming a release broke something
   it did not is the worst output this system can produce.
3. Only once the baseline is green, bump the dependency to the new version.
4. Run the same selected tests again — not the whole suite, and not a
   superset. Precision is the point: a test that never touches a contact
   point proves nothing about it either way. The comparison is only valid
   because both runs executed the *same* node ids.
5. Read the raw output, not just a summary line. Pytest's own final tally can
   look clean while the run underneath it was not.
6. Call `save_report` with the raw output so it is parsed once, centrally,
   the same way every time — do not hand-summarize a pass/fail count
   yourself from the terminal text.
7. Classify each contact point by **comparing the two reports**, never from
   the after-report alone. A contact point is `broken` only when its tests
   were green at the original version and are not at the new one:
   - A contact point reached by a test that failed or errored -> `broken`.
   - A contact point reached only by tests that passed -> `safe`.
   - A contact point **no selected test reaches** -> `uncovered`. Do not
     guess at its status. Fall back to an import check (or whatever
     lightweight existence check the sandbox tools offer) and report exactly
     that — "no test covers this; import check only" — rather than assigning
     `safe` or `broken` on vibes.
8. Persist each verdict with `save_impact`, and call `save_verify` if this
   step is followed by a patch-and-verify loop.

## The rule this file exists to state

**Trust the report's own judgment about whether the run was broken, never a
raw failed-test count.** A run can produce zero failures and zero passes and
still mean the code is broken — a collection error, where a module fails to
import, ends the run before a single test executes. `passed == 0, failed ==
0` is not "nothing to report," it is the loudest possible signal that
something is wrong. If the report exposes an `is_broken` field (or
equivalent), use it as the source of truth over any count you might compute
by hand. **"No failures" does not mean safe.** A parser or a summary line
that only looks for `FAILED` would call a collection error green — do not
make that mistake by re-deriving the verdict yourself from partial output.

**A red baseline is not evidence, it is a disqualification.** The one thing
that makes this whole system more than a guess is that it ran the same tests
twice and only one of the runs was red. Skip the before-run and every
`broken` verdict downstream is unfalsifiable — it is exactly the claim a
model would make if it had never opened a terminal.

If the sandbox or the test-running tool is unavailable, do not run this step
by imagination. Say plainly that reproduction could not be attempted, mark
the affected contact points `unknown` still (not `safe`), and let the brief
carry that gap forward honestly.

## Output for this step

An updated impact table: every row now `broken`, `safe`, or `uncovered`
(never left at `unknown` unless reproduction genuinely could not run), the
raw traceback or import-check output that justifies each `broken` or
`uncovered` call, and the counts (`M` tests run, `K` failed) that the brief
will quote verbatim.
