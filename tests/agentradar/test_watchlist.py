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
    assert names == {"requests", "pydantic", "pytest", "ruff", "httpx", "rich", "mylib"}
    pydantic = next(dep for dep in watchlist.dependencies if dep.name == "pydantic")
    assert pydantic.current_version == "2.7.0"
    assert pydantic.source == "pyproject.toml"
    httpx = next(dep for dep in watchlist.dependencies if dep.name == "httpx")
    assert httpx.current_spec == "httpx[http2]^0.27.0"
    assert httpx.source == "pyproject.toml:poetry"
    mylib = next(dep for dep in watchlist.dependencies if dep.name == "mylib")
    assert mylib.current_spec.startswith("mylib @ git+")


def test_from_requirements_sample() -> None:
    files = {
        "requirements.txt": (MANIFESTS / "requirements_sample.txt").read_text(
            encoding="utf-8"
        ),
        "requirements_base.txt": (MANIFESTS / "requirements_base.txt").read_text(
            encoding="utf-8"
        ),
    }
    watchlist = from_requirements(
        files["requirements.txt"],
        "req-app",
        source="requirements.txt",
        files=files,
    )
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


def test_detect_and_parse_resolves_requirements_includes() -> None:
    files = {
        "requirements.txt": (MANIFESTS / "requirements_sample.txt").read_text(
            encoding="utf-8"
        ),
        "requirements_base.txt": (MANIFESTS / "requirements_base.txt").read_text(
            encoding="utf-8"
        ),
    }
    watchlist = detect_and_parse(files, "req-app")
    names = [dep.name for dep in watchlist.dependencies]
    assert names == ["django", "celery", "pytest"]


def test_detect_and_parse_empty_when_no_manifest() -> None:
    watchlist = detect_and_parse({}, "empty")
    assert watchlist.dependencies == []


def test_requirements_hash_options_are_preserved() -> None:
    watchlist = from_requirements(
        "securepkg==1.2.3 --hash=sha256:abcd\n",
        "hash-app",
    )
    assert len(watchlist.dependencies) == 1
    dep = watchlist.dependencies[0]
    assert dep.name == "securepkg"
    assert dep.current_version == "1.2.3"
    assert dep.current_spec == "securepkg==1.2.3"


def test_requirements_tab_inline_comment() -> None:
    watchlist = from_requirements("tabbed==1.0.0\t# inline comment\n", "tab-app")
    assert [dep.name for dep in watchlist.dependencies] == ["tabbed"]


def test_requirements_backslash_continuation() -> None:
    watchlist = from_requirements(
        "wrapped==1.0.0\\\n"
        "  --hash=sha256:deadbeef\n",
        "wrap-app",
    )
    assert len(watchlist.dependencies) == 1
    assert watchlist.dependencies[0].name == "wrapped"


def test_wildcard_pin_has_no_current_version() -> None:
    watchlist = from_requirements("prefixpkg==1.*\n", "wildcard-app")
    dep = watchlist.dependencies[0]
    assert dep.current_spec == "prefixpkg==1.*"
    assert dep.current_version is None


def test_equivalent_distribution_names_deduplicate() -> None:
    watchlist = from_requirements(
        "foo-bar==1.0.0\n"
        "foo_bar>=2.0.0\n",
        "dedupe-app",
    )
    assert [dep.name for dep in watchlist.dependencies] == ["foo-bar"]
