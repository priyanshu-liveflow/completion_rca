# `agents/prompts/25-patch.md` — the patch procedure  ·  **Composer** (or fold into #15)

Small: one markdown file, no code. ~20 minutes.

## Working rules

**Wait until PR #15 (`feat/conductor`) is merged**, then:

```bash
cd ~/research-agents
git worktree add ~/research-agents-patchprompt -b feat/patch-prompt origin/main
cd ~/research-agents-patchprompt
```

`git branch --show-current` before every commit. Never touch `main`.

## What this is

PR #15 shipped `agents/prompts/{00-conductor,10-impact-analysis,20-repro,30-brief}.md`.
`25-patch.md` is the missing beat between reproduce and brief: the conductor
has a red run and must now write a fix. `agents/seed.ts` concatenates
`agents/prompts/*.md` **in filename order**, so `25-` lands between `20-` and
`30-` automatically. Add no other file.

Read all four existing prompts first and match their voice: second person,
imperative, procedure then a "the rule this file exists to state" section. Do
not restate what `20-repro.md` already says.

## Required content

**Procedure**

1. Read the failing traceback from the report `20-repro.md` produced — the
   actual traceback, not the summary line.
2. Read the source at each contact point (`read_function_source`), and fetch
   the dependency's migration guide with `scrape_page` if one exists. Bright
   Data is the only sanctioned way to fetch it.
3. Write a unified diff against the sandbox working tree.
4. Apply it with the sandbox's file/shell tools.
5. Re-run **exactly** the same selected tests. Same node ids as the baseline
   and the red run — a different set makes the comparison meaningless.
6. `save_verify` with before and after.

**Three rules this file must state plainly**

- **Never edit a test to make it pass.** `core/patch.py::validate_patch`
  rejects it, including a rename that moves a test file out of the way — but
  the conductor should never reach for it in the first place. An agent that
  "fixes" a failure by editing the test has defeated the entire product.
- **Stay inside the blast radius.** Only files the impact analysis identified.
  A patch touching anything else is rejected.
- **Patch one call site well rather than six badly** (cut item #3 in
  `docs/build-plan.md`). A minimal diff that provably flips red to green beats
  a broad refactor that flips nothing.

**On failure:** if the patch does not turn the run green, say so and stop. Do
not iterate silently, do not widen the diff, and do not report a fix that
isn't. `can_act` will block the PR anyway — the honest report is the product,
the fix is the upside.

**Worked example** — use the real demo numbers from `configs/demo.yaml`, and
quote them exactly:

```
before (mcp 1.29.1): 61 passed, 0 failed, 0 errors   -> green baseline
after  (mcp 2.1.1):   0 passed, 0 failed, 2 errors   -> broken (collection error)
patch: 4-line import rename
after patch (2.1.1): 61 passed, 0 failed, 0 errors   -> verified
```

Do not invent counts. `30-brief.md` was shipped with a fabricated "61 run, 2
failed" for this exact case and it had to be fixed — the red fixture is
`0/0/2`, because a collection error means no test ran. Zero failed and still
broken is the whole point.

## Acceptance

- `npx tsx agents/seed.ts` runs clean and the instructions still parse.
- Total instructions stay under the 6k-token budget. PR #15 measured ~3,281
  tokens at 13,122 chars; `seed.ts` prints the count on every run — check it.
- The file appears between `20-` and `30-` in the concatenated instructions.
