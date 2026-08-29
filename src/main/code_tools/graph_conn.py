"""Single FalkorDB graph connection — replaces graph_rca/graph.py and tools/code.py::_graph()."""

import os

_graph_instance = None

# codegraphcontext moved to FalkorDB Lite, which is embedded rather than a
# standalone server. The unix socket is created by a `codegraphcontext.core
# .falkor_worker` process and exists only while one is running — `cgc api
# start`, `cgc query`, or the MCP server. We connect to that socket; we cannot
# create it, because `falkordblite` ships in the cgc tool environment, not in
# this project's dependencies.
DEFAULT_SOCKET_PATH = "~/.codegraphcontext/global/db/falkordb.sock"

_UNAVAILABLE = (
    "No FalkorDB Lite worker is listening on {sock}.\n"
    "FalkorDB Lite is embedded: the socket exists only while a codegraphcontext "
    "process owns it.\n"
    "Start one and leave it running:  cgc api start\n"
    "Then confirm the graph is indexed:  cgc query 'MATCH (f:Function) RETURN count(f)'\n"
    "Override the socket location with FALKORDB_SOCKET_PATH if yours differs."
)


class GraphUnavailable(RuntimeError):
    """No FalkorDB worker is listening. Actionable, unlike a raw ConnectionError."""


def socket_path():
    """Socket to connect on. FALKORDB_SOCKET_PATH wins, matching cgc's own .env."""
    return os.path.expanduser(os.getenv("FALKORDB_SOCKET_PATH") or DEFAULT_SOCKET_PATH)


def get_graph():
    """Get cached FalkorDB graph connection.

    Raises GraphUnavailable when no worker is listening. A stale socket file
    left behind by a dead worker fails the same way as a missing one, so this
    pings rather than trusting os.path.exists.
    """
    global _graph_instance
    if _graph_instance is None:
        from falkordb import FalkorDB
        sock = socket_path()
        try:
            db = FalkorDB(unix_socket_path=sock)
            db.connection.ping()
        except Exception as e:
            raise GraphUnavailable(_UNAVAILABLE.format(sock=sock)) from e
        _graph_instance = db.select_graph("codegraph")
    return _graph_instance


def reset_graph():
    """Drop the cached connection so the next call reconnects."""
    global _graph_instance
    _graph_instance = None


def query(cypher: str, params: dict = None) -> list:
    """Execute Cypher query. Returns list of rows or [{"error": ...}]."""
    try:
        g = get_graph()
        result = g.query(cypher, params=params) if params else g.query(cypher)
        return [list(r) for r in result.result_set] if result.result_set else []
    except Exception as e:
        return [{"error": str(e)}]


def repair_has_method_edges(repo: str) -> int:
    """Fix missing HAS_METHOD edges where Class and Function share the same file path.

    codegraphcontext's Groovy parser creates Class + Function nodes but doesn't
    always create the relationship between them. This patches it post-index.
    Returns number of edges created.
    """
    g = get_graph()
    result = g.query(
        "MATCH (c:Class), (f:Function) "
        "WHERE c.path CONTAINS $repo AND f.path = c.path "
        "AND NOT (c)-[:HAS_METHOD]->(f) "
        "CREATE (c)-[:HAS_METHOD]->(f) "
        "RETURN count(f) AS created",
        params={"repo": repo},
    )
    if result.result_set:
        return result.result_set[0][0]
    return 0


def resolve_cross_file_calls(repo: str) -> int:
    """Create cross-file CALLS edges for Groovy DI using INJECTS edges as type resolver.

    For each function with a flow graph containing call nodes with a receiver (e.g. "workflowService.createRequest"),
    checks if the enclosing class INJECTS a class with that field name, then creates a CALLS edge
    from the caller function to the target method in the injected class.

    Returns number of edges created.
    """
    import json
    g = get_graph()

    # Build field_name → injected_class lookup from INJECTS edges
    injects = g.query(
        "MATCH (a:Class)-[r:INJECTS]->(b:Class) "
        "WHERE a.path CONTAINS $repo "
        "RETURN a.name, r.field_name, b.name",
        params={"repo": repo},
    )
    field_type_map = {}
    for row in (injects.result_set or []):
        injector, field, injected = row
        if field:
            field_type_map[(injector, field)] = injected

    if not field_type_map:
        return 0

    # Get all functions with flow graphs
    result = g.query(
        "MATCH (f:Function) WHERE f.path CONTAINS $repo "
        "AND f.exec_flow IS NOT NULL AND f.class_context IS NOT NULL "
        "RETURN id(f), f.name, f.class_context, f.exec_flow",
        params={"repo": repo},
    )

    created = 0
    for row in (result.result_set or []):
        fid, fname, class_ctx, flow_json = row
        if not flow_json or not class_ctx:
            continue
        try:
            flow = json.loads(flow_json)
        except Exception:
            continue

        for node in flow.get("nodes", []):
            if node.get("type") != "call" or "." not in node.get("call_target", ""):
                continue
            receiver, method = node["call_target"].split(".", 1)
            injected_class = field_type_map.get((class_ctx, receiver))
            if not injected_class:
                continue
            try:
                r = g.query(
                    "MATCH (caller:Function) WHERE id(caller) = $fid "
                    "MATCH (callee:Function {name: $method})-[:CONTAINS*0..1]-(c:Class {name: $cls}) "
                    "WHERE callee.path CONTAINS $repo "
                    "MERGE (caller)-[:CALLS {cross_file: true, via_inject: $receiver}]->(callee) "
                    "RETURN count(*)",
                    params={"fid": fid, "method": method, "cls": injected_class, "receiver": receiver, "repo": repo},
                )
                if r.result_set and r.result_set[0][0] > 0:
                    created += 1
            except Exception:
                pass

    return created
