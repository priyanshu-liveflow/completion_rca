"""Tests for repairing machine-written hunk headers. Pure, no git, no model."""

from __future__ import annotations

from src.main.agentradar.core.diffnorm import normalize_hunk_headers

SOURCE = '''\
import os


def unrelated():
    return os.getcwd()


def discount(price, percent):
    """Reduce price."""
    return price * (percent / 100)
'''

BARE = """\
diff --git a/billing.py b/billing.py
--- a/billing.py
+++ b/billing.py
@@
 def discount(price, percent):
     \"\"\"Reduce price.\"\"\"
-    return price * (percent / 100)
+    return price - (price * (percent / 100))
"""


def test_a_bare_header_gets_the_real_line_number() -> None:
    """The function starts at line 8, which the model had no way to know."""
    out = normalize_hunk_headers(BARE, {"billing.py": SOURCE})
    assert "@@ -8,3 +8,3 @@" in out
    assert "\n@@\n" not in out


def test_a_wrong_header_is_corrected_not_trusted() -> None:
    wrong = BARE.replace("@@\n", "@@ -1,3 +1,3 @@\n")
    out = normalize_hunk_headers(wrong, {"billing.py": SOURCE})
    assert "@@ -8,3 +8,3 @@" in out


def test_the_body_is_never_altered() -> None:
    out = normalize_hunk_headers(BARE, {"billing.py": SOURCE})
    assert "-    return price * (percent / 100)" in out
    assert "+    return price - (price * (percent / 100))" in out


def test_counts_reflect_added_and_removed_lines() -> None:
    diff = """\
diff --git a/billing.py b/billing.py
--- a/billing.py
+++ b/billing.py
@@
 def discount(price, percent):
-    \"\"\"Reduce price.\"\"\"
-    return price * (percent / 100)
+    return price - (price * (percent / 100))
+
+
+def extra():
+    return 1
"""
    out = normalize_hunk_headers(diff, {"billing.py": SOURCE})
    # three old lines (one context, two removed), six new (one context, five added)
    assert "@@ -8,3 +8,6 @@" in out


def test_an_unknown_file_passes_through_untouched() -> None:
    """Better a loud `git apply` failure than a patch placed by guesswork."""
    out = normalize_hunk_headers(BARE, {})
    assert "@@\n" in out


def test_ambiguous_context_is_left_alone() -> None:
    """Two identical candidate locations: picking one is how a patch lands wrong."""
    source = "def f():\n    pass\n\n\ndef g():\n    pass\n"
    diff = """\
--- a/m.py
+++ b/m.py
@@
     pass
"""
    assert "@@\n" in normalize_hunk_headers(diff, {"m.py": source})


def test_trailing_whitespace_does_not_block_a_match() -> None:
    diff = BARE.replace(
        "-    return price * (percent / 100)",
        "-    return price * (percent / 100)   ",
    )
    assert "@@ -8,3 +8,3 @@" in normalize_hunk_headers(diff, {"billing.py": SOURCE})


def test_an_empty_diff_is_returned_unchanged() -> None:
    assert normalize_hunk_headers("", {}) == ""
    assert normalize_hunk_headers("   ", {}) == "   "


def test_multiple_files_are_each_located_separately() -> None:
    other = "def helper():\n    return 2\n"
    diff = """\
diff --git a/billing.py b/billing.py
--- a/billing.py
+++ b/billing.py
@@
 def discount(price, percent):
     \"\"\"Reduce price.\"\"\"
-    return price * (percent / 100)
+    return price - (price * (percent / 100))
diff --git a/other.py b/other.py
--- a/other.py
+++ b/other.py
@@
 def helper():
-    return 2
+    return 3
"""
    out = normalize_hunk_headers(diff, {"billing.py": SOURCE, "other.py": other})
    assert "@@ -8,3 +8,3 @@" in out
    assert "@@ -1,2 +1,2 @@" in out
