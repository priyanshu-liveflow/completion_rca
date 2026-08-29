"""Build a :class:`Watchlist` from dependency manifest files.

Pure. Uses stdlib :mod:`tomllib` and :mod:`packaging` for PEP 508 / PEP 440.
"""

from __future__ import annotations

import re
import tomllib
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

from ..contracts.dependency import Dependency, Watchlist

__all__ = [
    "detect_and_parse",
    "from_pyproject",
    "from_requirements",
    "is_newer",
]

_SKIP_NAMES = frozenset({"python", "python_version"})
_COMMENT = re.compile(r"(?:^| )#.*$")


def is_newer(current: str, candidate: str) -> bool:
    """Return True when ``candidate`` is newer than ``current`` (PEP 440)."""
    try:
        return Version(candidate) > Version(current)
    except InvalidVersion as exc:
        raise ValueError(f"invalid version: {exc}") from exc


def _pinned_version(spec: str) -> str | None:
    """Extract an exact pin from a PEP 508 requirement string, if present."""
    try:
        requirement = Requirement(spec)
    except InvalidRequirement:
        return None
    for item in requirement.specifier:
        if item.operator == "==":
            return item.version
    return None


def _dependency_from_spec(spec: str, *, source: str) -> Dependency | None:
    """Parse one PEP 508 string into a :class:`Dependency`, or ``None`` to skip."""
    stripped = spec.strip()
    if not stripped or stripped.startswith("#"):
        return None
    try:
        requirement = Requirement(stripped)
    except InvalidRequirement:
        return None
    name = requirement.name.lower()
    if name in _SKIP_NAMES:
        return None
    return Dependency(
        name=requirement.name,
        current_spec=stripped,
        current_version=_pinned_version(stripped),
        source=source,
    )


def _dependency_from_poetry(
    name: str,
    version: str,
    *,
    source: str,
) -> Dependency | None:
    if name.lower() in _SKIP_NAMES:
        return None
    for candidate in (f"{name}{version}", f"{name} {version}"):
        dep = _dependency_from_spec(candidate, source=source)
        if dep is not None:
            return dep
    return Dependency(
        name=name,
        current_spec=version,
        current_version=_pinned_version(version) if "==" in version else None,
        source=source,
    )


def _append(
    deps: dict[str, Dependency],
    order: list[str],
    dep: Dependency | None,
) -> None:
    if dep is None:
        return
    key = dep.name.lower()
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
        version = _poetry_spec(value)
        if version is None:
            continue
        _append(deps, order, _dependency_from_poetry(name, version, source=source))


def _poetry_spec(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        version = value.get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
    return None


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
                _merge(
                    deps,
                    order,
                    [str(item) for item in group_deps],
                    source=group_source,
                )

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


def _requirements_line(line: str) -> str | None:
    stripped = _COMMENT.sub("", line).strip()
    if not stripped or stripped.startswith("-"):
        return None
    return stripped


def from_requirements(text: str, repo: str) -> Watchlist:
    """Parse ``requirements.txt`` text into a :class:`Watchlist`."""
    deps: dict[str, Dependency] = {}
    order: list[str] = []
    source = "requirements.txt"
    for line in text.splitlines():
        spec = _requirements_line(line)
        if spec is None:
            continue
        _merge(deps, order, [spec], source=source)
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
            return from_requirements(files[name], repo)
        if name in lowered:
            return from_requirements(lowered[name], repo)
    return Watchlist(repo=repo, dependencies=[])
