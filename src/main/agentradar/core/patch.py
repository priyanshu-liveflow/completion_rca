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
from collections.abc import Iterable

from ..contracts.evidence import TestReport
from ..contracts.impact import ImpactRow
from ..contracts.patch import Patch, VerifyResult

__all__ = [
    "allowed_files_from_impact",
    "build_verify_result",
    "can_act",
    "parse_diff",
    "validate_patch",
    "validate_submitted_patch",
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

    Records **both endpoints** of every file header, not just the destination.
    A git rename carries two distinct paths, and `git apply` acts on both: it
    deletes the source and creates the destination. Recording only `b/` meant
    `diff --git a/tests/test_server.py b/src/allowed.py` presented as a patch
    touching one allowed, non-test file — while applying it deleted a test.
    That defeats both of `validate_patch`'s rules at once, and
    `DaytonaRunner.apply_patch` hands the whole diff to `git apply` verbatim,
    so nothing downstream would have caught it. Every path the diff can move,
    create, or destroy has to be visible to validation.

    Never raises: a diff with no recognisable `diff --git` header or
    `---`/`+++` pair parses to an empty file list rather than throwing, so a
    caller can turn a malformed patch into a rejection instead of a crash.
    Rationale is not derivable from the diff text alone and is left blank for
    the caller to fill in.
    """
    files: list[str] = []
    seen: set[str] = set()
    pending_minus: str | None = None

    def record(*paths: str | None) -> None:
        for path in paths:
            if path is None or path == _DEV_NULL or path in seen:
                continue
            seen.add(path)
            files.append(path)

    for line in diff.splitlines():
        git_header = _DIFF_GIT.match(line)
        if git_header is not None:
            record(git_header.group("a"), git_header.group("b"))
            pending_minus = None
            continue

        minus = _MINUS_MINUS_MINUS.match(line)
        if minus is not None:
            pending_minus = minus.group("path")
            continue

        plus = _PLUS_PLUS_PLUS.match(line)
        if plus is not None:
            record(pending_minus, plus.group("path"))
            pending_minus = None

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


def allowed_files_from_impact(rows: Iterable[ImpactRow]) -> list[str]:
    """The blast radius, taken from evidence the store already holds.

    `validate_patch` is only as trustworthy as the `allowed_files` it is
    handed, so that list must not come from the same agent that wrote the
    diff. These are the files the graph named during impact analysis and the
    store persisted — the agent can widen its diff, but it cannot widen this.

    A mission with no impact rows yields an empty list, which makes
    `validate_patch` reject every patch. That is the intended answer: nothing
    was ever located, so there is no site a patch could legitimately be
    aimed at.
    """
    seen: set[str] = set()
    files: list[str] = []
    for row in rows:
        path = row.contact_point.file_path
        if path and path not in seen:
            seen.add(path)
            files.append(path)
    return sorted(files)


def validate_submitted_patch(
    patch: Patch, allowed_files: list[str]
) -> tuple[bool, str]:
    """`validate_patch` for a patch whose `files` list came from the agent.

    The file list is re-derived from the diff text and the supplied one is
    discarded. `Patch.files` is an ordinary field, so anything reaching this
    module through `VerifyResult.model_validate` on agent JSON can declare
    `files: ["src/client.py"]` beside a diff that renames
    `tests/test_server.py` away — passing both of `validate_patch`'s rules
    while `git apply` deletes a test. Reading the diff is the only view of
    the patch that `git apply` and this function share.
    """
    return validate_patch(parse_diff(patch.diff), allowed_files)


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
