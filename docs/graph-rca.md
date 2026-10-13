# Graph RCA CLI

Graph RCA is the inherited code-intelligence foundation of AgentRadar. It parses application logs, maps them to a FalkorDB code graph, runs trace agents, and combines multiple judging perspectives into a root-cause analysis. It also supports codebase queries without logs.

After `uv sync --group dev`, configure a provider using `.env.example` and start the graph worker as described in the [runbook](runbook.md).

```bash
uv run graph-rca index --repo /path/to/repo --name repo-name
uv run graph-rca run --log /path/to/app.log --repo /path/to/repo --config configs/my-repo.yaml --verbose
uv run graph-rca query "how does provisioning work" --repo repo-name --config configs/my-repo.yaml
```

Create a repository config from `configs/base/`. See [configuration guidance](../configs/WRITING_CONFIG.md) and the [original getting-started guide](wiki/code-rca-get-started.md).

`install.sh` is the original interactive Graph RCA installer. It is not the quick-start path for the AgentRadar dashboard or conductor.
