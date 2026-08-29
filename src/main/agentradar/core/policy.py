"""Approval policy for conductor action targets.

Pure: YAML *text* in, a mapping out. No filesystem, no network, no subprocess.
The file `actions/policy.yaml` is read by the caller (MCP, tests, seed) and
handed here as a string, so a missing file is a missing argument rather than a
silent default.

Fail closed. `agents/seed.ts` was fixed for exactly this bug: a compile-time
cast that checked nothing, so a typo like `requried` compiled to an *ungated
write* and seeding still reported success. Anything this loader cannot read as
exactly `required` or `none` raises. A target absent from the policy is a
target we refuse to act on — never a target we allow.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from ..contracts.evidence import TestReport
from ..contracts.mission import ActionPlan
from ..contracts.patch import VerifyResult

__all__ = [
    "APPROVAL_NONE",
    "APPROVAL_REQUIRED",
    "PolicyError",
    "approval_tool_list",
    "load_policy",
    "plan_action",
    "pr_body",
]

APPROVAL_REQUIRED = "required"
APPROVAL_NONE = "none"
_APPROVAL_VALUES = frozenset({APPROVAL_REQUIRED, APPROVAL_NONE})

ActionTarget = Literal["github_pr", "github_issue", "slack", "export"]
_ACTION_TARGETS: tuple[str, ...] = get_args(ActionTarget)


class PolicyError(ValueError):
    """Malformed or incomplete policy. Never a license to skip approval."""


def load_policy(text: str) -> dict[str, bool]:
    """YAML text -> ``{target_name: requires_approval}``.

    Raises :class:`PolicyError` on any `approval` value that is not exactly
    `required` or `none`, on a missing `approval` key, and on a null value.
    """
    try:
        parsed: Any = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PolicyError("policy is not valid YAML") from exc
    if not isinstance(parsed, dict):
        raise PolicyError("policy must be a mapping")

    targets = parsed.get("targets")
    if not isinstance(targets, dict) or not targets:
        raise PolicyError("policy has no `targets` map")

    out: dict[str, bool] = {}
    for name, spec in targets.items():
        if not isinstance(name, str) or not name:
            raise PolicyError(f"policy target name {name!r} is not a non-empty string")
        out[name] = _requires_approval(name, spec)
    return out


def _requires_approval(name: str, spec: object) -> bool:
    if not isinstance(spec, dict):
        raise PolicyError(f"target {name!r} is not a mapping")
    if "approval" not in spec:
        raise PolicyError(
            f"target {name!r} is missing `approval`; "
            "refusing to act: an unreadable approval would compile to an ungated write"
        )
    approval = spec["approval"]
    if not isinstance(approval, str) or approval not in _APPROVAL_VALUES:
        raise PolicyError(
            f"target {name!r} has approval {approval!r}; expected "
            f"{APPROVAL_REQUIRED!r} or {APPROVAL_NONE!r}. "
            "Refusing to act: an unreadable approval value would compile to "
            "an ungated write."
        )
    return approval == APPROVAL_REQUIRED


def approval_tool_list(policy: dict[str, bool]) -> list[str]:
    """TrueForge `require_approval_for_tools`, sorted for determinism."""
    return sorted(name for name, required in policy.items() if required)


def plan_action(
    target: str,
    summary: str,
    payload: dict[str, Any],
    policy: dict[str, bool],
) -> ActionPlan:
    """Build an ActionPlan with `requires_approval` read from the policy.

    A target not present in `policy` raises — it is not treated as ungated.
    """
    if target not in policy:
        raise PolicyError(
            f"target {target!r} is absent from the policy — refusing to act"
        )
    if target not in _ACTION_TARGETS:
        raise PolicyError(f"target {target!r} is not a known action")
    try:
        return ActionPlan.model_validate(
            {
                "target": target,
                "summary": summary,
                "payload": payload,
                "requires_approval": policy[target],
            }
        )
    except ValidationError as exc:
        raise PolicyError(f"target {target!r} is not a known action") from exc


def pr_body(summary: str, verify: VerifyResult) -> str:
    """Markdown PR body that embeds the before/after :class:`TestReport`s.

    The evidence is the product; a PR without these counts is just a diff
    from a stranger. Built here, not left to the agent, so the reports cannot
    be omitted by a prompt.
    """
    before = verify.before
    after = verify.after
    files = ", ".join(verify.patch.files) or "(none)"
    diff = verify.patch.diff.rstrip()
    diff_block = f"```diff\n{diff}\n```" if diff else "_(empty diff)_"
    return "\n".join(
        [
            summary.strip(),
            "",
            "## Evidence",
            "",
            _report_block("Before", before.package, before.version, before),
            _report_block("After", after.package, after.version, after),
            f"verified={verify.verified}",
            "",
            "## Patch",
            "",
            f"Files: {files}",
            "",
            diff_block,
            "",
        ]
    )


def _report_block(label: str, package: str, version: str, report: TestReport) -> str:
    return "\n".join(
        [
            f"### {label}: {package} {version}",
            f"- passed={report.passed} failed={report.failed} errors={report.errors}",
            f"- is_broken={report.is_broken} is_green={report.is_green}",
            f"- duration_s={report.duration_s}",
            "",
        ]
    )
