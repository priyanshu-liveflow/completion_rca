"""`parse_diff` and `validate_patch` — the test-file rejection is the product.

An agent that "fixes" a failing test by editing the test has defeated the
whole point of the patch-and-verify loop. These tests exist to prove that
rejection is enforced, and enforced by path (not just by convention).
"""

from __future__ import annotations

from src.main.agentradar.core.patch import parse_diff, validate_patch

_GOOD_DIFF = """\
diff --git a/src/pkg/client.py b/src/pkg/client.py
index 1111111..2222222 100644
--- a/src/pkg/client.py
+++ b/src/pkg/client.py
@@ -14,7 +14,7 @@ import logging
 import logging

-from mcp.server.fastmcp import FastMCP
+from mcp.server.mcpserver import MCPServer as FastMCP

 logger = logging.getLogger(__name__)
"""

_TEST_FILE_DIFF = """\
diff --git a/tests/test_server.py b/tests/test_server.py
index 3333333..4444444 100644
--- a/tests/test_server.py
+++ b/tests/test_server.py
@@ -1,3 +1,3 @@
-def test_get_activities():
+def test_get_activities_renamed():
     pass
"""

_MULTI_FILE_DIFF = """\
diff --git a/src/pkg/client.py b/src/pkg/client.py
index 1111111..2222222 100644
--- a/src/pkg/client.py
+++ b/src/pkg/client.py
@@ -1,1 +1,1 @@
-old
+new
diff --git a/tests/test_server.py b/tests/test_server.py
index 3333333..4444444 100644
--- a/tests/test_server.py
+++ b/tests/test_server.py
@@ -1,1 +1,1 @@
-old
+new
"""

_OUTSIDE_RADIUS_DIFF = """\
diff --git a/src/pkg/unrelated.py b/src/pkg/unrelated.py
index 5555555..6666666 100644
--- a/src/pkg/unrelated.py
+++ b/src/pkg/unrelated.py
@@ -1,2 +1,2 @@
-old
+new
"""

_PLAIN_UNIFIED_DIFF = """\
--- a/src/pkg/client.py
+++ b/src/pkg/client.py
@@ -14,7 +14,7 @@
-from mcp.server.fastmcp import FastMCP
+from mcp.server.mcpserver import MCPServer as FastMCP
"""

_MALFORMED_DIFF = "I fixed the bug, trust me. No diff headers here.\njust prose."

_CLIENT_PY = "src/pkg/client.py"


# -- parse_diff ----------------------------------------------------------


def test_parse_diff_extracts_file_list() -> None:
    patch = parse_diff(_GOOD_DIFF)
    assert patch.files == [_CLIENT_PY]
    assert patch.diff == _GOOD_DIFF


def test_parse_diff_handles_plain_unified_diff_without_git_header() -> None:
    """A bare `---`/`+++` pair, with no `diff --git` header, must parse too."""
    patch = parse_diff(_PLAIN_UNIFIED_DIFF)
    assert patch.files == [_CLIENT_PY]


def test_parse_diff_multi_file() -> None:
    patch = parse_diff(_MULTI_FILE_DIFF)
    assert patch.files == [_CLIENT_PY, "tests/test_server.py"]


def test_parse_diff_malformed_does_not_raise() -> None:
    """No recognisable headers -> empty file list, not an exception."""
    patch = parse_diff(_MALFORMED_DIFF)
    assert patch.files == []
    assert patch.diff == _MALFORMED_DIFF


# -- validate_patch --------------------------------------------------------


def test_validate_patch_rejects_test_file_edit() -> None:
    patch = parse_diff(_TEST_FILE_DIFF)
    ok, reason = validate_patch(patch, allowed_files=["tests/test_server.py"])
    assert ok is False
    assert "test" in reason.lower()
    assert "tests/test_server.py" in reason


def test_validate_patch_rejects_test_file_even_when_other_files_are_allowed() -> None:
    """A patch that touches an allowed file AND a test file is still rejected."""
    patch = parse_diff(_MULTI_FILE_DIFF)
    allowed = [_CLIENT_PY, "tests/test_server.py"]
    ok, reason = validate_patch(patch, allowed_files=allowed)
    assert ok is False
    assert "tests/test_server.py" in reason


def test_validate_patch_rejects_file_outside_blast_radius() -> None:
    patch = parse_diff(_OUTSIDE_RADIUS_DIFF)
    ok, reason = validate_patch(patch, allowed_files=[_CLIENT_PY])
    assert ok is False
    assert "unrelated.py" in reason


def test_validate_patch_accepts_allowed_non_test_file() -> None:
    patch = parse_diff(_GOOD_DIFF)
    ok, reason = validate_patch(patch, allowed_files=[_CLIENT_PY])
    assert ok is True
    assert isinstance(reason, str) and reason


def test_validate_patch_rejects_empty_file_list_cleanly() -> None:
    """A malformed diff fails validation, not with an exception."""
    patch = parse_diff(_MALFORMED_DIFF)
    ok, reason = validate_patch(patch, allowed_files=[_CLIENT_PY])
    assert ok is False
    assert isinstance(reason, str) and reason
