# Testing

Run commands from the repository root unless a section says otherwise. Test results apply to the selected revision and environment, not to every supported provider or dependency.

## Backend

Full environment:

```bash
uv sync --group dev
uv run ruff check src/main/agentradar tests/agentradar
uv run ruff format --check src/main/agentradar tests/agentradar
uv run python scripts/check_layering.py
uv run mypy --strict src/main/agentradar
uv run python scripts/export_schemas.py --check
uv run pytest tests/agentradar tests/shared -q
```

For the smaller CI-only environment, install `requirements-ci.txt` into a fresh virtual environment and invoke its tools directly. This does not install the legacy indexer or cloud sandbox SDK.

```bash
uv venv .venv-ci
uv pip install --python .venv-ci/bin/python -r requirements-ci.txt
.venv-ci/bin/python -m pytest tests/agentradar tests/shared -q
```

The socket tests need permission to create a local Unix socket. Live graph tests skip when the FalkorDB Lite worker is unavailable. To run those, start `cgc api start --host 127.0.0.1`, with the pinned demo repository already indexed, then rerun pytest. A skipped graph test is not a live graph pass.

## Frontend unit tests and production build

```bash
npm ci --prefix apps/web
npm run lint --prefix apps/web
npm run test --prefix apps/web
npm run build --prefix apps/web
```

## Browser end-to-end tests

Requires the root `.venv` to contain Python test dependencies. From `apps/web`:

```bash
npx playwright install chromium
npm run build
npm run test:e2e
```

Playwright launches the production server on port 3100 and exercises:

- replay labeling, approval locked before and during a red run, green verification, confirmation, and denial;
- dock collapse/expand and the read-only sandbox pop-out;
- a simulated unavailable harness, with no successful replay fallback;
- a fresh review screen, real Python/Git/pytest repair through the HTTP endpoint, persisted before/after evidence, and reload.

Each run creates a separate database and review export under `.e2e/`; it never replaces the developer's review history. Reports and failure traces are ignored by Git. The service-failure test injects an HTTP 503; it does not contact TrueForge. Replay checks validate the UI, not the truth of a live dependency migration.

## Local repair integration check

```bash
uv run python scripts/demo_repair.py --canned --no-save
```

This creates real files, observes two failing tests, applies a fixed source patch, and observes those tests pass. The temporary package has no remote and opens no PR. Selection is manual and the graph source is static. This proves the repair mechanism, not release discovery or cloud orchestration.

## Connected dependency E2E

Use the [runbook](runbook.md) to configure the real graph, release collector, harness, model, sandbox, and GitHub target. Verify the following in one mission:

1. The graph and sandbox use the same source commit.
2. The selected tests pass on the baseline version.
3. The dependency changes to the requested version and the same tests fail.
4. The patch changes allowed source files only.
5. The same tests pass after the patch and the saved verification gate opens.
6. A denied action makes no GitHub write. An approved action creates the intended PR with its evidence.

Do not classify a fixture replay, a fixed patch, a manually executed sandbox probe, or an unavailable provider as a complete connected E2E pass. Run GitHub publication checks against a designated test target with authorization for the write.

`scripts/smoke_chain.py` is an older mixed graph/recorded-output check. Its test output is loaded from fixtures; it does not run reproduction or establish a new red-to-green result.
