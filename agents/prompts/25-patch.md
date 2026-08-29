# Patch — turn a red run into a proven fix

Goal: the reproduction step has already handed you a red report. Write the
smallest change that makes *those same tests* green on the new version, apply
it in the sandbox, and persist the before/after pair. This step is allowed
to produce a diff. It is not allowed to claim the diff worked.

Skip this whole file if reproduction never produced a red run. There is
nothing to patch. A green after-bump is a brief, not a fix.

## Procedure

1. **Read the traceback.** Take it from the report the reproduce step already
   saved — the actual traceback, not the summary line and not a paraphrase
   of it. A collection error's traceback is the whole signal; a one-line
   tally is not a substitute.
2. **Read the code, then the migration.** Call `read_function_source` at
   each contact point the impact table named. If the dependency published a
   migration guide or changelog for this version, fetch it with
   `scrape_page`. Bright Data (`web` MCP) is the only sanctioned way to fetch
   it — do not reach for any other HTTP client.
3. **Write a unified diff** against the sandbox working tree, aimed at the
   traceback you just read. One rename, one import, one call-site change —
   whatever the traceback actually says.
4. **Apply it** with the sandbox's own file and shell tools. The sandbox
   will apply whatever you give it — that is not the check.
5. **Re-run exactly the same selected tests.** Same node ids as the green
   baseline and the red after-bump run. A different set makes the comparison
   meaningless, and a "fix" proven against a different suite is not a fix.
6. **`save_verify`** with the red report as `before` and the post-patch report
   as `after`. The green baseline is *not* this `before`. `can_act` requires
   `before` broken and `after` green; handing it the baseline makes the gate
   refuse, correctly. `save_verify` re-parses the diff and runs
   `validate_patch` against the files on the impact table. A test edit or an
   out-of-radius file is refused there, so `can_act` never sees it. Only the
   diff headers count — omitting a path from the payload does not sneak it
   through.

## The rule this file exists to state

Three things `save_verify` will refuse by running `validate_patch` on the
diff itself. The conductor should never reach for them in the first place.

- **Never edit a test to make it pass.** That includes a rename that moves a
  test file out of the way. An agent that "fixes" a failure by editing the
  test has defeated the entire product. Change the production code the
  traceback points at, or stop.
- **Stay inside the blast radius.** Only files the impact analysis identified.
  A patch touching anything else is rejected. Do not "while you're there"
  tidy a neighbour, and do not expand the allowed set to fit a broader diff.
- **Patch one call site well rather than six badly.** A minimal diff that
  provably flips red to green beats a broad refactor that flips nothing. If
  four import sites share the same one-line rename and that is what the
  selected tests require, that is still one change. Six unrelated rewrites
  across files the graph did not name is not.

**On failure: say so and stop.** If the post-patch run is not green, report
that the patch did not verify, keep the diff attached as an attempt, and do
not iterate silently, do not widen the diff, and do not write "fixed" about
a run that is still red. `can_act` will block the PR anyway — the honest report
is the product, the fix is the upside.

## Worked example

Quote these counts exactly when this is the demo; they are the real
`TestReport`s, not a paraphrase. Do not invent replacements.

```
before (mcp 1.29.1): 61 passed, 0 failed, 0 errors   -> green baseline
after  (mcp 2.1.1):   0 passed, 0 failed, 2 errors   -> broken (collection error)
patch: 4-line import rename
after patch (2.1.1): 61 passed, 0 failed, 0 errors   -> verified
```

The red row is `0 passed, 0 failed, 2 errors`. Zero failed and still broken:
two modules never imported, so no test ran. The patch is a four-line import
rename, not a refactor. After it, the *same* two modules report 61 passed.
That red→green pair is what `save_verify` records and what `can_act` reads.
A "61 run, 2 failed" story would describe a run that never happened — do not
write it, here or in the brief.

## Output for this step

The unified diff (in full), the post-patch counts quoted from the report, and
a single word: `verified` or `failed`. If it failed, that word is the
verdict; the brief carries the gap forward. Do not leave a maybe.
