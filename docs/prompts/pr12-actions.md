# PR12 — `feat(actions): github + approval policy`  ·  **Grok 4.6 (high)**

## Working rules

Create your **own git worktree**. Do not work in `~/research-agents`:

```bash
cd ~/research-agents
git worktree add ~/research-agents-pr12 -b feat/actions origin/main
cd ~/research-agents-pr12
```

Run `git branch --show-current` before **every** commit and confirm it says
`feat/actions`. Never force-push. Never touch `main`. Open a PR when done.

Read `CLAUDE.md` and `docs/build-plan.md` (section PR12) first. The spine —
`contracts/` → `core/` → `adapters/` → `mcp/` — is a review blocker, not a
suggestion.

## What this PR is

The last mile: turning a proven repair into a pull request a human approved.
Everything before it produced evidence. This produces a *write*, and writes
are the only irreversible thing this system does.

Two halves, and they must not blur together:

- `core/policy.py` — pure. Reads `actions/policy.yaml`, decides what needs
  approval. No I/O.
- `adapters/github.py` — the only place a `gh` subprocess exists.

## Files

```
src/main/agentradar/core/policy.py       NEW
src/main/agentradar/adapters/github.py   NEW
tests/agentradar/test_policy.py          NEW
tests/agentradar/test_github_adapter.py  NEW
```

Do **not** create or edit `actions/policy.yaml` — it exists on `feat/conductor`
(PR #15) and that PR owns it. Read it for its shape; your loader must parse the
file as it stands.

## `core/policy.py`

```python
def load_policy(text: str) -> dict[str, bool]:
    """YAML text -> {target_name: requires_approval}."""

def approval_tool_list(policy: dict[str, bool]) -> list[str]:
    """-> TrueForge `require_approval_for_tools`, sorted for determinism."""

def plan_action(
    target: str, summary: str, payload: dict[str, Any], policy: dict[str, bool]
) -> ActionPlan:
    """Build an ActionPlan with requires_approval read from the policy."""
```

**Fail closed.** `agents/seed.ts` on PR #15 was fixed for exactly this bug:
`parseYaml(...) as Policy` is a compile-time cast that checks nothing, so a
typo like `requried` silently compiled to an *ungated write* and seeding still
reported success. Your loader must raise on any `approval` value that is not
exactly `required` or `none`, and on a target absent from the policy. A target
you cannot read is a target you refuse to act on — never a target you allow.
Test this directly.

## `adapters/github.py`

```python
class CodeHost(Protocol):
    def open_pr(self, branch: str, title: str, body: str, diff: str) -> str: ...
    def open_issue(self, title: str, body: str) -> str: ...

class GhClient:  # shells out to `gh`, already authenticated on this machine
```

Consumers type-hint `CodeHost`, never `GhClient` (spine rule 3).

Every subprocess call: explicit `timeout`, non-zero exit raises a typed error.
**Never** return a silent empty string or swallow a failure — a write that
didn't happen must never look like one that did. Copy the error discipline in
`adapters/brightdata.py`; it is the reference implementation for this.

`check_layering.py` bans network clients outside `adapters/brightdata.py`. `gh`
is a subprocess, not an HTTP client, and the checker already allows it — the
Bright Data rule governs *retrieving web content*, and this is a vendor CLI
called with our own credentials. See the PR #7 entry in `docs/decisions.md`;
that argument is settled, don't relitigate it.

## The gate — the point of the whole PR

```python
from src.main.agentradar.core.patch import can_act
```

`can_act(verify)` is already on `main` and already correct: `verify is not None
and verify.verified`, where `VerifyResult.verified` is a **computed field**
(`before.is_broken and after.is_green`) so it cannot be forged through
`save_verify`'s agent-supplied JSON. Do not reimplement it, do not re-derive
it, do not add a second gate beside it.

**Wire it so a red verification makes the GitHub tools genuinely unreachable,
not merely discouraged.** `open_pr` must not be callable with unproven
evidence — enforce it at the call boundary, not in a prompt. A comment saying
"only call this when tests are green" is not a gate.

The PR body must embed the before/after `TestReport`s. The evidence *is* the
product; a PR without it is just a diff from a stranger.

## Tests

`tests/agentradar/test_policy.py` — pure, no infra.
`tests/agentradar/test_github_adapter.py` — fake the subprocess. **No test may
touch the network or open a real PR.**

Must assert:

1. `load_policy` raises on `approval: requried`, on a missing `approval` key,
   and on a null value — one test each.
2. `approval_tool_list` returns `github_issue, github_pr, slack` from the real
   `actions/policy.yaml` shape, sorted, with `export` absent.
3. `can_act(None)` → the PR tool is unreachable. Assert the *unreachability*,
   not just a false return.
4. A `VerifyResult` built from the real `fixtures/pytest_output_red.txt` and
   `fixtures/pytest_output_green.txt` via `core.testreport.parse_pytest` →
   reachable. Build the reports from the fixtures, do not hand-construct them:
   the red fixture is a collection error (`passed=0, failed=0, errors=2`) and
   hand-built reports hide exactly the bug that matters here.
5. `GhClient` raises on non-zero exit and on timeout — never returns "".

## Acceptance

- Deny → **zero** writes reach GitHub. Prove it with a fake that records calls.
- Approve → `open_pr` and `open_issue` produce a URL.
- `can_act` false → the tool is not reachable at all.
- Malformed policy → raises, does not default to ungated.
- All green: `ruff check`, `ruff format --check`, `python scripts/check_layering.py`,
  `mypy --strict src/main/agentradar`, `pytest tests/agentradar tests/shared -q`.

Qodo will review. Fix its findings or log the decline in `docs/decisions.md` —
silence is not an option.
