# Prewarm runbook

Executed by hand before the demo slot. Ten seconds of work; it buys the
difference between a 6.1s live cycle and a 16.2s one.

Measured at H0 with `sandbox/timing_probe.py` against a real Daytona sandbox
(default image: Debian 13, Python 3.14, ships `git`, `pip`, `uv`):

| Path | Steps | Time |
|---|---|---|
| Cold | create · clone · install · baseline green | **10.1s** |
| Live | bump · red · patch · green | **6.1s** |
| Create alone | — | 0.15–0.7s |

**Prewarming is an optimisation, not a dependency.** If the session dies, cold
recovery costs ten seconds. Do not improvise under pressure — rerun this file.

Every value below comes from `configs/demo.yaml`. Do not hardcode them
anywhere; read them from that file.

---

## 0. Before you start

```bash
grep -E 'repo_url|commit|install_spec_before|install_spec_after' configs/demo.yaml
echo "${DAYTONA_API_KEY:+DAYTONA_API_KEY is set}"
```

`daytona` is **not** a project dependency and cannot become one: it pulls
protobuf>=5 through opentelemetry, while `codegraphcontext` pins protobuf<3.21.
Run the probe in its own environment:

```bash
uv run --with daytona --with pyyaml --no-project python sandbox/timing_probe.py
```

Nothing on the test path needs the SDK. `DaytonaRunner` takes an
already-connected sandbox handle and imports `daytona` lazily inside
`connect`, so `tests/agentradar` runs without it.

The commit must be the **same one the graph indexed**. A prewarmed sandbox at a
different commit produces contact points that do not exist in the checkout, and
the impact table silently stops meaning anything.

## 1. Provision through TrueForge

Provision the sandbox **through a real TrueForge turn**, not the Daytona CLI —
`sandbox.created` must fire so the session timeline shows it.

Set the idle intervals explicitly on the provider config. A "kept alive"
session can still be stopped out from under you by the defaults:

| Setting | Value | Why |
|---|---|---|
| `auto_stop_interval_in_minutes` | `0` | never stop on idle |
| `auto_archive_interval_in_minutes` | `0` | never archive |
| `auto_delete_interval_in_minutes` | `0` | never delete |

`0` means disabled. If the provider rejects `0`, set each well past the wait
before your slot, and re-verify with step 5.

## 2. Clone at the pinned commit

```bash
git clone --filter=blob:none <repo_url> /home/daytona/repo
cd /home/daytona/repo && git checkout -q <commit>
```

## 3. Install baseline deps and confirm green

```bash
pip install -q --break-system-packages -e ".[dev]" "<install_spec_before>"
python -m pytest -q
```

**Stop here if this is not green.** A red baseline makes the whole repro
worthless — you cannot prove a release broke something that was already broken.
Expected: `61 passed`.

## 4. Keep it alive

Record the sandbox id. Leave the TrueForge session open. Do not restart the
harness between now and the demo — reattach with:

```python
DaytonaRunner.connect(api_key, sandbox_id)
```

The API key stays in the harness. **Nothing that runs in the sandbox ever
receives a credential** — not as an env var, not in a command, not in a file.

## 5. Verify it survived the gap

Just before the slot:

```bash
cd /home/daytona/repo && git rev-parse HEAD && python -m pytest -q
```

Still green at the right commit → go. Anything else → tear it down and rerun
steps 1–3. That is ten seconds, not a lost demo.

`python3 sandbox/timing_probe.py --idle-minutes N` tests idle survival directly
if you want the answer before the day.

---

## On stage

The warmup is **setup, not evidence.** Every number in the impact claim comes
from a run *after* the version change.

1. Bump — `set_package_version(dependency, to_version)`
2. Red — `run_tests(<graph-selected node ids>)` → `parse_pytest` → `is_broken`
3. Patch — `apply_patch(diff)`
4. Green — `run_tests(<the same node ids>)` → `parse_pytest` → `is_green`

Step 4 must run **the same node ids** as step 2. A repro that reports red on one
set of tests and green on another proves nothing.

## Teardown

```python
sandbox.delete()
```

Daytona bills while a sandbox exists. Delete it after the demo.
