"""Class-based resolution — logger class extraction, framework detection from config."""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict

from ..config import DomainConfig
from ..index.flow_extractor import load_patterns

_func_logs_cache: dict[str, dict[int, list[str]]] = {}


def _get_func_logs_cached(repo: str) -> dict[int, list[str]]:
    """Load first-fragment templates grouped by fid from trie cache."""
    if repo in _func_logs_cache:
        return _func_logs_cache[repo]
    from ..store import load_trie_data
    by_fid: dict[int, list[str]] = defaultdict(list)
    for row in load_trie_data(repo):
        by_fid[row[2]].append(row[0][0] if row[0] else "")
    _func_logs_cache[repo] = dict(by_fid)
    return _func_logs_cache[repo]


def extract_logger_class(raw_text: str, config: DomainConfig = None) -> str | None:
    """Extract logger class name from log line using config's line_pattern."""
    if not config:
        return None
    first_line = raw_text.split('\n')[0]
    lf = config.log_format
    patterns = []
    if lf.line_pattern:
        patterns.append(lf.line_pattern)
    patterns.extend(lf.alt_patterns)
    for pattern in patterns:
        m = re.match(pattern, first_line)
        if m:
            fields = {k: v for k, v in m.groupdict().items() if v is not None}
            if "logger" in fields:
                return fields["logger"]
            break
    m = re.search(r'\]\s+([\w.$]+)\s+:', raw_text)
    return m.group(1) if m else None


def find_by_class(graph, logger_class: str, repo_path: str, message: str = "") -> list[tuple[str, int]]:
    """Resolve logger class to functions. Returns [(qualified_name, fid)]."""
    repo_name = repo_path.split("/")[-1]
    parts = logger_class.split('.')
    class_name = parts[-1] if parts else logger_class

    result = graph.query(
        'MATCH (c:Class)-[:CONTAINS]->(f:Function) '
        'WHERE c.path CONTAINS $repo AND c.name = $class_name '
        'RETURN c.name + "." + f.name, f.name, f.source, id(f)',
        params={"repo": repo_name, "class_name": class_name}
    )
    if not result.result_set and len(parts) > 2:
        suffix = '.'.join(parts[-2:])
        result = graph.query(
            'MATCH (c:Class)-[:CONTAINS]->(f:Function) '
            'WHERE c.path CONTAINS $repo AND c.qualified_name ENDS WITH $suffix '
            'RETURN c.name + "." + f.name, f.name, f.source, id(f)',
            params={"repo": repo_name, "suffix": suffix}
        )
    if not result.result_set:
        return []

    if message:
        msg_lower = message.lower()
        # Prefer longest function name match to avoid 'createRequest' beating 'createRequestFinalStep'
        name_matches = [(row[0], row[3], len(row[1])) for row in result.result_set if row[1].lower() in msg_lower]
        if name_matches:
            name_matches.sort(key=lambda x: x[2], reverse=True)
            # Verify: does the winning function's templates actually match the message?
            # If not, check if a sibling function's templates DO match
            winner_fid = name_matches[0][1]
            func_logs = _get_func_logs_cached(repo_name)
            winner_templates = func_logs.get(winner_fid, [])
            if winner_templates and any(t and len(t) > 3 and t in message for t in winner_templates):
                return [(name_matches[0][0], name_matches[0][1])]
            # Winner's templates don't match — check all siblings by template
            for row in result.result_set:
                fid = row[3]
                templates = func_logs.get(fid, [])
                if any(t and len(t) > 5 and t in message for t in templates):
                    return [(row[0], fid)]
            # No template match — fall back to longest name match
            return [(name_matches[0][0], name_matches[0][1])]

    if message:
        msg_fragment = message.strip().lstrip('- ').split('---')[0].split(':')[0].strip()[:40]
        if len(msg_fragment) > 5:
            for row in result.result_set:
                if row[2] and msg_fragment in row[2]:
                    return [(row[0], row[3])]

        # Last resort: check all functions' log templates
        func_logs = _get_func_logs_cached(repo_name)
        for row in result.result_set:
            fid = row[3]
            templates = func_logs.get(fid, [])
            if any(t and len(t) > 5 and t in message for t in templates):
                return [(row[0], fid)]

    return []


def is_framework_log(text: str, language: str = None, extra_markers: list[str] = None) -> bool:
    """Check if log text is from a framework. Markers loaded from YAML config."""
    markers = []

    # Load from language YAML
    if language:
        patterns = load_patterns(language)
        markers.extend(patterns.framework_markers)

    # Add repo-specific extras (from DomainConfig)
    if extra_markers:
        markers.extend(extra_markers)

    if not markers:
        return False

    text_lower = text.lower()
    return any(m.lower() in text_lower for m in markers)
