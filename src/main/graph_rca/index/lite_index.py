"""Lite Log Index — extracts log templates using patterns from flow YAML configs."""
from __future__ import annotations

import re

from ..models import LogTemplate, DynamicPart
from .flow_extractor import load_patterns
from src.main.shared.logging import get_logger

log = get_logger("lite_index")


def _extract_fragments(log_content: str, language: str) -> tuple[list[str], list[DynamicPart]]:
    """Extract static fragments from log string based on language interpolation rules."""
    # Groovy GString: ${var} or $var
    if language in ("groovy",) and ('${' in log_content or '$' in log_content):
        if '${' in log_content:
            parts = re.split(r'\$\{[^}]*\}', log_content)
            frags = [p for p in parts if p.strip()]
            dyns = [DynamicPart(variable=m.group(1), position=i)
                    for i, m in enumerate(re.finditer(r'\$\{([^}]*)\}', log_content))]
            return frags, dyns
        parts = re.split(r'\$[\w.]+', log_content)
        frags = [p for p in parts if p.strip()]
        if frags:
            dyns = [DynamicPart(variable=m.group(0)[1:], position=i)
                    for i, m in enumerate(re.finditer(r'\$([\w.]+)', log_content))]
            return frags, dyns

    # Python f-string: {var}
    if language == "python" and log_content.startswith(('f"', "f'")):
        inner = log_content[2:-1]
        parts = re.split(r'\{[^}]+\}', inner)
        frags = [p for p in parts if p]
        dyns = [DynamicPart(variable=m.group(1), position=i)
                for i, m in enumerate(re.finditer(r'\{([^}]+)\}', inner))]
        return frags, dyns

    # SLF4J {} placeholders (Java, Kotlin)
    if '{}' in log_content:
        parts = log_content.split('{}')
        return [p for p in parts if p], []

    # printf-style %s %d (Java, Go, C)
    if re.search(r'%[sdflxvqweEgG]', log_content):
        parts = re.split(r'%[-+0-9*.]*[sdflxvqweEgGoO]', log_content)
        return [p for p in parts if p], []

    # Rust/JS format: {name} or {0}
    if language in ("rust", "javascript", "typescript") and re.search(r'\{[^}]*\}', log_content):
        parts = re.split(r'\{[^}]*\}', log_content)
        return [p for p in parts if p], []

    # Concatenation: "text" + var + "more"
    if '+' in log_content and '"' in log_content:
        parts = re.split(r'\"\s*\+\s*|\s*\+\s*\"', log_content)
        frags = [p.strip().strip('"') for p in parts if p.strip().strip('"')]
        return frags, []

    # Plain string
    cleaned = log_content.strip('"').strip("'")
    return [cleaned] if cleaned else [], []


def extract_log_templates(source: str, language: str) -> list[LogTemplate]:
    """Extract log templates from function source using YAML-configured patterns."""
    if not source:
        return []

    patterns = load_patterns(language)
    if not patterns.log_calls:
        return []

    templates = []
    lines = source.split('\n')

    for line_idx, line in enumerate(lines):
        for pattern in patterns.log_calls:
            match = pattern.search(line)
            if not match:
                continue

            level = match.group(1).lower() if match.lastindex else "info"

            # Gather full statement (handle multi-line)
            full_stmt = line[match.end():]
            if line_idx + 1 < len(lines) and not full_stmt.rstrip().endswith((');', ')')):
                for next_line in lines[line_idx + 1:min(line_idx + 4, len(lines))]:
                    full_stmt += ' ' + next_line.strip()
                    if ');' in next_line or next_line.rstrip().endswith(')'):
                        break

            # Extract quoted string
            str_match = re.search(r'"([^"]*(?:"[^"]*)*[^"]*)"', full_stmt)
            if not str_match:
                str_match = re.search(r"'([^']*)'", full_stmt)
            if not str_match:
                continue

            log_content = str_match.group(1)
            frags, dyns = _extract_fragments(log_content, language)
            if not frags:
                continue

            regex = '.*'.join(re.escape(f) for f in frags)
            templates.append(LogTemplate(
                static_text=''.join(frags), static_fragments=frags,
                log_level=level, line_in_function=line_idx + 1,
                dynamic_parts=dyns, regex_pattern=regex,
            ))
            break
    return templates



