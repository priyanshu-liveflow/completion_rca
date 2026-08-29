"""Stack trace parsing — Java, Python, Go, Rust, PowerShell."""
from __future__ import annotations

import re

from ..models import StackTrace, StackFrame
from ..config import DomainConfig

STACK_PATTERNS = {
    "java": {
        "frame": re.compile(r'^\s*at\s+(?:[\w.]+/)?([\w.$]+)\.([\w<>]+)\(([^:]+):(\d+)\)'),
        "caused_by": re.compile(r'^Caused by:\s+([\w.$]+):\s*(.*)'),
        "exception": re.compile(r'^([\w.$]+(?:Exception|Error|Throwable)):\s*(.*)'),
        "more": re.compile(r'^\s*\.\.\.\s+(\d+)\s+more'),
    },
    "python": {
        "frame": re.compile(r'^\s+File\s+"([^"]+)",\s+line\s+(\d+),\s+in\s+(\w+)'),
        "exception": re.compile(r'^(\w+(?:Error|Exception)):\s*(.*)'),
    },
}


def parse_stack_trace(lines: list[str], config: DomainConfig) -> StackTrace | None:
    """Parse stack trace from continuation lines."""
    language = config.language or "java"
    st_cfg = config.stack_trace

    if st_cfg.frame_pattern:
        patterns = {"frame": re.compile(st_cfg.frame_pattern),
                    "caused_by": re.compile(st_cfg.caused_by_pattern) if st_cfg.caused_by_pattern else None,
                    "exception": re.compile(st_cfg.exception_pattern) if st_cfg.exception_pattern else None}
    else:
        patterns = STACK_PATTERNS.get(language)

    if not patterns:
        return None

    if language in ("java", "groovy"):
        return _parse_java(lines, patterns)
    elif language == "python":
        return _parse_python(lines, patterns)
    return None


def _parse_java(lines: list[str], patterns: dict) -> StackTrace | None:
    frames, caused_by = [], []
    exception, message = "", ""
    frame_pat = patterns.get("frame")
    exc_pat = patterns.get("exception")
    caused_by_pat = patterns.get("caused_by")

    if not frame_pat:
        return None

    i = 0
    if i < len(lines) and exc_pat:
        m = exc_pat.match(lines[i])
        if m:
            exception, message = m.group(1), m.group(2)
            i += 1

    while i < len(lines):
        line = lines[i]
        m = frame_pat.match(line)
        if m:
            frames.append(StackFrame(class_name=m.group(1), method=m.group(2),
                                    file=m.group(3) if m.lastindex >= 3 else "",
                                    line=int(m.group(4)) if m.lastindex >= 4 else 0))
            i += 1
            continue
        if caused_by_pat:
            m = caused_by_pat.match(line)
            if m:
                sub = _parse_java(lines[i+1:], patterns)
                if sub:
                    sub.exception, sub.message = m.group(1), m.group(2)
                    caused_by.append(sub)
                break
        i += 1

    if not frames and not exception:
        return None
    return StackTrace(exception=exception, message=message, frames=frames, caused_by=caused_by)


def _parse_python(lines: list[str], patterns: dict) -> StackTrace | None:
    frames = []
    exception, message = "", ""
    frame_pat = patterns.get("frame")
    exc_pat = patterns.get("exception")

    for line in lines:
        if frame_pat:
            m = frame_pat.match(line)
            if m:
                frames.append(StackFrame(class_name=m.group(1), method=m.group(3) if m.lastindex >= 3 else "unknown",
                                        file=m.group(1), line=int(m.group(2))))
                continue
        if exc_pat:
            m = exc_pat.match(line)
            if m:
                exception, message = m.group(1), m.group(2)

    if not frames and not exception:
        return None
    return StackTrace(exception=exception, message=message, frames=frames)
