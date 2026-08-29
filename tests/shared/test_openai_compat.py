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


@pytest.mark.asyncio
async def test_invoke_binds_tools_before_model_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: tools + model_override must not raise AttributeError.

    `bind_tools` is a ChatOpenAI method. `Runnable.bind` returns a generic
    RunnableBinding that does not expose it, so binding the model override
    first crashes before any request. The trace-agent path always supplies
    both, which made every OpenAI-compatible trace fail on its first turn.
    """
    monkeypatch.setenv("CLOUD_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    provider = LangChainProvider()
    captured: dict[str, object] = {}

    class _Response:
        content = "ok"
        tool_calls: list[dict] = []
        response_metadata: dict = {}

    class _Bound:
        def __init__(self, tools: object) -> None:
            self._tools = tools

        def bind(self, **kwargs: object) -> "_Bound":
            captured["model"] = kwargs.get("model")
            return self

        async def ainvoke(self, _messages: object) -> _Response:
            captured["tools"] = self._tools
            return _Response()

    class _Client:
        def bind_tools(self, tools: object) -> _Bound:
            return _Bound(tools)

        def bind(self, **_kwargs: object) -> object:  # pragma: no cover
            raise AssertionError("model override must be bound after tools")

    provider._client = _Client()  # type: ignore[assignment]

    tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
    response = await provider.invoke(
        messages=[{"role": "user", "content": "hi"}],
        tools=tools,
        system="sys",
        model_override="some/other-model",
    )

    assert response.content == "ok"
    assert captured["tools"] == tools
    assert captured["model"] == "some/other-model"
