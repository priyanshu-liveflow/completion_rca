# Graph RCA

Standalone project for graph-driven root cause analysis. Parses application logs, maps them to a FalkorDB code graph, runs parallel trace agents, then uses multi-lens judges to converge on a root cause.

This is a copy of the `graph_rca` stack from explorer — plus every support file it needs to run on its own (`shared`, `code_tools`, `config`, domain YAMLs, CLI).

## Quick Setup

```bash
cd /Users/priyanshu/graph_rca
./install.sh
```

Prerequisites: [uv](https://docs.astral.sh/uv/getting-started/installation/), Python 3.11+, [codegraphcontext](https://pypi.org/project/codegraphcontext/), AWS credentials (Bedrock) or Ollama.

## Commands

### Index a repo

```bash
uv run graph-rca index --repo /path/to/repo --name repo-name
uv run graph-rca index --repo /path/to/repo --name repo-name --force
uv run graph-rca index --repo /path/to/repo --name repo-name --skip-codegraph
uv run graph-rca index --repo /path/to/repo --name repo-name --summary   # optional, needs ollama
```

### Run RCA on a log

```bash
uv run graph-rca run \
  --log /path/to/app.log \
  --repo /path/to/repo \
  --config configs/ecmv4.yaml \
  --verbose
```

Interactive (pick clusters before investigating):

```bash
uv run graph-rca run \
  --log /path/to/app.log \
  --repo /path/to/repo \
  --config configs/ecmv4.yaml \
  --interactive
```

### Query the codebase (no log)

```bash
uv run graph-rca query "how does provisioning work" --repo ecmv4-g2 --config configs/ecmv4.yaml
uv run graph-rca query "provisioning comments" --repo ecmv4-g2 --config configs/ecmv4.yaml --interactive
```

## Repo config

Copy a base template and edit it:

```bash
cp configs/base/spring-boot.yaml configs/my-repo.yaml
```

See `configs/WRITING_CONFIG.md` and `docs/wiki/code-rca-get-started.md`.

## Layout

```
src/main/
  cli.py                 # graph-rca entry: run | index | summarize | query
  graph_rca/             # pipeline, index, resolve, align, prompts
  shared/                # LLM loop, providers (aws/azure/ollama), logging
  code_tools/            # FalkorDB access + trace-agent tools
  config/                # env-backed JSON configs
configs/
  base/                  # spring-boot, python-logging, go-structured
  flow_patterns/         # per-language flow extractors
  runtime/               # bedrock / ollama model budgets
  ecmv4.yaml idwms.yaml
```

## Pipeline

```
PREPARE (parse + resolve + tier + cluster)
    → ROUTE (filter clusters by prompt relevance)
    → INVESTIGATE
        Mode A: EXPLAIN (parallel agents per function)
        Mode B: RCA (decompose → parallel trace agents → multi-lens judges)
    → JUDGE (route → lens → final verdict)
```
