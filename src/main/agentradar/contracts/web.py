"""Search and scrape payloads returned by the web MCP tools."""

from pydantic import BaseModel, ConfigDict


class SearchHit(BaseModel):
    """One organic SERP result after Bright Data search."""

    model_config = ConfigDict(frozen=True)

    title: str
    url: str
    snippet: str


class SearchResults(BaseModel):
    """Contract returned by `web_search`."""

    model_config = ConfigDict(frozen=True)

    query: str
    hits: list[SearchHit]


class PageContent(BaseModel):
    """Contract returned by `scrape_page`."""

    model_config = ConfigDict(frozen=True)

    url: str
    text: str
