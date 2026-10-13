# AgentRadar mission control

Next.js / React dashboard for inspecting dependency-break evidence, sandbox output, and review verification. See the [project README](../../README.md) for the product and the [architecture](../../docs/architecture.md) for data flow.

## Run locally

Requires Node.js 22.14+.

```bash
npm ci
npm run dev -- --hostname 127.0.0.1
```

- `/`: recorded replay. No backend or service keys needed; decisions are local only.
- `/?live=1`: starts a TrueForge session through the local proxy. Follow the [runbook](../../docs/runbook.md) first. Resolve live approvals in TrueForge; browser submission and session resume are not implemented.
- `/sandbox`: read-only pop-out of the current dashboard evidence.
- `/reviews`: stored review/repair evidence, with controls for a local repair demonstration or PR verification. Python must be installed in the repository's `.venv`.

The fixed-patch demo runs real local tests and Git against a temporary package; it does not perform dependency discovery or call a model. Model repair requires the existing provider configuration in the server environment.

The app is intended for local use. Do not expose its command-running endpoints or harness proxy as a public hosted service.

## Test

```bash
npm run lint
npm run test
npm run build
npx playwright install chromium
npm run test:e2e
```

Browser E2E starts the production server on `127.0.0.1:3100`, uses its own store and review export under the repository's ignored `.e2e/` directory, and never requires a GitHub write. Install the Python dependencies first. See [testing details](../../docs/testing.md).

`AGENTRADAR_REVIEW_EXPORT` may point to an absolute JSON export path; when omitted, `/reviews` reads `public/review-runs.json`. Match this value in the verifier and Next.js server when using a custom path.
