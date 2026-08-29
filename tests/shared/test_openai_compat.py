"""Tests for the openai_compat LLM provider factory branch."""

import pytest

from src.main.config.loader import get_analyzer_configs
from src.main.shared.factory import make_provider
from src.main.shared.providers.langchain import LangChainProvider


@pytest.fixture(autouse=True)
def _clear_config_cache() -> None:
    get_analyzer_configs.cache_clear()
    yield
    get_analyzer_configs.cache_clear()


def test_factory_returns_langchain_provider_for_openai_compat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLOUD_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    provider = make_provider(cloud_provider="openai_compat")
    assert isinstance(provider, LangChainProvider)


def test_factory_raises_for_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown CLOUD_PROVIDER"):
        make_provider(cloud_provider="not-a-provider")


def test_factory_reads_cloud_provider_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUD_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    provider = make_provider()
    assert isinstance(provider, LangChainProvider)
