# Code-RCA: Get Started

Root cause analysis for application logs using a code graph. Feed it a log file + an indexed source repo → get back the exact function/class causing failures with evidence and a suggested fix.

---

## Prerequisites

| Tool | Install | Purpose |
|------|---------|---------|
| uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | Python package manager |
| codegraphcontext | `pipx install codegraphcontext` | Indexes repos into FalkorDB |
| AWS credentials | Bedrock access in us-east-1 | Claude Sonnet/Opus |
| graphviz | `brew install graphviz` | SVG visualization (optional) |

---

## Step 1: Clone & Install

```bash
cd /Users/priyanshu/graph_rca
./install.sh
# or: uv sync
```

---

## Step 2: Index Your Repo (Code Graph)

This parses source code into a FalkorDB graph: classes, functions, call edges, source code, imports.

```bash
codegraphcontext index /path/to/your/repo --force
```

### Verify index

```bash
# Count classes
redis-cli -s ~/.codegraphcontext/global/db/falkordb.sock \
  GRAPH.QUERY codegraph "MATCH (c:Class) WHERE c.path CONTAINS 'your-repo-name' RETURN count(c)"

# Count functions
redis-cli -s ~/.codegraphcontext/global/db/falkordb.sock \
  GRAPH.QUERY codegraph "MATCH (f:Function) WHERE f.path CONTAINS 'your-repo-name' RETURN count(f)"

# Spot check a class
redis-cli -s ~/.codegraphcontext/global/db/falkordb.sock \
  GRAPH.QUERY codegraph "MATCH (c:Class) WHERE c.name = 'YourClassName' RETURN c.name, c.path"
```

### Supported languages

codegraphcontext uses tree-sitter and supports: Java, Python, Go, Rust, C/C++, TypeScript/JavaScript, Groovy (patched), PowerShell (patched).

For Groovy/PowerShell support, run the patch first:
```bash
uv run python -c "from src.main.graph_rca.lang_support.patch_codegraphcontext import patch; patch()"
```

---

## Step 3: Build the Lite Log Index

The lite index maps log statements in source code → functions. This enables the resolver to match log lines back to their originating function without an LLM call.

```bash
# Use the unified index command (builds lite index + supplement + flow graphs)
uv run graph-rca index --repo /path/to/repo --name your-repo-name
```

### Verify lite index

```bash
# Check template count
uv run python -c "
from src.main.graph_rca.index.lite_index import get_index_stats
print(get_index_stats('your-repo-name'))
"

# Query a specific function's log templates
redis-cli -s ~/.codegraphcontext/global/db/falkordb.sock \
  GRAPH.QUERY codegraph "MATCH (lt:LogTemplate)-[:EMITTED_BY]->(f:Function {name: 'yourFunction'}) WHERE lt.repo_path CONTAINS 'your-repo-name' RETURN lt.static_text, lt.log_level"
```

### How it works

The lite index scans every function's source code for log statements (SLF4J, Log4j, Python logging, etc.), extracts static text fragments, and stores them as `LogTemplate` nodes connected to their function via `EMITTED_BY` edges.

During analysis, the preprocessor matches actual log lines against these templates to resolve which function produced each log entry — enabling Tier 2 resolution (unique template match) without any LLM call.

---

## Step 4: Create a Domain Config

Configs tell the preprocessor how to parse your log format:

```bash
cp configs/base/spring-boot.yaml configs/your-app.yaml
```

Edit `configs/your-app.yaml`:
```yaml
extends: base/spring-boot.yaml   # or python-logging.yaml, go-structured.yaml

repo: your-repo-name             # must match what was indexed
service_name: your-service

# Override only what differs from base
ignore_patterns:
  - 'GET /healthz'
  - 'HikariPool.*Thread starvation'

error_markers:
  - pattern: 'NullPointerException'
  - pattern: 'INVALID.AUTH.TOKEN'
```

### Available base templates

| Base | For |
|------|-----|
| `base/spring-boot.yaml` | Java/Groovy with Logback default layout |
| `base/python-logging.yaml` | Python stdlib logging |
| `base/go-structured.yaml` | Go structured JSON logs |

---

## Step 5: Run Analysis

```bash
uv run graph-rca run \
  --log /path/to/your/app.log \
  --mode code-rca \
  --repo your-repo-name \
  --config configs/your-app.yaml \
  --model "us.anthropic.claude-sonnet-4-5-20250929-v1:0" \
  --verbose
```

With visualization:
```bash
uv run graph-rca run \
  --log /path/to/your/app.log \
  --mode code-rca \
  --repo your-repo-name \
  --config configs/your-app.yaml \
  --model "us.anthropic.claude-sonnet-4-5-20250929-v1:0" \
  --verbose --visualize
```

### Use Opus for higher accuracy (slower, more expensive):
```bash
uv run graph-rca run \
  --log /path/to/your/app.log \
  --mode code-rca \
  --repo your-repo-name \
  --config configs/your-app.yaml \
  --model "us.anthropic.claude-opus-4-6-v1" \
  --verbose
```

