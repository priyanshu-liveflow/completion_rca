# Code review with Qodo

Required for the Best Code Quality track. The track is judged on **dealing with what it finds
before you merge** — not on having run the tool. A repo full of unaddressed Qodo comments scores
worse than one with fewer, resolved ones.

## Setup (one manual step)

Install the GitHub App on this repo: **https://github.com/apps/qodo-merge-pro**

The repo is public with 0 stars, so the free-for-open-source plan (100+ stars) doesn't apply. The
standard free tier gives 75 PR reviews/month, which is far more than this build needs.

Config lives in [`.pr_agent.toml`](../.pr_agent.toml) at the repo root, on the default branch.
Changes only take effect once merged to `main`.

## How we work

Trunk-based, small PRs, merged continuously. **Never one large PR at the end** — that is the single
most common way teams fail this track, because a big diff produces findings you have no time left
to fix.

1. Branch per slice of work. One concern per PR.
2. Open the PR. Qodo auto-runs `/describe`, `/review`, `/improve`.
3. Fix what it finds, or record why not (below).
4. Merge.

Useful manual commands, as PR comments:

| Command | Use |
|---|---|
| `/review` | re-run after pushing fixes |
| `/improve` | code suggestions only |
| `/ask <question>` | ask about the diff |
| `/describe` | regenerate the PR description |

## Project rules Qodo enforces

`.pr_agent.toml` carries `extra_instructions` encoding six architectural invariants. The important
one: **all outbound web access goes through Bright Data.** No linter can catch a stray `httpx.get`,
but a reviewer told the rule exists will. `repo_context_files` also points Qodo at `CLAUDE.md`, so
the rules we write for our own coding agent are the same rules our reviewer applies.

That is deliberate — one source of truth for project constraints, enforced at both authoring time
and review time.

## Declining a finding

Sometimes Qodo is wrong, or right but not worth it before a deadline. Both are fine. What is not
fine is silence — an ignored comment is indistinguishable from an unnoticed one.

Record it in [`decisions.md`](decisions.md) with the PR number, the finding, and the reasoning.
Judges reading that file see engineering judgment. Judges reading a wall of unresolved comments
see a team that ran a tool for the checkbox.
