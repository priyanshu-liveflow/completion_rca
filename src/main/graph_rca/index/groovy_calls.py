"""Supplement CALLS edges for Groovy-specific patterns not captured by tree-sitter.

Adds edges for:
1. Property access: obj.field → obj.getField() / obj.setField()
2. Inner class method → outer class method calls (builder patterns)
"""
from __future__ import annotations

from src.main.code_tools import get_graph
from src.main.shared.logging import get_logger

log = get_logger("groovy_calls")


def supplement_groovy_calls(repo: str) -> dict:
    """Add synthetic CALLS edges for Groovy property access and inner class patterns."""
    g = get_graph()
    edges_added = 0

    # 1. Property access: find functions whose source references `obj.fieldName`
    #    where getFieldName or setFieldName exists in the same class
    edges_added += _add_property_access_edges(g, repo)

    # 2. Inner class → outer class: methods in inner classes that call outer class methods
    edges_added += _add_inner_class_edges(g, repo)

    # 3. Orphan methods: functions with 0 callers — find cross-file source references
    edges_added += _add_orphan_method_edges(g, repo)

    log.info("groovy_supplement_done", edges_added=edges_added)
    return {"edges_added": edges_added}


def _add_property_access_edges(g, repo: str) -> int:
    """For each getter/setter, find functions that use the property form and add CALLS edge."""
    # Find all getters/setters in the repo
    result = g.query(
        "MATCH (f:Function) WHERE f.path CONTAINS $repo AND "
        "(f.name STARTS WITH 'get' OR f.name STARTS WITH 'set') AND size(f.name) > 3 "
        "RETURN f.name, id(f)",
        params={"repo": repo}
    )
    if not result.result_set:
        return 0

    edges = 0
    for row in result.result_set:
        method_name = row[0]  # e.g. getProvisioningComments
        method_id = row[1]
        # Derive property name: getProvisioningComments → provisioningComments
        prefix_len = 3  # "get" or "set"
        prop_name = method_name[prefix_len:]
        if not prop_name:
            continue
        prop_name = prop_name[0].lower() + prop_name[1:]  # lowercase first char

        # Find functions that contain this property name in their source (but aren't the getter/setter itself)
        callers = g.query(
            "MATCH (caller:Function) WHERE caller.path CONTAINS $repo "
            "AND caller.source CONTAINS $prop AND id(caller) <> $mid "
            "AND NOT (caller)-[:CALLS]->(:Function {name: $mname}) "
            "RETURN id(caller) LIMIT 20",
            params={"repo": repo, "prop": prop_name, "mid": method_id, "mname": method_name}
        )
        if not callers.result_set:
            continue

        for caller_row in callers.result_set:
            caller_id = caller_row[0]
            try:
                g.query(
                    "MATCH (a:Function), (b:Function) WHERE id(a) = $cid AND id(b) = $mid "
                    "MERGE (a)-[:CALLS {synthetic: true, reason: 'groovy_property'}]->(b)",
                    params={"cid": caller_id, "mid": method_id}
                )
                edges += 1
            except Exception:
                pass

    return edges


def _add_inner_class_edges(g, repo: str) -> int:
    """Find inner class methods calling outer class methods and add CALLS edges."""
    # Find classes that have inner classes (same file, different class nodes)
    # Approach: find functions in the same file where one calls another by name in source
    # but no CALLS edge exists — specifically for builder patterns

    # Find builder-pattern methods (withX, build) that reference other methods in source
    result = g.query(
        "MATCH (f:Function) WHERE f.path CONTAINS $repo "
        "AND (f.name STARTS WITH 'with' OR f.name = 'build') "
        "AND f.source IS NOT NULL "
        "RETURN f.name, f.source, f.path, id(f)",
        params={"repo": repo}
    )
    if not result.result_set:
        return 0

    edges = 0
    for row in result.result_set:
        fname, source, fpath, fid = row[0], row[1], row[2], row[3]
        if not source:
            continue

        # Find method calls in the source (pattern: .methodName( for builder chains, or obj.methodName()
        import re
        calls_in_source = re.findall(r'\.(\w+)\s*\(', source)

        for called_name in set(calls_in_source):
            if called_name == fname or called_name[0].isupper():
                continue  # skip constructors and self
            # Check if this function exists in the same file
            target = g.query(
                "MATCH (t:Function {name: $name}) WHERE t.path = $path "
                "AND NOT (:Function {name: $caller})-[:CALLS]->(t) "
                "RETURN id(t) LIMIT 1",
                params={"name": called_name, "path": fpath, "caller": fname}
            )
            if target.result_set:
                tid = target.result_set[0][0]
                try:
                    g.query(
                        "MATCH (a:Function), (b:Function) WHERE id(a) = $fid AND id(b) = $tid "
                        "MERGE (a)-[:CALLS {synthetic: true, reason: 'inner_class'}]->(b)",
                        params={"fid": fid, "tid": tid}
                    )
                    edges += 1
                except Exception:
                    pass

    return edges


def _add_orphan_method_edges(g, repo: str) -> int:
    """For functions with 0 incoming CALLS edges, find source references across the repo."""
    # Find functions with no callers (orphans) — non-trivial names, not getters/setters
    result = g.query(
        "MATCH (f:Function) WHERE f.path CONTAINS $repo "
        "AND NOT (:Function)-[:CALLS]->(f) "
        "AND size(f.name) > 5 "
        "AND NOT f.name STARTS WITH 'get' AND NOT f.name STARTS WITH 'set' "
        "RETURN f.name, id(f)",
        params={"repo": repo}
    )
    if not result.result_set:
        return 0

    # Process all orphans — FalkorDB handles source CONTAINS efficiently
    orphans = [(row[0], row[1]) for row in result.result_set]

    edges = 0
    for fname, fid in orphans[:3000]:
        pattern = f".{fname}("
        callers = g.query(
            "MATCH (caller:Function) WHERE caller.path CONTAINS $repo "
            "AND caller.source CONTAINS $pattern AND id(caller) <> $fid "
            "RETURN id(caller) LIMIT 10",
            params={"repo": repo, "pattern": pattern, "fid": fid}
        )
        if not callers.result_set:
            continue
        for caller_row in callers.result_set:
            try:
                g.query(
                    "MATCH (a:Function), (b:Function) WHERE id(a) = $cid AND id(b) = $fid "
                    "MERGE (a)-[:CALLS {synthetic: true, reason: 'orphan_grep'}]->(b)",
                    params={"cid": caller_row[0], "fid": fid}
                )
                edges += 1
            except Exception:
                pass

    return edges
