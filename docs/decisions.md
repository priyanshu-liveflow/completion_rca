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

