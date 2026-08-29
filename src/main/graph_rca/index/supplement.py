"""Function boundary detection — finds end of functions via brace/indent counting."""
from __future__ import annotations

import re

from .flow_extractor import load_patterns


def _find_function_end(lines: list[str], start: int, language: str) -> int:
    """Find end of function based on language block style."""
    fp = load_patterns(language)
    if fp.block_style == "indent":
        return _find_python_end(lines, start)
    return _find_brace_end(lines, start)


def _find_brace_end(lines: list[str], start: int) -> int:
    """Find end of brace-delimited function. Simple depth counter — first depth=0 after opening.
    Strips content between quotes and neutralizes char-literal braces before counting."""
    depth = 0
    found_open = False

    for i in range(start, len(lines)):
        # Remove content inside quotes (handles "{" in strings)
        line = re.sub(r'"[^"]*"', '', lines[i])
        line = re.sub(r"'[^']*'", '', line)
        for ch in line:
            if ch == '{':
                depth += 1
                found_open = True
            elif ch == '}':
                depth -= 1
                if found_open and depth == 0:
                    return i + 1

    return start + 1  # fallback


def _find_python_end(lines: list[str], start: int) -> int:
    """Find end of indent-delimited function."""
    if start + 1 >= len(lines):
        return start + 1
    # Detect indent of first body line
    body_start = start + 1
    while body_start < len(lines) and not lines[body_start].strip():
        body_start += 1
    if body_start >= len(lines):
        return start + 1
    body_indent = len(lines[body_start]) - len(lines[body_start].lstrip())
    if body_indent == 0:
        return start + 1

    for i in range(body_start + 1, min(start + 3000, len(lines))):
        line = lines[i]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent < body_indent:
            return i
    return len(lines)
