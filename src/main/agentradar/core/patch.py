"""Validate a candidate patch and gate PR/issue tools on proven repair.

Pure: no I/O, no network, no subprocess, no clock. Patch *application* runs
through the harness-native sandbox (``adapters/sandbox.py::DaytonaRunner.apply_patch``),
driven by the agent, exactly like test execution in PR5. This module owns two
decisions only, both made from text and contracts already in hand:

1. ``validate_patch`` — is this diff even allowed to be applied? An agent that
   "fixes" a failing test by editing the test itself has defeated the entire
   product, so edits to test files are rejected outright, and so is anything
   outside the blast radius that justified writing the patch in the first
   place.
2. ``can_act`` — given a completed before/after run, may the PR/issue tools
   fire at all? This is the single most important assertion in the codebase.
   Our demo's own red case is a *collection* error: two modules never import,
   so pytest reports ``failed == 0, errors == 2``. A gate keyed on
   ``before.failed > 0`` would refuse to open the PR after a patch that
   actually worked, at the last step of the demo. ``before.is_broken`` and
   ``after.is_green`` are the only counts that survive that failure mode —
   see ``contracts/evidence.py`` and the warning on ``VerifyResult.verified``
   in ``contracts/patch.py``.
"""

from __future__ import annotations

import re

from ..contracts.evidence import TestReport
from ..contracts.patch import Patch, VerifyResult

__all__ = [
    "build_verify_result",
    "can_act",
    "parse_diff",
    "validate_patch",
]

# `diff --git a/path b/path` — the header every git-produced unified diff
# carries, including diffs an LLM writes when asked to mimic `git diff`.
_DIFF_GIT = re.compile(r"^diff --git a/(?P<a>\S+) b/(?P<b>\S+)$")

# Fallback for a plain `diff -u` style patch with only the `---`/`+++` pair
# and no `diff --git` header.
_MINUS_MINUS_MINUS = re.compile(r"^--- (?:a/)?(?P<path>\S+)")
_PLUS_PLUS_PLUS = re.compile(r"^\+\+\+ (?:b/)?(?P<path>\S+)")

_DEV_NULL = "/dev/null"

# Conventional test-file shapes: any path segment named `test`/`tests` (this
# repo's own demo config pins `test_root: "tests"`), or a leaf matching
# pytest's own discovery rule (`test_*.py` / `*_test.py`).
_TEST_DIR_SEGMENTS = frozenset({"test", "tests"})
_TEST_LEAF = re.compile(r"^(test_.+\.py|.+_test\.py)$")


def _is_test_file(path: str) -> bool:
    """True if `path` is a test file by pytest's own discovery convention."""
    parts = path.split("/")
    if any(part in _TEST_DIR_SEGMENTS for part in parts[:-1]):
        return True
    return bool(_TEST_LEAF.match(parts[-1]))


def parse_diff(diff: str) -> Patch:
    """Parse a unified diff into a `Patch`, reading only its file headers.

    Never raises: a diff with no recognisable `diff --git` header or
    `---`/`+++` pair parses to an empty file list rather than throwing, so a
    caller can turn a malformed patch into a rejection instead of a crash.
    Rationale is not derivable from the diff text alone and is left blank for
    the caller to fill in.
    """
    files: list[str] = []
    seen: set[str] = set()
    pending_minus: str | None = None

    for line in diff.splitlines():
        git_header = _DIFF_GIT.match(line)
        if git_header is not None:
            path = git_header.group("b")
            if path == _DEV_NULL:
                path = git_header.group("a")
            if path != _DEV_NULL and path not in seen:
                seen.add(path)
                files.append(path)
            pending_minus = None
            continue

        minus = _MINUS_MINUS_MINUS.match(line)
        if minus is not None:
            pending_minus = minus.group("path")
            continue

        plus = _PLUS_PLUS_PLUS.match(line)
        if plus is not None:
            path = plus.group("path")
            if path == _DEV_NULL:
                path = pending_minus
            pending_minus = None
            if path is not None and path != _DEV_NULL and path not in seen:
                seen.add(path)
                files.append(path)

    return Patch(diff=diff, files=files, rationale="")


def validate_patch(patch: Patch, allowed_files: list[str]) -> tuple[bool, str]:
    """Reject patches touching files outside the blast radius, or test files.

    `allowed_files` is the blast radius that justified writing the patch —
    the contact points and their dependents, not the whole repo. Returns
    `(True, reason)` when the patch may proceed to the sandbox, or
    `(False, reason)` with a reason string precise enough to show a human:
    which files, and which rule.
    """
    if not patch.files:
        return False, "patch touches no files (empty or unparsed diff)"

    test_hits = sorted(f for f in patch.files if _is_test_file(f))
    if test_hits:
        return False, (
            "patch edits test file(s) "
            f"{', '.join(test_hits)} — an agent may not fix a failing test "
            "by editing the test"
        )

    allowed = set(allowed_files)
    outside = sorted(f for f in patch.files if f not in allowed)
    if outside:
        return False, (
            f"patch touches file(s) outside the blast radius: {', '.join(outside)} "
            f"(allowed: {', '.join(sorted(allowed)) or 'none'})"
        )

    return True, "patch touches only allowed, non-test files"


def build_verify_result(
    patch: Patch, before: TestReport, after: TestReport
) -> VerifyResult:
    """Assemble before/after evidence and compute the one gate that matters.

    `VerifyResult.verified` is a computed field — `before.is_broken and
    after.is_green`, never `before.failed > 0` — so it cannot be supplied
    here or anywhere else. See this module's docstring for why.
    """
    return VerifyResult(patch=patch, before=before, after=after)


def can_act(verify: VerifyResult | None) -> bool:
    """PR tools are unreachable unless a real red-to-green transition was proven."""
    return verify is not None and verify.verified
