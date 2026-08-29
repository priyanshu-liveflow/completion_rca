"""MCP server over GitHub writes. Tools: github_pr, github_issue.

Tool names match `actions/policy.yaml` targets so TrueForge
`require_approval_for_tools` actually pauses before a write. `github_pr` is
gated a second time at the call boundary by `can_act` — a red verification
makes the write unreachable even if a prompt says to call it anyway.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.main.agentradar.adapters.github import (
    ActionDenied,
    CodeHost,
    GateClosed,
    GhClient,
    GhError,
    execute,
    pr_writer,
)
from src.main.agentradar.contracts.mission import ActionPlan
from src.main.agentradar.contracts.patch import VerifyResult
from src.main.agentradar.core.policy import PolicyError, load_policy, plan_action
from src.main.agentradar.mcp._server import ToolError, serve, tool

POLICY_PATH = Path(__file__).resolve().parents[4] / "actions" / "policy.yaml"

_host: CodeHost | None = None
_policy: dict[str, bool] | None = None


def set_host(host: CodeHost) -> None:
    """Inject a CodeHost. Tests pass a recording fake."""
    global _host
    _host = host


def get_host() -> CodeHost:
    """Active host, defaulting to the `gh` CLI adapter."""
    if _host is None:
        return GhClient()
    return _host


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


@tool(
    "github_pr",
    "Open a pull request carrying a verified patch. Unreachable unless "
    "VerifyResult.verified is a proven red-to-green transition. Body is built "
    "from the before/after TestReports; the agent cannot omit them.",
    {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": "Head branch already pushed to the remote",
            },
            "title": {"type": "string", "description": "Pull request title"},
            "summary": {
                "type": "string",
                "description": "One-line ask shown above the evidence",
            },
            "diff": {
                "type": "string",
                "description": "Unified diff included in the PR body",
            },
            "verify": {
                "type": "object",
                "description": "VerifyResult dump; `verified` is computed, not trusted",
            },
        },
        "required": ["branch", "title", "diff", "verify"],
    },
)
def github_pr(
    branch: str,
    title: str,
    diff: str,
    verify: dict[str, Any],
    summary: str = "",
) -> ActionPlan:
    """Open a PR. Returns an ActionPlan whose payload includes the URL."""
    try:
        result = VerifyResult.model_validate(verify)
    except ValidationError as exc:
        raise ToolError("invalid_input", f"verify: {exc}") from exc

    host = get_host()
    if pr_writer(host, result) is None:
        raise ToolError(
            "gate_closed",
            "github_pr is unreachable without a proven red-to-green transition",
        )

    plan = _plan(
        "github_pr",
        summary or title,
        {"branch": branch, "title": title, "diff": diff},
    )
    try:
        url = execute(host, plan, approved=True, verify=result)
    except GateClosed as exc:
        raise ToolError("gate_closed", str(exc)) from exc
    except ActionDenied as exc:
        raise ToolError("denied", str(exc)) from exc
    except GhError as exc:
        raise ToolError("github", str(exc)) from exc
    except PolicyError as exc:
        raise ToolError("policy", str(exc)) from exc
    return _plan(
        "github_pr",
        plan.summary,
        {"url": url, "branch": branch, "title": title, "diff": diff},
    )


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
    try:
        url = execute(host, plan, approved=True)
    except ActionDenied as exc:
        raise ToolError("denied", str(exc)) from exc
    except GhError as exc:
        raise ToolError("github", str(exc)) from exc
    except PolicyError as exc:
        raise ToolError("policy", str(exc)) from exc
    return _plan("github_issue", title, {"url": url, "title": title, "body": body})


def main() -> None:
    """Entry: `python -m src.main.agentradar.mcp.github_server --port 8768`."""
    import argparse

    parser = argparse.ArgumentParser(description="AgentRadar GitHub MCP server")
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    serve("mcp-github", args.port)


if __name__ == "__main__":
    main()
