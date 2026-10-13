# Contributing

AgentRadar's primary workflow is dependency-break detection and repair. Start with the [README](README.md) and [architecture](docs/architecture.md).

Keep changes focused and open a pull request against `main`. Preserve the existing Graph RCA implementation unless your change explicitly concerns it. Record relevant tradeoffs in the PR; historical hackathon plans are context, not a current task list.

## Setup

- Python 3.11+ and uv for the backend: `uv sync --group dev`.
- Node.js 22.14+ for the dashboard: `npm ci --prefix apps/web`.
- The local replay and fixed-patch repair require no service credentials. Use the [runbook](docs/runbook.md) for the connected workflow.

## Boundaries

- Keep external effects in adapters and use protocols at the decision layer.
- Return contract models from MCP handlers; update `contracts/schemas` with `python scripts/export_schemas.py` when models change.
- Keep release/news retrieval behind Bright Data. Harness, model, graph, and GitHub integration use their dedicated adapters.
- Do not pass credentials into sandbox commands or commit `.env`, databases, private transcripts, or local review exports.
- Preserve verification and human-approval gates. A replay is never fresh execution evidence.

## Before opening a PR

Run the [testing commands](docs/testing.md) relevant to the change. Include the exact result and any skipped or unavailable live-service checks. Browser tests use a production build and isolated local evidence storage.

The project is [MIT licensed](LICENSE). Third-party dependencies and the external demonstration repository retain their own licenses.
