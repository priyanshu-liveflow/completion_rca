"""Template scanner — extracts LogTemplate nodes from function source."""
from __future__ import annotations

import re

from src.main.shared.logging import get_logger

log = get_logger("template_scanner")

_extractors: dict[str, object] = {}


def _get_extractor(lang: str):
    """Get cached FlowExtractor instance for log detection."""
    if lang not in _extractors:
        from .flow_extractor import FlowExtractor, load_patterns
        _extractors[lang] = FlowExtractor(load_patterns(lang), lang)
    return _extractors[lang]


def scan_templates(source: str, fid: int, repo: str, lang: str, graph) -> int:
    """Scan source lines for log calls and create LogTemplate nodes. Returns count."""
    extractor = _get_extractor(lang)
    count = 0
    for line_idx, line in enumerate(source.split('\n')):
        level, text, frags = extractor._detect_log(line)
        if level and frags and len(''.join(frags)) >= 3:
            st = ''.join(frags)
            regex = '.*'.join(re.escape(f) for f in frags)
            try:
                graph.query(
                    "MATCH (f:Function) WHERE id(f) = $fid "
                    "CREATE (lt:LogTemplate {"
                    "  static_text: $st, static_fragments: $frags,"
                    "  log_level: $level, line_in_function: $line,"
                    "  regex_pattern: $regex, repo_path: $repo"
                    "})-[:EMITTED_BY]->(f)",
                    params={"fid": fid, "st": st, "frags": frags,
                            "level": level, "line": line_idx + 1,
                            "regex": regex, "repo": repo},
                )
                count += 1
            except Exception:
                pass
    return count


def index_orphan_closures(repo: str, graph, lang: str = "groovy") -> int:
    """Index log templates from classes that have 0 functions (closure-only Grails controllers).

    Reads source files directly, finds def x = { } closure blocks, and creates
    Function + LogTemplate nodes for each.
    """
    import os
    result = graph.query(
        "MATCH (c:Class) WHERE c.path CONTAINS $repo "
        "OPTIONAL MATCH (c)-[:CONTAINS]->(f:Function) "
        "WITH c, count(f) as func_count WHERE func_count = 0 "
        "RETURN c.name, c.path, id(c)",
        params={"repo": repo},
    )
    if not result.result_set:
        return 0

    extractor = _get_extractor(lang)
    closure_pat = re.compile(r'^\s*def\s+(\w+)\s*=\s*\{')
    template_count = 0

    for row in result.result_set:
        class_name, class_path, class_id = row
        if not class_path or not os.path.exists(class_path):
            continue

        try:
            with open(class_path) as f:
                lines = f.readlines()
        except Exception:
            continue

        i = 0
        while i < len(lines):
            m = closure_pat.match(lines[i])
            if m:
                func_name = m.group(1)
                start_i = i
                depth = 0
                for j in range(i, len(lines)):
                    clean = re.sub(r'"[^"]*"', '', lines[j])
                    clean = re.sub(r"'[^']*'", '', clean)
                    depth += clean.count('{') - clean.count('}')
                    if depth == 0 and j > i:
                        closure_src = ''.join(lines[start_i:j + 1])
                        try:
                            graph.query(
                                "MATCH (c:Class) WHERE id(c) = $cid "
                                "CREATE (c)-[:CONTAINS]->(f:Function {name: $name, path: $path, "
                                "start_line: $start, source: $src})",
                                params={"cid": class_id, "name": func_name,
                                        "path": class_path, "start": start_i + 1,
                                        "src": closure_src},
                            )
                        except Exception:
                            pass

                        r = graph.query(
                            "MATCH (f:Function {name: $name, path: $path, start_line: $start}) "
                            "RETURN id(f)",
                            params={"name": func_name, "path": class_path, "start": start_i + 1},
                        )
                        if not r.result_set:
                            break

                        fid = r.result_set[0][0]
                        for line_idx in range(start_i, j + 1):
                            level, text, frags = extractor._detect_log(lines[line_idx])
                            if level and frags and len(''.join(frags)) >= 3:
                                st = ''.join(frags)
                                regex_pat = '.*'.join(re.escape(frag) for frag in frags)
                                try:
                                    graph.query(
                                        "MATCH (f:Function) WHERE id(f) = $fid "
                                        "CREATE (lt:LogTemplate {"
                                        "  static_text: $st, static_fragments: $frags,"
                                        "  log_level: $level, line_in_function: $line,"
                                        "  regex_pattern: $regex, repo_path: $repo"
                                        "})-[:EMITTED_BY]->(f)",
                                        params={"fid": fid, "st": st, "frags": frags,
                                                "level": level, "line": line_idx - start_i + 1,
                                                "regex": regex_pat, "repo": repo},
                                    )
                                    template_count += 1
                                except Exception:
                                    pass
                        break
                i = j + 1 if depth == 0 else i + 1
            else:
                i += 1

    if template_count > 0:
        log.info("orphan_closures_indexed", templates=template_count)
    return template_count
