"""Repair the hunk headers in a machine-written diff.

Pure: no I/O. Takes the diff and the current contents of the files it names,
and returns a diff `git apply` will accept.

Models reliably get the *edit* right and the *bookkeeping* wrong. A typical
reply carries `@@` with no line numbers at all, or `@@ -1,3 +1,3 @@` when the
hunk is at line 40. `git apply` rejects both — the first as "patch with only
garbage", which reads like a corrupt response rather than a header the model
could not have known, since nothing in the prompt tells it where in the file
the function starts. `--recount` does not help: it recomputes counts but
still requires a parseable start line.

So the start line is recovered the only way it can be: by finding where the
hunk's own context and removed lines actually occur in the file. That is
information we have and the model does not, which makes this a translation
rather than a guess. A hunk whose context cannot be found is left untouched,
so the patch fails loudly in `git apply` instead of being applied somewhere
wrong.
"""

from __future__ import annotations

import re

__all__ = ["normalize_hunk_headers"]

_FILE_HEADER = re.compile(r"^\+\+\+ (?:b/)?(?P<path>\S+)")
_HUNK = re.compile(r"^@@")


def _old_side(body: list[str]) -> list[str]:
    """The lines this hunk expects to already be in the file."""
    return [line[1:] for line in body if line[:1] in (" ", "-")]


def _new_count(body: list[str]) -> int:
    return sum(1 for line in body if line[:1] in (" ", "+"))


def _find_start(haystack: list[str], needle: list[str]) -> int | None:
    """1-based line where `needle` occurs in `haystack`, or None.

    Compares with trailing whitespace stripped: a model that reflows a blank
    line is still describing the same location, and refusing the match would
    reject a correct patch over invisible characters.
    """
    if not needle:
        return None
    trimmed = [line.rstrip() for line in haystack]
    target = [line.rstrip() for line in needle]
    limit = len(trimmed) - len(target)
    matches = [i for i in range(limit + 1) if trimmed[i : i + len(target)] == target]
    # Exactly one match, or the location is ambiguous and guessing which one
    # the model meant is how a patch lands in the wrong place.
    return matches[0] + 1 if len(matches) == 1 else None


def normalize_hunk_headers(diff: str, sources: dict[str, str]) -> str:
    """Rewrite each hunk header to the position its context actually occupies.

    `sources` maps the diff's own paths (as they appear after `+++ b/`) to the
    file's current text. A path absent from `sources`, or a hunk whose context
    is missing or ambiguous, is passed through unchanged.
    """
    if not diff.strip():
        return diff

    lines = diff.splitlines()
    out: list[str] = []
    path: str | None = None
    index = 0

    while index < len(lines):
        line = lines[index]

        header = _FILE_HEADER.match(line)
        if header is not None:
            path = header.group("path")
            out.append(line)
            index += 1
            continue

        if not _HUNK.match(line):
            out.append(line)
            index += 1
            continue

        # Collect the hunk body: everything until the next hunk or file header.
        body_start = index + 1
        cursor = body_start
        while cursor < len(lines):
            nxt = lines[cursor]
            if _HUNK.match(nxt) or nxt.startswith(("diff --git ", "--- ", "+++ ")):
                break
            if nxt[:1] not in (" ", "+", "-", "\\", ""):
                break
            cursor += 1
        body = lines[body_start:cursor]

        source = sources.get(path or "")
        start = (
            _find_start(source.splitlines(), _old_side(body))
            if source is not None
            else None
        )

        if start is None:
            out.append(line)
        else:
            old = len(_old_side(body))
            new = _new_count(body)
            out.append(f"@@ -{start},{old} +{start},{new} @@")

        out.extend(body)
        index = cursor

    return "\n".join(out) + ("\n" if diff.endswith("\n") else "")
