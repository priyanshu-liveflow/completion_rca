# AgentRadar

Graph is the cheap filter. Sandbox is the expensive prover. A PR opens only on a proven red → green.

```
src/main/agentradar/
├─ contracts/   pydantic v2 models. Imports NOTHING from siblings. No logic.
├─ core/        pure functions over contracts. No I/O, network, subprocess, or clock.
├─ adapters/    the ONLY code that touches the outside world. Protocol + one impl each.
└─ mcp/         thin servers: parse → validate → call core/adapter → return a contract.
```

## Four rules

1. `core/` may not import `adapters/` or `mcp/`. Enforced by `scripts/check_layering.py`.
2. All outbound web access goes through Bright Data. No `fetch`, `requests`, `httpx`, `urllib`, `aiohttp`, `curl`, or any unproxied client — including in tests and scripts. The only sanctioned network module is `adapters/brightdata.py`, which shells out to the `bdata` CLI.
3. Every adapter is a `typing.Protocol` plus one concrete impl. Consumers type-hint the Protocol, never the impl.
4. Every MCP handler returns a contract model. No bare `dict` returns.

Inherited `graph_rca` code is out of scope for ruff/mypy/format. Do not reformat it.

## Bright Data

Coverage: SERP → `web_search`; Web Unlocker → `scrape_page`; Scraper Studio → `run_collector`.

Collectors are the durable artifact. IDs (`c_*`) survive healing — never regenerate them.

```json
{
  "id": "c_...",
  "url": "https://github.com/<dep>/releases",
  "description": "Extract releases: tag, date, body, breaking_change_flag",
  "required_fields": ["tag", "date", "body"],
  "health": { "min_rows": 5, "max_missing_field_ratio": 0.2 }
}
```

Heal procedure, in `run_collector`:

1. Run the collector.
2. Validate rows against `required_fields` + health thresholds.
3. On degradation, return the structured report **and** invoke `bdata scraper heal <id> "<symptom>" --url <url>`, polling to completion. `symptom` is the `HealthVerdict.symptom` string, verbatim.
4. Re-run. Emit `CollectorRun` with `health` and `health_after_heal`.

## Sandbox

The harness holds credentials. The sandbox gets code, files, and shell only. Secrets never enter the sandbox. Never pass an API key, token, or connection string into sandbox execution.

## Commits

Trunk-based. One concern per PR. Conventional commits: `feat(scope):`, `fix(scope):`, `chore:`.

- Branch: `feat/<slug>`, `fix/<slug>`, `chore/<slug>`.
- Scope new tooling to `src/main/agentradar` and `tests/agentradar`.
- Qodo findings: fix or log the decline in `docs/decisions.md`. Silence is not an option.
