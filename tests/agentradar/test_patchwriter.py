"""Tests for turning a model's reply into a diff. No provider, no network."""

from __future__ import annotations

from src.main.agentradar.adapters.patchwriter import build_prompt, extract_diff
from src.main.agentradar.core.remediation import RemediationRequest

DIFF = """\
diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1,2 +1,2 @@
-    return None
+    return 1"""


def _request() -> RemediationRequest:
    return RemediationRequest(
        finding_title="target returns None",
        finding_body="it should return 1",
        file_path="src/a.py",
        function_name="target",
        source="def target():\n    return None\n",
        failing_tests=["tests/test_a.py::test_one"],
        failure_excerpt="AssertionError",
        allowed_files=["src/a.py"],
    )


def test_a_bare_diff_survives_unchanged() -> None:
    assert extract_diff(DIFF).startswith("diff --git a/src/a.py")


def test_a_trailing_newline_is_added() -> None:
    """`git apply` rejects a patch with no final newline, as if it were corrupt."""
    assert extract_diff(DIFF).endswith("\n")


def test_code_fences_are_stripped() -> None:
    assert "```" not in extract_diff(f"```diff\n{DIFF}\n```")


def test_prose_before_the_diff_is_discarded() -> None:
    out = extract_diff(f"Sure! Here is the patch you asked for:\n\n{DIFF}")
    assert out.startswith("diff --git")
    assert "Sure!" not in out


def test_a_plain_diff_without_the_git_header_is_accepted() -> None:
    plain = "--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-a\n+b"
    assert extract_diff(plain).startswith("--- a/src/a.py")


def test_a_reply_with_no_diff_yields_empty_not_garbage() -> None:
    """An empty string becomes an ordinary rejection downstream, not a crash."""
    assert extract_diff("I cannot fix this safely.") == ""
    assert extract_diff("") == ""


def test_prompt_names_the_allowed_files_and_failing_tests() -> None:
    prompt = build_prompt(_request())
    assert "src/a.py" in prompt
    assert "tests/test_a.py::test_one" in prompt
    assert "target returns None" in prompt


def test_prompt_truncates_a_huge_source_body() -> None:
    request = RemediationRequest(**{**_request().__dict__, "source": "x" * 50_000})
    assert len(build_prompt(request, max_source_chars=100)) < 5_000