---

## Pipeline Flow

```
1. PREPROCESS    — parse log, resolve each line to originating function via lite index
2. DECOMPOSE    — LLM plans 3-5 independent trace agent assignments
3. TRACE        — parallel agents walk the code graph with tools
4. ROUTE        — picks evaluation lenses based on agent findings
5. LENS JUDGES  — evaluate from different angles in parallel
6. FINAL JUDGE  — synthesizes verdict with confidence + fix suggestion
```

### Resolution tiers (preprocessor)

| Tier | Method | Speed |
|------|--------|-------|
| 1 | Stack trace frame → direct function lookup | Instant |
| 2 | Lite index unique template match | Instant |
| 3 | Contextual: class + neighbour inference | Instant |
| 4 | Unmapped (no resolution) | — |

Target: 95%+ lines resolved at Tier 1-3 before any LLM call.

---

## Verify Preprocessing Accuracy

```bash
uv run python -c "
from src.main.graph_rca.preprocess.parser import parse_log_entries
from src.main.graph_rca.resolve.resolver import resolve_entries
from src.main.graph_rca.models import WalkablePath
from src.main.graph_rca.config import DomainConfig

config = DomainConfig.from_yaml('configs/your-app.yaml')
log_text = open('/path/to/your/app.log').read()
entries = parse_log_entries(log_text, config)
entries, branches = resolve_entries(entries, 'your-repo-name', config)
mapped = sum(1 for e in entries if e.resolution_tier <= 3)
coverage = (mapped / len(entries) * 100) if entries else 0.0

print(f'Entries: {len(entries)}')
print(f'Coverage: {coverage:.1f}%')
tiers = {}
for e in entries:
    tiers[e.resolution_tier] = tiers.get(e.resolution_tier, 0) + 1
for t in sorted(tiers):
    print(f'  Tier {t}: {tiers[t]} ({100*tiers[t]//len(entries)}%)')
"
```

Expected output:
```
Entries: 5292
Coverage: 98%
Errors: 12
Tier breakdown:
  Tier 1: 203 (4%)
  Tier 2: 4891 (92%)
  Tier 3: 112 (2%)
  Tier 4: 86 (2%)
```

---

## Example: idwms JWT Auth Failure

```bash
uv run graph-rca run \
  --log tests/fixtures/idwms_errors.log \
  --mode code-rca \
  --repo idwms \
  --config configs/idwms.yaml \
  --model "us.anthropic.claude-sonnet-4-5-20250929-v1:0" \
  --verbose
```

Result: identifies `JwtTokenProvider.secretKey` field never initialized → 92% confidence.

---

## CLI Flags

| Flag | Description |
|------|-------------|
| `--log`, `-l` | Path to log file (required) |
| `--mode code-rca` | Use the code-graph RCA pipeline |
| `--repo`, `-r` | Repo name as indexed (required) |
| `--config` | YAML domain config (required for best results) |
| `--model` | Model override (Sonnet for speed, Opus for accuracy) |
| `--verbose`, `-v` | Show per-turn agent activity |
| `--visualize` | Generate SVG diagrams |
| `--output`, `-o` | Output directory (default: `output_run/`) |

---

## Cost

| Scenario | Approximate Cost |
|----------|-----------------|
| Sonnet, first run | ~$0.50-0.80 |
| Sonnet, cached | ~$0.30-0.50 |
| Opus, first run | ~$2-4 |
| Opus, cached | ~$1-2 |

Prompt caching gives 40-60% cost reduction after the first run.

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Coverage < 50% | Lite index missing or repo name mismatch | Rebuild: `build_lite_index('repo-name', verbose=True)` |
| All agents conf=0.30 | Functions not in graph | Verify: `redis-cli ... GRAPH.QUERY codegraph "MATCH (f:Function) WHERE f.path CONTAINS 'repo-name' RETURN count(f)"` |
| `Enter MFA code` crash | MFA prompt in non-interactive context | Pre-auth: `aws sts get-caller-identity` |
| `staleness warning` | Code changed since last index | Re-index: `codegraphcontext index /path/to/repo --force` |
| Groovy classes = 0 | Groovy parser not patched | Run: `uv run python -c "from src.main.graph_rca.lang_support.patch_codegraphcontext import patch; patch()"` then re-index |

---

## Full Setup Script (copy-paste)

```bash
# 1. Install
cd cua-log-analyzer && uv sync

# 2. Patch for Groovy/PowerShell (optional)
uv run python -c "from src.main.graph_rca.lang_support.patch_codegraphcontext import patch; patch()"

# 3. Index everything in one shot
uv run graph-rca index --repo /path/to/your/repo --name your-repo-name

# 4. Create config
cp configs/base/spring-boot.yaml configs/your-app.yaml
# Edit: set repo name, language, entry_start, line_pattern
# See: configs/WRITING_CONFIG.md

# 5. Run
uv run graph-rca run \
  --log your-log.log \
  --mode code-rca \
  --repo your-repo-name \
  --config configs/your-app.yaml \
  --verbose
```
