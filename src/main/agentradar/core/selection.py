"""Graph-guided test selection. Pure: a graph Protocol in, a TestSelection out.

Two strategies, both measured against the real index before this module was
written (see `docs/demo-repo.md`), and both shipped:

* `CALLS` — recursive callers of a contact point. Reaches **zero** tests for an
  import-shaped break, because nothing *calls* an import. It is not dead code:
  a changed signature needs it, and 56 of the demo repo's 61 tests do reach
  source functions through `CALLS`.
* `IMPORTS` — transitive importers with dot-boundary prefix matching. Reaches
  exactly the two test modules that actually error, out of five.

A real dependency release produces both shapes, so `select_tests` runs both and
unions them.

`IMPORTS` edges run file to module-*name* string, and those name nodes are
leaves: `test_server.py -IMPORTS-> "intervals_mcp_server.tools"` does not
connect to any file node, so a transitive Cypher walk dies after one hop. The
name-to-file join is done here, in pure code.

The `CodeGraph` Protocol below is declared in `core/` rather than imported from
`adapters/`, because rule 1 forbids the import. `FalkorCodeGraph` satisfies it
structurally. Rows are dicts so core stays free of adapter types:

* `callers_of` -> `{"name", "fid", "file_path", "class_name"}`. The path is what
  separates a test caller from a source caller; without it every real caller
  fails `is_test_node` and the CALLS strategy silently selects nothing.
* `import_edges` -> `{"file_path", "imported"}`, every IMPORTS edge in the repo.
  183 of them for the demo repo, so one fetch beats a query per hop.
* `functions_in` -> `{"name", "fid", "file_path", "class_name"}`.

`class_name` is load-bearing. The graph stores method names bare and puts
ownership on a separate `Class-CONTAINS->Function` edge, so a test method inside
a class would otherwise be emitted as `path::test_method` — which pytest cannot
run. `file_path` is repo-relative on every row.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from src.main.agentradar.contracts.evidence import TestSelection
from src.main.agentradar.contracts.impact import ContactPoint

Strategy = Literal["callers", "imports", "path", "manual"]


@runtime_checkable
class CodeGraph(Protocol):
    """The slice of the code graph that selection needs. No FalkorDB here."""

    def callers_of(
        self, fid: int, repo: str, limit: int = 25
    ) -> list[dict[str, Any]]: ...

    def import_edges(self, repo: str) -> list[dict[str, Any]]: ...

    def functions_in(self, file_path: str, repo: str) -> list[dict[str, Any]]: ...


def _parts(path: str) -> list[str]:
    """Path segments, separator-normalised and free of `.` noise."""
    cleaned = path.replace("\\", "/").strip("/")
    return [part for part in cleaned.split("/") if part and part != "."]


def module_name_for(file_path: str, source_root: str) -> str:
    """`'src/pkg/api/client.py'` to `'pkg.api.client'`.

    `__init__.py` resolves to the package itself, so
    `module_name_for('src/pkg/tools/__init__.py', 'src')` is `'pkg.tools'`.
    A `source_root` that does not prefix the path is left alone — test files
    live outside it and still need a name.
    """
    parts = _parts(file_path)
    root = _parts(source_root)
    if root and parts[: len(root)] == root:
        parts = parts[len(root) :]
    if not parts:
        return ""
    last = parts[-1]
    if last.endswith(".py"):
        last = last[: -len(".py")]
    parts = parts[:-1] if last == "__init__" else [*parts[:-1], last]
    return ".".join(part for part in parts if part)


def module_matches(imported: str, target: str) -> bool:
    """True when `imported` is `target` or a dot-boundary prefix of it.

    `module_matches('pkg.api', 'pkg.api.client')` is True — that boundary is
    what catches a test importing the package a changed module lives in.
    `module_matches('pkg.apiclient', 'pkg.api.client')` is False; naive
    `startswith` would call it a match and drag in unrelated modules.
    """
    if not imported or not target:
        return False
    return imported == target or target.startswith(f"{imported}.")


def is_test_node(name: str, file_path: str, test_root: str) -> bool:
    """A node is a test when it sits under `test_root` and is named `test_*`.

    Both halves are load-bearing: the graph indexes a `<module>` node per file,
    and module nodes under `tests/` are not runnable pytest targets.
    """
    if not name.startswith("test_"):
        return False
    return test_root in _parts(file_path)[:-1]


def to_node_ids(functions: list[dict[str, Any]]) -> list[str]:
    """Graph nodes to pytest node ids: `'path::name'`, or `'path::Class::name'`.

    A test method inside a class needs the class segment. The graph stores
    method names bare and hangs ownership off a separate edge, so dropping
    `class_name` yields an id that pytest cannot resolve — it would fail in the
    sandbox, several minutes later, looking like a broken test rather than a
    broken selector.

    Rows without both a path and a name are dropped for the same reason.
    """
    ids: list[str] = []
    for row in functions:
        path = str(row.get("file_path") or "")
        name = str(row.get("name") or "")
        if not (path and name):
            continue
        owner = str(row.get("class_name") or "")
        ids.append(f"{path}::{owner}::{name}" if owner else f"{path}::{name}")
    return ids


def _ordered(found: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows sorted by fid, so two runs of the same graph agree on stage."""
    return [found[fid] for fid in sorted(found)]


