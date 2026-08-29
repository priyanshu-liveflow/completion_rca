"""Watchlist and release events derived from a repo's dependency manifest."""

from pydantic import BaseModel, ConfigDict


class Dependency(BaseModel):
    """A single runtime dependency taken from the indexed repo's manifest."""

    model_config = ConfigDict(frozen=True)

    name: str
    current_spec: str
    current_version: str | None
    source: str


class Watchlist(BaseModel):
    """Dependencies the scouts watch; the manifest *is* the watchlist."""

    model_config = ConfigDict(frozen=True)

    repo: str
    dependencies: list[Dependency]


class ReleaseEvent(BaseModel):
    """A published version the scouts retrieved for a watched dependency."""

    model_config = ConfigDict(frozen=True)

    dependency: str
    version: str
    published_at: str
    title: str
    body: str
    url: str
    breaking_hint: bool = False
    source_collector: str | None = None


class DemoTarget(BaseModel):
    """What the agent is working on: repo, commit, dependency, symbol.

    Deliberately does NOT carry `configs/demo.yaml`'s `expected_*` keys. Those
    are the answer key — the contact points, the test selection, the patch
    shape — and they exist to check the agent's work, not to feed it. An agent
    handed `expected_contact_points` would report them back without the graph
    proving anything, and the demo would be a recitation.
    """

    model_config = ConfigDict(frozen=True)

    repo_url: str
    repo_key: str
    commit: str
    source_root: str
    test_root: str
    test_command: str
    python: str
    dependency: str
    from_version: str
    to_version: str
    install_spec_before: str
    install_spec_after: str
    symbol: str
