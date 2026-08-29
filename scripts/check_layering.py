"""Enforce AgentRadar layering and the Bright Data network rule.

Zero dependencies, stdlib only. Exits non-zero with the offending file:line.

1. `src/main/agentradar/core/` may not import `adapters` or `mcp`.
2. `requests`, `httpx`, `urllib.request`, `aiohttp`, and subprocess
   invocations of `curl`/`wget` are forbidden outside
   `src/main/agentradar/adapters/brightdata.py`.

Inherited `graph_rca` modules already use `httpx` for local Ollama. They
are allowlisted so this check does not rewrite history. New code under
`src/` or `tests/` is not.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src" / "main" / "agentradar" / "core"
BRIGHTDATA = (ROOT / "src" / "main" / "agentradar" / "adapters" / "brightdata.py").resolve()

# Pre-existing graph_rca HTTP clients. Do not grow this list.
_INHERITED_NETWORK_PREFIXES = (
    ROOT / "src" / "main" / "graph_rca",
    ROOT / "src" / "main" / "shared",
    ROOT / "src" / "main" / "code_tools",
    ROOT / "src" / "main" / "config",
    ROOT / "src" / "main" / "cli.py",
    ROOT / "tests" / "graph_rca",
)

_NETWORK_MODULES = frozenset({"requests", "httpx", "aiohttp", "urllib.request"})
_SUBPROCESS_FNS = frozenset({"run", "call", "Popen", "check_output", "check_call"})
_SHELL_BINS = frozenset({"curl", "wget"})


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _is_inherited_network_path(path: Path) -> bool:
    resolved = path.resolve()
    for prefix in _INHERITED_NETWORK_PREFIXES:
        prefix = prefix.resolve()
        if resolved == prefix or prefix in resolved.parents:
            return True
    return False


def _iter_py(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root] if root.suffix == ".py" else []
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def _imported_modules(node: ast.AST) -> list[str]:
    names: list[str] = []
    if isinstance(node, ast.Import):
        names.extend(alias.name for alias in node.names)
    elif isinstance(node, ast.ImportFrom):
        base = node.module or ""
        if base:
            names.append(base)
        for alias in node.names:
            if alias.name == "*":
                continue
            names.append(f"{base}.{alias.name}" if base else alias.name)
    return names


def _names_layer(mod: str) -> bool:
    parts = mod.split(".")
    return "adapters" in parts or "mcp" in parts


def _is_network_module(mod: str) -> bool:
    if mod in _NETWORK_MODULES:
        return True
    return any(mod == banned or mod.startswith(f"{banned}.") for banned in _NETWORK_MODULES)


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _first_shell_bin(node: ast.AST) -> str | None:
    text = _const_str(node)
    if text is not None:
        first = text.split()[0].rsplit("/", 1)[-1] if text.split() else ""
        return first if first in _SHELL_BINS else None
    if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
        first = _const_str(node.elts[0])
        if first is None:
            return None
        return first.rsplit("/", 1)[-1] if first.rsplit("/", 1)[-1] in _SHELL_BINS else None
    return None


def _is_subprocess_call(node: ast.Call, subprocess_aliases: set[str], bound_fns: set[str]) -> bool:
    func = node.func
    if isinstance(func, ast.Name) and func.id in bound_fns:
        return True
    if isinstance(func, ast.Attribute) and func.attr in _SUBPROCESS_FNS:
        if isinstance(func.value, ast.Name) and func.value.id in subprocess_aliases:
            return True
    return False


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        line = exc.lineno or 1
        print(f"{_rel(path)}:{line}: syntax error: {exc.msg}", file=sys.stderr)
        return None


def check_core(path: Path, tree: ast.AST) -> list[str]:
    """Return violations of the core-must-not-import-adapters/mcp rule."""
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for mod in _imported_modules(node):
            if _names_layer(mod):
                hits.append(f"{_rel(path)}:{node.lineno}: core imports {mod!r}")
    return hits


def check_network(path: Path, tree: ast.AST) -> list[str]:
    """Return Bright Data rule violations in one file."""
    if path.resolve() == BRIGHTDATA:
        return []
    if _is_inherited_network_path(path):
        return []

    hits: list[str] = []
    subprocess_aliases: set[str] = set()
    bound_fns: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for mod in _imported_modules(node):
                if _is_network_module(mod):
                    hits.append(f"{_rel(path)}:{node.lineno}: network import {mod!r}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "subprocess" or alias.name.startswith("subprocess."):
                        subprocess_aliases.add(alias.asname or alias.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom) and (node.module or "") == "subprocess":
                for alias in node.names:
                    if alias.name in _SUBPROCESS_FNS:
                        bound_fns.add(alias.asname or alias.name)

        if isinstance(node, ast.Call) and _is_subprocess_call(node, subprocess_aliases, bound_fns):
            if node.args:
                bin_name = _first_shell_bin(node.args[0])
                if bin_name is not None:
                    hits.append(
                        f"{_rel(path)}:{node.lineno}: subprocess invokes {bin_name!r}"
                    )
    return hits


def main() -> int:
    """Run both layering checks. Print OK: layering clean on success."""
    violations: list[str] = []
    parse_failed = False

    for path in _iter_py(CORE):
        tree = _parse(path)
        if tree is None:
            parse_failed = True
            continue
        violations.extend(check_core(path, tree))

    for root in (ROOT / "src", ROOT / "tests"):
        for path in _iter_py(root):
            tree = _parse(path)
            if tree is None:
                parse_failed = True
                continue
            violations.extend(check_network(path, tree))

    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    if parse_failed:
        return 1
    print("OK: layering clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