def _reached_from(rows: list[dict[str, Any]]) -> list[str]:
    """Contact-point *function names* that reached these rows.

    Function names, not file paths, because that is what the contract says
    `TestSelection.reached_from` holds — and both walks must agree, or a union
    mixes two identifier namespaces and correlates back to nothing. For an
    import-shaped break these are mostly `<module>` nodes, since the contact
    point is a module-level import; `ContactPoint.file_path` is where a
    consumer gets the file.

    Every contributing contact point is kept, not just the first to arrive: two
    of them routinely share one module.
    """
    names: set[str] = set()
    for row in rows:
        names.update(row.get("origins") or ())
    return sorted(names - {""})


def _tests_in_files(
    graph: CodeGraph,
    files: dict[str, set[str]],
    repo: str,
    test_root: str,
) -> dict[int, dict[str, Any]]:
    """Test functions inside `files`, keyed by fid. `files` maps path to origins."""
    found: dict[int, dict[str, Any]] = {}
    for path in sorted(files):
        for row in graph.functions_in(path, repo):
            fid = row.get("fid")
            name = str(row.get("name") or "")
            node_path = str(row.get("file_path") or path)
            if fid is None or not is_test_node(name, node_path, test_root):
                continue
            existing = found.get(int(fid))
            if existing is not None:
                existing["origins"].update(files[path])
                continue
            found[int(fid)] = {
                "name": name,
                "fid": int(fid),
                "file_path": node_path,
                "class_name": row.get("class_name"),
                "origins": set(files[path]),
            }
    return found


def _callers_walk(
    graph: CodeGraph,
    contact_points: list[ContactPoint],
    repo: str,
    max_depth: int,
    test_root: str,
) -> list[dict[str, Any]]:
    """BFS up CALLS from every contact point. Cycle-safe, depth-limited."""
    origins: dict[int, set[str]] = {}
    for point in sorted(contact_points, key=lambda p: (p.fid, p.function_name)):
        origins.setdefault(point.fid, set()).add(point.function_name)

    visited = set(origins)
    frontier = sorted(origins)
    found: dict[int, dict[str, Any]] = {}

    for _ in range(max_depth):
        if not frontier:
            break
        following: list[int] = []
        for fid in frontier:
            for row in graph.callers_of(fid, repo):
                raw = row.get("fid")
                if raw is None:
                    continue
                caller = int(raw)
                if caller in visited:
                    continue
                visited.add(caller)
                following.append(caller)
                origins.setdefault(caller, set()).update(origins.get(fid, set()))
                name = str(row.get("name") or "")
                path = str(row.get("file_path") or "")
                if is_test_node(name, path, test_root):
                    found.setdefault(
                        caller,
                        {
                            "name": name,
                            "fid": caller,
                            "file_path": path,
                            "class_name": row.get("class_name"),
                            "origins": set(origins[caller]),
                        },
                    )
        frontier = sorted(following)
    return _ordered(found)


def _imports_walk(
    graph: CodeGraph,
    contact_points: list[ContactPoint],
    repo: str,
    max_depth: int,
    test_root: str,
    source_root: str,
) -> list[dict[str, Any]]:
    """Transitive IMPORTS walk, then the name-to-file join. Five steps.

    1. Contact points give the touched files.
    2. Each file gives its importable module name.
    3. Importers whose imported name matches on a dot boundary are reached.
    4. Newly reached files re-enter the frontier as module names.
    5. Reached files under `test_root` give up their `test_*` functions.
    """
    edges = sorted(
        (str(edge.get("file_path") or ""), str(edge.get("imported") or ""))
        for edge in graph.import_edges(repo)
    )

    frontier: dict[str, set[str]] = {}
    for point in sorted(contact_points, key=lambda p: (p.file_path, p.fid)):
        if not point.file_path:
            continue
        name = module_name_for(point.file_path, source_root)
        if name:
            frontier.setdefault(name, set()).add(point.function_name)

    seen_modules = set(frontier)
    reached: dict[str, set[str]] = {}

    for _ in range(max_depth):
        if not frontier:
            break
        following: dict[str, set[str]] = {}
        for importer, imported in edges:
            if not importer or importer in reached:
                continue
            matched: set[str] = set()
            for module, sources in frontier.items():
                if module_matches(imported, module):
                    matched.update(sources)
            if not matched:
                continue
            reached[importer] = matched
            name = module_name_for(importer, source_root)
            if name and name not in seen_modules:
                seen_modules.add(name)
                following.setdefault(name, set()).update(matched)
        frontier = following

    test_files = {
        path: sources
        for path, sources in reached.items()
        if test_root in _parts(path)[:-1]
    }
    return _ordered(_tests_in_files(graph, test_files, repo, test_root))


