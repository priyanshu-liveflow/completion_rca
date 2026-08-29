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
