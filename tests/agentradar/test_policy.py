"""Approval policy — pure, no infra.

Fail-closed: a typo, a missing key, or a null `approval` raises rather than
compiling to an ungated write.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.main.agentradar.core.policy import (
    PolicyError,
    approval_tool_list,
    load_policy,
    plan_action,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY_FILE = ROOT / "actions" / "policy.yaml"

_VALID = """\
targets:
  github_pr:
    approval: required
  github_issue:
    approval: required
  slack:
    approval: required
  export:
    approval: none
"""


def test_load_policy_raises_on_typo_requried() -> None:
    text = """\
targets:
  github_pr:
    approval: requried
"""
    with pytest.raises(PolicyError, match="requried"):
        load_policy(text)


def test_load_policy_raises_on_missing_approval_key() -> None:
    text = """\
targets:
  github_pr:
    description: opens a pull request
"""
    with pytest.raises(PolicyError, match="missing"):
        load_policy(text)


def test_load_policy_raises_on_null_approval() -> None:
    text = """\
targets:
  github_pr:
    approval: null
"""
    with pytest.raises(PolicyError, match="approval"):
        load_policy(text)


def test_approval_tool_list_from_real_policy_shape() -> None:
    policy = load_policy(POLICY_FILE.read_text(encoding="utf-8"))
    assert approval_tool_list(policy) == ["github_issue", "github_pr", "slack"]
    assert "export" not in approval_tool_list(policy)
    assert policy["export"] is False


def test_load_policy_maps_required_and_none() -> None:
    policy = load_policy(_VALID)
    assert policy == {
        "github_pr": True,
        "github_issue": True,
        "slack": True,
        "export": False,
    }


def test_plan_action_reads_requires_approval_from_policy() -> None:
    policy = load_policy(_VALID)
    gated = plan_action("github_pr", "open the PR", {"branch": "fix/x"}, policy)
    assert gated.requires_approval is True
    ungated = plan_action("export", "write a report", {"path": "out.md"}, policy)
    assert ungated.requires_approval is False


def test_plan_action_raises_on_target_absent_from_policy() -> None:
    policy = load_policy(_VALID)
    with pytest.raises(PolicyError, match="absent"):
        plan_action("webhook", "ping", {}, policy)
