"""Watchlist parsing and version comparison."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.main.agentradar.core.watchlist import (
    detect_and_parse,
    from_pyproject,
    from_requirements,
    is_newer,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = ROOT / "fixtures" / "manifests"
REPO_PYPROJECT = ROOT / "pyproject.toml"

EXPECTED_RUNTIME_DEPS = [
    "pydantic",
    "typer",
    "rich",
    "httpx",
    "anthropic",
    "boto3",
    "python-dotenv",
    "azure-identity",
    "codegraphcontext",
    "falkordb",
    "tree-sitter",
    "tree-sitter-language-pack",
    "pyyaml",
    "sentence-transformers",
    "numpy",
    "scipy",
    "structlog",
    "graphviz",
    "mcp",
    "langchain-openai",
    "packaging",
]


def test_is_newer_semver() -> None:
    assert is_newer("0.2.9", "0.3.0") is True
    assert is_newer("0.10.0", "0.9.0") is False


def test_is_newer_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="invalid version"):
        is_newer("not-a-version", "1.0.0")


def test_repo_pyproject_runtime_dependencies() -> None:
    watchlist = from_pyproject(REPO_PYPROJECT.read_text(encoding="utf-8"), "graph-rca")
    runtime = [
        dep.name
        for dep in watchlist.dependencies
        if dep.source == "pyproject.toml"
    ]
    assert runtime == EXPECTED_RUNTIME_DEPS
    assert watchlist.repo == "graph-rca"


def test_pyproject_sample_merges_sections() -> None:
    text = (MANIFESTS / "pyproject_sample.toml").read_text(encoding="utf-8")
    watchlist = from_pyproject(text, "sample-app")
    names = {dep.name.lower() for dep in watchlist.dependencies}
    assert names == {"requests", "pydantic", "pytest", "ruff", "httpx", "rich"}
    pydantic = next(dep for dep in watchlist.dependencies if dep.name == "pydantic")
    assert pydantic.current_version == "2.7.0"
    assert pydantic.source == "pyproject.toml"
    httpx = next(dep for dep in watchlist.dependencies if dep.name == "httpx")
    assert httpx.source == "pyproject.toml:poetry"


def test_from_requirements_sample() -> None:
    text = (MANIFESTS / "requirements_sample.txt").read_text(encoding="utf-8")
    watchlist = from_requirements(text, "req-app")
    names = [dep.name for dep in watchlist.dependencies]
    assert names == ["django", "celery", "pytest"]
    django = next(dep for dep in watchlist.dependencies if dep.name == "django")
    assert django.current_version == "5.0.4"
    assert django.source == "requirements.txt"


def test_detect_and_parse_prefers_pyproject() -> None:
    pyproject = (MANIFESTS / "pyproject_sample.toml").read_text(encoding="utf-8")
    requirements = (MANIFESTS / "requirements_sample.txt").read_text(encoding="utf-8")
    watchlist = detect_and_parse(
        {"requirements.txt": requirements, "pyproject.toml": pyproject},
        "sample-app",
    )
    assert "requests" in {dep.name for dep in watchlist.dependencies}
    assert "django" not in {dep.name for dep in watchlist.dependencies}


def test_detect_and_parse_falls_back_to_requirements() -> None:
    requirements = (MANIFESTS / "requirements_sample.txt").read_text(encoding="utf-8")
    watchlist = detect_and_parse({"requirements.txt": requirements}, "req-app")
    names = [dep.name for dep in watchlist.dependencies]
    assert names == ["django", "celery", "pytest"]


def test_detect_and_parse_empty_when_no_manifest() -> None:
    watchlist = detect_and_parse({}, "empty")
    assert watchlist.dependencies == []
