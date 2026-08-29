"""Build a :class:`Watchlist` from dependency manifest files.

Pure. Uses stdlib :mod:`tomllib` and :mod:`packaging` for PEP 508 / PEP 440.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import PurePosixPath
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from ..contracts.dependency import Dependency, Watchlist

__all__ = [
    "detect_and_parse",
    "from_pyproject",
    "from_requirements",
    "is_newer",
]

_SKIP_NAMES = frozenset({"python", "python_version"})
_INLINE_COMMENT = re.compile(r"\s+#")
_HASH_OPTION = re.compile(r"\s--hash=\S+")


def is_newer(current: str, candidate: str) -> bool:
    """Return True when ``candidate`` is newer than ``current`` (PEP 440)."""
    try:
        return Version(candidate) > Version(current)
    except InvalidVersion as exc:
        raise ValueError(f"invalid version: {exc}") from exc


def _dep_key(name: str) -> str:
    return canonicalize_name(name)


def _pinned_version(spec: str) -> str | None:
    """Extract a concrete ``==`` pin, excluding wildcard-compatible releases."""
    try:
        requirement = Requirement(spec)
    except InvalidRequirement:
        return None
    if len(requirement.specifier) != 1:
        return None
    item = next(iter(requirement.specifier))
    if item.operator != "==" or item.version.endswith(".*"):
        return None
    try:
        Version(item.version)
    except InvalidVersion:
        return None
    return item.version


def _dependency_from_spec(spec: str, *, source: str) -> Dependency | None:
    """Parse one PEP 508 string into a :class:`Dependency`, or ``None`` to skip."""
    stripped = spec.strip()
    if not stripped or stripped.startswith("#"):
        return None
    try:
        requirement = Requirement(stripped)
    except InvalidRequirement:
        return None
    if _dep_key(requirement.name) in _SKIP_NAMES:
        return None
    return Dependency(
        name=requirement.name,
        current_spec=stripped,
        current_version=_pinned_version(stripped),
        source=source,
    )


def _format_poetry_extras(extras: Any) -> str:
    if not isinstance(extras, list) or not extras:
        return ""
    return "[" + ",".join(str(extra) for extra in extras) + "]"


def _poetry_spec(name: str, value: Any) -> str | None:
    if isinstance(value, str):
        constraint = value.strip()
        return f"{name}{constraint}" if constraint else None
    if not isinstance(value, dict):
        return None

    extras = _format_poetry_extras(value.get("extras"))
    raw_version = value.get("version")
    if isinstance(raw_version, str) and raw_version.strip():
        return f"{name}{extras}{raw_version.strip()}"

    if isinstance(value.get("git"), str):
        ref = value.get("rev") or value.get("tag") or value.get("branch") or "HEAD"
        return f"{name}{extras} @ git+{value['git']}@{ref}"
    if isinstance(value.get("path"), str):
        return f"{name}{extras} @ file:{value['path']}"
    if isinstance(value.get("url"), str):
        return f"{name}{extras} @ {value['url']}"
    return None


def _dependency_from_poetry(name: str, spec: str, *, source: str) -> Dependency | None:
    if _dep_key(name) in _SKIP_NAMES:
        return None
    candidates = [spec]
    if not spec.startswith(name):
        candidates.extend((f"{name}{spec}", f"{name} {spec}"))
    for candidate in candidates:
        dep = _dependency_from_spec(candidate, source=source)
        if dep is not None:
            return dep
    return Dependency(
        name=name,
        current_spec=spec,
        current_version=None,
        source=source,
    )


def _append(
    deps: dict[str, Dependency],
    order: list[str],
    dep: Dependency | None,
) -> None:
    if dep is None:
        return
    key = _dep_key(dep.name)
    if key in deps:
        return
    deps[key] = dep
    order.append(key)


def _merge(
    deps: dict[str, Dependency],
    order: list[str],
    items: list[str],
    *,
    source: str,
) -> None:
    for item in items:
        _append(deps, order, _dependency_from_spec(item, source=source))


def _merge_poetry(
    deps: dict[str, Dependency],
    order: list[str],
    table: dict[str, Any],
    *,
    source: str,
) -> None:
    for name, value in table.items():
        spec = _poetry_spec(name, value)
        if spec is None:
            continue
        _append(deps, order, _dependency_from_poetry(name, spec, source=source))


def _expand_group_entries(
    groups: dict[str, Any],
    entries: list[Any],
    *,
    visiting: frozenset[str],
) -> list[str]:
    """Expand PEP 735 ``{include-group = ...}`` entries recursively."""
    specs: list[str] = []
    for item in entries:
        if isinstance(item, dict):
            include = item.get("include-group")
            if isinstance(include, str):
                if include in visiting:
                    raise ValueError(f"cycle in dependency-groups: {include!r}")
                nested = groups.get(include)
                if isinstance(nested, list):
                    specs.extend(
                        _expand_group_entries(
                            groups,
                            nested,
                            visiting=visiting | {include},
                        )
                    )
                continue
        if isinstance(item, str):
            specs.append(item)
    return specs


def from_pyproject(text: str, repo: str) -> Watchlist:
    """Parse ``pyproject.toml`` text into a :class:`Watchlist`."""
    data = tomllib.loads(text)
    deps: dict[str, Dependency] = {}
    order: list[str] = []
    source = "pyproject.toml"

    project = data.get("project")
    if isinstance(project, dict):
        raw = project.get("dependencies")
        if isinstance(raw, list):
            _merge(deps, order, [str(item) for item in raw], source=source)

    groups = data.get("dependency-groups")
    if isinstance(groups, dict):
        group_source = f"{source}:dependency-groups"
        for group_deps in groups.values():
            if isinstance(group_deps, list):
                expanded = _expand_group_entries(
                    groups,
                    group_deps,
                    visiting=frozenset(),
                )
                _merge(deps, order, expanded, source=group_source)

    poetry = data.get("tool")
    if isinstance(poetry, dict):
        poetry_deps = poetry.get("poetry")
        if isinstance(poetry_deps, dict):
            table = poetry_deps.get("dependencies")
            if isinstance(table, dict):
                _merge_poetry(
                    deps,
                    order,
                    table,
                    source=f"{source}:poetry",
                )

    return Watchlist(
        repo=repo,
        dependencies=[deps[key] for key in order],
    )


def _logical_requirement_lines(text: str) -> list[str]:
    """Join backslash continuations before comment stripping."""
    logical: list[str] = []
    buffer = ""
    for line in text.splitlines():
        if line.rstrip().endswith("\\"):
            buffer += line.rstrip()[:-1]
            continue
        buffer += line
        logical.append(buffer)
        buffer = ""
    if buffer:
        logical.append(buffer)
    return logical


def _strip_inline_comment(line: str) -> str:
    match = _INLINE_COMMENT.search(line)
    if match is None:
        return line.strip()
    return line[: match.start()].strip()


def _strip_requirement_options(spec: str) -> str:
    previous = None
    current = spec.strip()
    while current != previous:
        previous = current
        current = _HASH_OPTION.sub("", current).strip()
    return current


def _resolve_requirements_path(
    path: str,
    *,
    base: str,
    files: dict[str, str],
) -> str | None:
    candidates = [path]
    if base:
        candidates.insert(0, str(PurePosixPath(base).parent / path))
    lookup = {name.lower(): name for name in files}
    for candidate in candidates:
        hit = lookup.get(candidate.lower())
        if hit is not None:
            return hit
    return None


def _parse_requirements_text(
    text: str,
    *,
    source: str,
    files: dict[str, str] | None,
    base: str,
    visiting: frozenset[str],
    deps: dict[str, Dependency],
    order: list[str],
) -> None:
    for line in _logical_requirement_lines(text):
        stripped = _strip_inline_comment(line)
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("-r ") or stripped.startswith("--requirement "):
            if files is None:
                continue
            parts = stripped.split(maxsplit=1)
            if len(parts) != 2:
                continue
            include_path = parts[1].strip()
            resolved = _resolve_requirements_path(
                include_path,
                base=base,
                files=files,
            )
            if resolved is None or resolved in visiting:
                continue
            _parse_requirements_text(
                files[resolved],
                source=source,
                files=files,
                base=resolved,
                visiting=visiting | {resolved},
                deps=deps,
                order=order,
            )
            continue
        if stripped.startswith("-"):
            continue
        spec = _strip_requirement_options(stripped)
        if spec:
            _merge(deps, order, [spec], source=source)


def from_requirements(
    text: str,
    repo: str,
    *,
    source: str = "requirements.txt",
    files: dict[str, str] | None = None,
) -> Watchlist:
    """Parse ``requirements.txt`` text into a :class:`Watchlist`."""
    deps: dict[str, Dependency] = {}
    order: list[str] = []
    _parse_requirements_text(
        text,
        source=source,
        files=files,
        base=source,
        visiting=frozenset({source}),
        deps=deps,
        order=order,
    )
    return Watchlist(
        repo=repo,
        dependencies=[deps[key] for key in order],
    )


def detect_and_parse(files: dict[str, str], repo: str) -> Watchlist:
    """``{filename: contents}`` → :class:`Watchlist`. Prefers ``pyproject.toml``."""
    for name in ("pyproject.toml", "pyproject.TOML"):
        if name in files:
            return from_pyproject(files[name], repo)
    lowered = {path.lower(): contents for path, contents in files.items()}
    if "pyproject.toml" in lowered:
        return from_pyproject(lowered["pyproject.toml"], repo)
    for name in ("requirements.txt", "requirements.in"):
        if name in files:
            return from_requirements(files[name], repo, source=name, files=files)
        if name in lowered:
            key = next(path for path in files if path.lower() == name)
            return from_requirements(files[key], repo, source=key, files=files)
    return Watchlist(repo=repo, dependencies=[])
