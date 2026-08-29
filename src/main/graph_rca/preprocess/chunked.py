"""Chunked preprocessing — multiprocessing parallel log parsing + dedup."""
from __future__ import annotations

import os
import re
from multiprocessing import Pool, cpu_count
from pathlib import Path

from ..models import LogEntry, StackTrace, StackFrame, WalkablePath
from ..config import DomainConfig
from .parser import parse_log_entries


def preprocess_chunked(file_path: str, config: DomainConfig, workers: int = None) -> list[LogEntry]:
    """Parse large log file in parallel chunks, dedup results. Returns raw entries (no resolution)."""
    file_path = str(Path(file_path).resolve())
    workers = workers or min(cpu_count(), 8)

    entry_start = re.compile(config.log_format.entry_start)
    boundaries = _find_chunk_boundaries(file_path, workers, entry_start)

    config_dict = _config_to_dict(config)
    tasks = [(file_path, boundaries[i], boundaries[i+1], config_dict, i)
             for i in range(len(boundaries)-1)]

    with Pool(processes=workers) as pool:
        chunk_results = pool.map(_process_chunk, tasks)

    entries = [_rebuild_entry(d) for d in [e for chunk in chunk_results for e in chunk]]
    return _dedup_entries(entries)


def _find_chunk_boundaries(file_path: str, n_chunks: int, entry_start: re.Pattern) -> list[int]:
    """Find byte offsets where chunks start, aligned to entry boundaries."""
    file_size = os.path.getsize(file_path)
    chunk_size = file_size // n_chunks
    boundaries = [0]

    with open(file_path, "rb") as f:
        for i in range(1, n_chunks):
            f.seek(chunk_size * i)
            f.readline()  # skip partial line
            while True:
                pos = f.tell()
                line = f.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                if entry_start.match(text):
                    boundaries.append(pos)
                    break

    boundaries.append(file_size)
    return boundaries


def _process_chunk(args: tuple) -> list[dict]:
    """Worker: parse + filter a chunk. Returns list of dicts (picklable)."""
    file_path, start, end, config_dict, chunk_index = args
    config = _config_from_dict(config_dict)

    with open(file_path, "rb") as f:
        f.seek(start)
        text = f.read(end - start).decode("utf-8", errors="replace")

    entries = parse_log_entries(text, config)

    # Known errors filter
    if config.known_errors:
        known_pats = [re.compile(ke["pattern"]) for ke in config.known_errors if "pattern" in ke]
        entries = [e for e in entries if not (e.is_error and any(p.search(e.raw_text) for p in known_pats))]

    # Serialize for cross-process transfer
    return [_entry_to_dict(e) for e in entries]


def _entry_to_dict(e: LogEntry) -> dict:
    st_text = None
    if e.stack_trace:
        parts = [f"{e.stack_trace.exception}: {e.stack_trace.message}"]
        for f in e.stack_trace.frames:
            parts.append(f"\tat {f.class_name}.{f.method}({f.file}:{f.line})")
        st_text = "\n".join(parts)

    return {
        "line_number": e.line_number, "raw_text": e.raw_text,
        "level": e.level, "timestamp": e.timestamp,
        "static_text": e.static_text, "dynamic_values": e.dynamic_values,
        "service": e.service, "thread_id": e.thread_id,
        "stack_trace_text": st_text, "is_error": e.is_error, "is_framework": e.is_framework,
    }


def _rebuild_entry(d: dict) -> LogEntry:
    st = None
    if d["stack_trace_text"]:
        lines = d["stack_trace_text"].split("\n")
        exc_parts = lines[0].split(": ", 1) if lines else ["", ""]
        frames = []
        for l in lines[1:]:
            m = re.match(r"\s*at\s+([\w.$]+)\.([\w<>]+)\(([^:]+):(\d+)\)", l)
            if m:
                frames.append(StackFrame(m.group(1), m.group(2), m.group(3), int(m.group(4))))
        st = StackTrace(exception=exc_parts[0], message=exc_parts[1] if len(exc_parts) > 1 else "", frames=frames)

    return LogEntry(
        line_number=d["line_number"], line_end=d["line_number"],
        raw_text=d["raw_text"], level=d["level"], timestamp=d["timestamp"],
        static_text=d["static_text"], dynamic_values=d["dynamic_values"],
        service=d["service"], thread_id=d["thread_id"],
        stack_trace=st, is_error=d["is_error"], is_framework=d["is_framework"],
    )


def _dedup_entries(entries: list[LogEntry]) -> list[LogEntry]:
    """Deduplicate INFO/DEBUG by fuzzy signature with repeat_count. ERRORs never deduped."""
    _strip = re.compile(
        r'[0-9a-fA-F]{4,}|\d{4}-\d{2}-\d{2}[T_][\d:.]+Z?|\d+|"[^"]*"|\'[^\']*\'|\s+')
    seen: dict[str, LogEntry] = {}
    result = []
    _preserve_levels = {"ERROR", "FATAL", "SEVERE", "WARN"}
    for e in entries:
        if e.level in _preserve_levels:
            result.append(e)
            continue
        sig = _strip.sub(' ', e.static_text).strip()
        if sig not in seen:
            seen[sig] = e
            result.append(e)
        else:
            seen[sig].repeat_count += 1
    return result


def _config_to_dict(config: DomainConfig) -> dict:
    return {
        "repo": config.repo, "language": config.language,
        "service_name": config.service_name, "ignore_patterns": config.ignore_patterns,
        "known_errors": config.known_errors, "error_markers": config.error_markers,
        "entry_points": config.entry_points,
        "log_format": {
            "type": config.log_format.type, "entry_start": config.log_format.entry_start,
            "line_pattern": config.log_format.line_pattern, "alt_patterns": config.log_format.alt_patterns,
            "message_separators": config.log_format.message_separators,
            "continuation_patterns": config.log_format.continuation_patterns,
            "group_by_thread": config.log_format.group_by_thread,
            "thread_field": config.log_format.thread_field, "error_levels": config.log_format.error_levels,
        },
        "stack_trace": {
            "format": config.stack_trace.format, "frame_pattern": config.stack_trace.frame_pattern,
            "caused_by_pattern": config.stack_trace.caused_by_pattern,
            "exception_pattern": config.stack_trace.exception_pattern,
        },
    }


def _config_from_dict(d: dict) -> DomainConfig:
    from ..config import DomainConfig, LogFormat, StackTraceConfig
    return DomainConfig(
        repo=d.get("repo", ""), branch=d.get("branch", ""), language=d.get("language"),
        service_name=d.get("service_name"), ignore_patterns=d.get("ignore_patterns", []),
        known_errors=d.get("known_errors", []), error_markers=d.get("error_markers", []),
        entry_points=d.get("entry_points", []),
        log_format=LogFormat.from_dict(d.get("log_format", {})),
        stack_trace=StackTraceConfig.from_dict(d.get("stack_trace", {})),
    )
