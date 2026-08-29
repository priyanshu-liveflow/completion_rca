"""MCP server over GitHub writes. Tools: github_pr, github_issue.

Tool names match `actions/policy.yaml` targets so TrueForge
`require_approval_for_tools` actually pauses before a write. `github_pr` is
gated a second time at the call boundary by `can_act` — a red verification
makes the write unreachable even if a prompt says to call it anyway.

The verify evidence is loaded from the mission store, not from the tool
arguments. A caller-authored `VerifyResult` dump cannot open the gate.
The diff written into the PR body is `mission.verify.patch.diff`, not a
second caller-supplied patch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.main.agentradar.adapters.github import (
    ActionDenied,
    CodeHost,
    GateClosed,
    GhClient,
    GhError,
    execute,
    pr_writer,
)
from src.main.agentradar.adapters.store import (
    MissionStore,
    SqliteStore,
    default_store_path,
)
from src.main.agentradar.contracts.mission import ActionPlan
from src.main.agentradar.contracts.patch import VerifyResult
from src.main.agentradar.core.policy import PolicyError, load_policy, plan_action
from src.main.agentradar.mcp._server import ToolError, serve, tool

POLICY_PATH = Path(__file__).resolve().parents[4] / "actions" / "policy.yaml"

_host: CodeHost | None = None
_policy: dict[str, bool] | None = None
_store: MissionStore | None = None
_default_store: SqliteStore | None = None


def set_host(host: CodeHost) -> None:
    """Inject a CodeHost. Tests pass a recording fake."""
    global _host
    _host = host


def get_host() -> CodeHost:
    """Active host, defaulting to the `gh` CLI adapter."""
    if _host is None:
        return GhClient()
    return _host


def set_store(store: MissionStore) -> None:
    """Inject a store. Tests pass ``SqliteStore(':memory:')``."""
    global _store
    _store = store


def get_store() -> MissionStore:
    """Active store, sharing the same default path as ``store_server``."""
    global _default_store
    if _store is not None:
        return _store
    if _default_store is None:
        _default_store = SqliteStore(default_store_path())
    return _default_store


def set_policy(policy: dict[str, bool]) -> None:
    """Inject a parsed policy. Tests pass a fixture mapping."""
    global _policy
    _policy = policy


def get_policy() -> dict[str, bool]:
    """Active policy, defaulting to `actions/policy.yaml`."""
    if _policy is not None:
        return _policy
    try:
        text = POLICY_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise ToolError("policy", f"cannot read {POLICY_PATH}: {exc}") from exc
    try:
        return load_policy(text)
    except PolicyError as exc:
        raise ToolError("policy", str(exc)) from exc


def _plan(target: str, summary: str, payload: dict[str, Any]) -> ActionPlan:
    try:
        return plan_action(target, summary, payload, get_policy())
    except PolicyError as exc:
        raise ToolError("policy", str(exc)) from exc


def _with_url(plan: ActionPlan, url: str) -> ActionPlan:
    """Attach the write URL to an already-validated plan. No second policy read."""
    return plan.model_copy(update={"payload": {**plan.payload, "url": url}})


def _run_write(
    host: CodeHost, plan: ActionPlan, *, verify: VerifyResult | None = None
) -> str:
    try:
        return execute(host, plan, approved=True, verify=verify)
    except GateClosed as exc:
        raise ToolError("gate_closed", str(exc)) from exc
    except ActionDenied as exc:
        raise ToolError("denied", str(exc)) from exc
    except GhError as exc:
        raise ToolError("github", str(exc)) from exc
    except PolicyError as exc:
        raise ToolError("policy", str(exc)) from exc


@tool(
    "github_pr",
    "Open a pull request for a mission whose store already holds a proven "
    "red-to-green VerifyResult. The PR body is built from those reports and "
    "the verified patch; the agent cannot omit them or substitute another diff.",
    {
        "type": "object",
        "properties": {
            "mission_id": {
                "type": "string",
                "description": "Mission whose save_verify result gates the write",
            },
            "branch": {
                "type": "string",
                "description": "Head branch already pushed to the remote",
            },
            "title": {"type": "string", "description": "Pull request title"},
            "summary": {
                "type": "string",
                "description": "One-line ask shown above the evidence",
            },
        },
        "required": ["mission_id", "branch", "title"],
    },
)
def github_pr(
    mission_id: str,
    branch: str,
    title: str,
    summary: str = "",
) -> ActionPlan:
    """Open a PR. Returns an ActionPlan whose payload includes the URL."""
    try:
        mission = get_store().get_mission(mission_id)
    except KeyError as exc:
        message = str(exc.args[0]) if exc.args else str(exc)
        raise ToolError("not_found", message) from exc

    result = mission.verify
    host = get_host()
    if pr_writer(host, result) is None or result is None:
        raise ToolError(
            "gate_closed",
            "github_pr is unreachable without a proven red-to-green transition",
        )

    plan = _plan(
        "github_pr",
        summary or title,
        {"branch": branch, "title": title, "diff": result.patch.diff},
    )
    url = _run_write(host, plan, verify=result)
    return _with_url(plan, url)


@tool(
    "github_issue",
    "File an issue for a call site reproduction proved broken.",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Issue title"},
            "body": {"type": "string", "description": "Issue body"},
        },
        "required": ["title", "body"],
    },
)
def github_issue(title: str, body: str) -> ActionPlan:
    """File an issue. Returns an ActionPlan whose payload includes the URL."""
    host = get_host()
    plan = _plan("github_issue", title, {"title": title, "body": body})
    url = _run_write(host, plan)
    return _with_url(plan, url)


def main() -> None:
    """Entry: `python -m src.main.agentradar.mcp.github_server --port 8768`."""
    import argparse

    parser = argparse.ArgumentParser(description="AgentRadar GitHub MCP server")
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    serve("mcp-github", args.port)


if __name__ == "__main__":
    main()