def select_tests_by_callers(
    graph: CodeGraph,
    contact_points: list[ContactPoint],
    repo: str,
    *,
    max_depth: int = 4,
    test_root: str = "tests",
) -> TestSelection:
    """BFS up CALLS edges from each contact point; collect test functions.

    Reaches nothing for an import-shaped break — that is a property of the
    break, not a bug, and it is why `select_tests` also walks IMPORTS.
    """
    rows = _callers_walk(graph, contact_points, repo, max_depth, test_root)
    return TestSelection(
        tests=to_node_ids(rows),
        strategy="callers",
        reached_from=_reached_from(rows),
    )


def select_tests_by_imports(
    graph: CodeGraph,
    contact_points: list[ContactPoint],
    repo: str,
    *,
    max_depth: int = 4,
    test_root: str = "tests",
    source_root: str = "src",
) -> TestSelection:
    """Transitive IMPORTS walk with dot-boundary prefix matching."""
    rows = _imports_walk(graph, contact_points, repo, max_depth, test_root, source_root)
    return TestSelection(
        tests=to_node_ids(rows),
        strategy="imports",
        reached_from=_reached_from(rows),
    )


def select_tests_by_path(
    contact_points: list[ContactPoint], repo_files: list[str], test_root: str
) -> TestSelection:
    """Last resort: tests whose path mirrors a touched module. No graph needed.

    Two conventions, both weak, which is why this never runs inside
    `select_tests`: a shared package directory, or a `test_<stem>.py` mirror of
    a touched file. Entries are bare file paths — pytest accepts those as node
    ids just as it accepts `path::name`.
    """
    touched_dirs: set[str] = set()
    touched_stems: set[str] = set()
    for point in contact_points:
        parts = _parts(point.file_path)
        if not parts:
            continue
        touched_dirs.update(parts[:-1])
        touched_stems.add(parts[-1].removesuffix(".py"))

    selected: dict[str, str] = {}
    for path in sorted(set(repo_files)):
        parts = _parts(path)
        if len(parts) < 2 or test_root not in parts[:-1]:
            continue
        stem = parts[-1].removesuffix(".py")
        mirrored = stem.removeprefix("test_").removesuffix("_test")
        shared = touched_dirs.intersection(parts[:-1]) - {test_root}
        if shared or mirrored in touched_stems:
            selected[path] = sorted(shared)[0] if shared else mirrored

    return TestSelection(
        tests=sorted(selected),
        strategy="path",
        reached_from=sorted(set(selected.values())),
    )


def _strategy_that_fired(
    callers: list[dict[str, Any]], imports: list[dict[str, Any]]
) -> Strategy:
    """Which walk produced the union. Never a silent fallback.

    `TestSelection.strategy` is a single value and the contract is frozen, so a
    union that both walks fed is reported as whichever contributed more, ties
    going to `callers` because "this test calls the changed code" is stronger
    evidence than "this test imports the module it lives in". Run the two
    `select_tests_by_*` functions directly for the full breakdown.

    An empty union reports `manual`: the graph chose nothing, so anything that
    runs has to be chosen by a human. Saying `imports` there would claim a walk
    succeeded when it found nothing.
    """
    if not callers and not imports:
        return "manual"
    if callers and len(callers) >= len(imports):
        return "callers"
    return "imports"


def select_tests(
    graph: CodeGraph,
    contact_points: list[ContactPoint],
    repo: str,
    *,
    max_depth: int = 4,
    max_tests: int = 12,
    test_root: str = "tests",
    source_root: str = "src",
) -> TestSelection:
    """Union of the callers walk and the imports walk, recording which fired."""
    callers = _callers_walk(graph, contact_points, repo, max_depth, test_root)
    imports = _imports_walk(
        graph, contact_points, repo, max_depth, test_root, source_root
    )

    merged: dict[int, dict[str, Any]] = {}
    for row in [*callers, *imports]:
        fid = int(row["fid"])
        existing = merged.get(fid)
        if existing is None:
            merged[fid] = dict(row, origins=set(row.get("origins") or ()))
        else:
            # A test both walks reached was reached from both sets of contact
            # points. Keeping only the first would under-report provenance.
            existing["origins"].update(row.get("origins") or ())
    rows = _ordered(merged)

    # A negative limit would slice from the end and quietly return almost
    # everything. Clamp: asking for fewer than zero tests means zero.
    limit = max(0, max_tests)
    truncated = len(rows) > limit
    kept = rows[:limit]
    return TestSelection(
        tests=to_node_ids(kept),
        strategy=_strategy_that_fired(callers, imports),
        reached_from=_reached_from(kept),
        truncated=truncated,
    )
