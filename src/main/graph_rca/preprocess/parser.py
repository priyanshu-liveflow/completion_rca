"""Log parser — structured entry extraction from raw log text."""
from __future__ import annotations

import re

from ..models import LogEntry
from ..config import DomainConfig
from .stack_trace import parse_stack_trace


def parse_log_entries(log_text: str, config: DomainConfig) -> list[LogEntry]:
    """Parse raw log text into structured entries."""
    lines = log_text.split('\n')
    entry_start = re.compile(config.entry_start)
    ignore_patterns = [re.compile(p) for p in config.ignore_patterns]
    cont_pats = [re.compile(p) for p in config.log_format.continuation_patterns] if config.log_format.continuation_patterns else []

    entries: list[LogEntry] = []
    current_lines: list[str] = []
    current_start: int = 0

    for i, line in enumerate(lines):
        is_cont = current_lines and cont_pats and any(p.match(line) for p in cont_pats)

        if entry_start.match(line) and current_lines and not is_cont:
            entry = _build_entry(current_lines, current_start, config)
            if entry and not _should_ignore(entry.raw_text, ignore_patterns):
                entries.append(entry)
            current_lines = [line]
            current_start = i + 1
        else:
            current_lines.append(line)
            if not current_lines:
                current_start = i + 1

    if current_lines:
        entry = _build_entry(current_lines, current_start, config)
        if entry and not _should_ignore(entry.raw_text, ignore_patterns):
            entries.append(entry)

    return entries


def _build_entry(lines: list[str], start_line: int, config: DomainConfig) -> LogEntry | None:
    if not lines:
        return None
    raw = '\n'.join(lines)
    first = lines[0]

    fields = _extract_fields(first, config)
    level = fields.get("level", _extract_level(first)).lower()
    ts = fields.get("timestamp")
    thread_id = fields.get(config.log_format.thread_field)
    message = fields.get("message") or _extract_message(first, config)

    stack_trace = None
    if len(lines) > 1:
        # Strip entry_start prefix from continuation lines (e.g. K8s timestamp)
        entry_start_re = re.compile(config.entry_start) if config else None
        cont_lines = []
        for l in lines[1:]:
            if entry_start_re:
                m = entry_start_re.match(l)
                cont_lines.append(l[m.end():] if m else l)
            else:
                cont_lines.append(l)
        stack_trace = parse_stack_trace(cont_lines, config)

    is_error = level in config.log_format.error_levels or (
        config.error_markers and any(re.search(p, raw) for p in [re.compile(m) for m in config.error_markers]))

    return LogEntry(
        line_number=start_line, line_end=start_line + len(lines) - 1,
        raw_text=raw, level=level, timestamp=ts,
        static_text=message, dynamic_values=[],
        service=config.service_name, thread_id=thread_id,
        stack_trace=stack_trace, is_error=is_error)


def _extract_fields(line: str, config: DomainConfig) -> dict[str, str]:
    lf = config.log_format
    if lf.type == "json":
        import json as _json
        try:
            obj = _json.loads(line)
            return {k: str(obj[v]) for k, v in lf.field_map.items() if v in obj}
        except (ValueError, KeyError):
            return {}
    patterns = ([lf.line_pattern] if lf.line_pattern else []) + lf.alt_patterns
    for pat in patterns:
        m = re.match(pat, line)
        if m:
            return {k: v for k, v in m.groupdict().items() if v is not None}
    return {}


def _extract_level(line: str) -> str:
    m = re.search(r'\b(TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|CRITICAL)\b', line, re.IGNORECASE)
    return m.group(1).lower().replace("warning", "warn") if m else "info"


def _extract_message(line: str, config: DomainConfig) -> str:
    seps = config.log_format.message_separators if config else [' : ', ' - ']
    bracket_end = line.rfind(']')
    if bracket_end > 0:
        for sep in seps:
            idx = line.find(sep, bracket_end)
            if idx > 0:
                return line[idx + len(sep):].strip()
    for sep in seps:
        idx = line.find(sep, 20)
        if idx > 0:
            return line[idx + len(sep):].strip()
    m = re.match(config.entry_start, line)
    return line[m.end():].strip() if m else line.strip()


def _should_ignore(text: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(text) for p in patterns)
