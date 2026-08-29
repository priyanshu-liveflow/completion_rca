"""Provider factory — mirrors CUALLMFactory from CUAIntegrationAgent.

Reads CLOUD_PROVIDER (via config loader) and returns the matching BaseLLMProvider.
"""

from src.main.config import get_analyzer_configs
from src.main.shared.providers.base import BaseLLMProvider


def make_provider(
    cloud_provider: str | None = None,
    *,
    ollama_base_url: str | None = None,
    ollama_num_ctx: int | None = None,
) -> BaseLLMProvider:
    """Return the LLM provider. `cloud_provider` overrides CLOUD_PROVIDER when set."""
    if not cloud_provider:
        cloud_provider = get_analyzer_configs()["basic"]["cloud_provider"]

    if cloud_provider == "aws":
        from src.main.shared.providers.aws import AWSBedrockProvider
        return AWSBedrockProvider()

    if cloud_provider == "azure":
        from src.main.shared.providers.azure import AzureProvider
        return AzureProvider()

    if cloud_provider == "ollama":
        from src.main.shared.providers.ollama import OllamaProvider
        return OllamaProvider(
            base_url=ollama_base_url or "http://localhost:11434",
            num_ctx=ollama_num_ctx if ollama_num_ctx is not None else 32768,
        )

    if cloud_provider == "openai_compat":
        from src.main.shared.providers.langchain import LangChainProvider
        return LangChainProvider()

    raise ValueError(
        f"Unknown CLOUD_PROVIDER '{cloud_provider}'. "
        "Set CLOUD_PROVIDER=aws|azure|ollama|openai_compat in your environment or .env file."
    )
