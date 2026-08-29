"""Provider factory — mirrors CUALLMFactory from CUAIntegrationAgent.

Reads CLOUD_PROVIDER (via config loader) and returns the matching BaseLLMProvider.
"""

from src.main.config import get_analyzer_configs
from src.main.shared.providers.base import BaseLLMProvider


def make_provider() -> BaseLLMProvider:
    cloud_provider: str = get_analyzer_configs()["basic"]["cloud_provider"]

    if cloud_provider == "aws":
        from src.main.shared.providers.aws import AWSBedrockProvider
        return AWSBedrockProvider()

    if cloud_provider == "azure":
        from src.main.shared.providers.azure import AzureProvider
        return AzureProvider()

    if cloud_provider == "ollama":
        from src.main.shared.providers.ollama import OllamaProvider
        return OllamaProvider()

    raise ValueError(
        f"Unknown CLOUD_PROVIDER '{cloud_provider}'. "
        "Set CLOUD_PROVIDER=aws|azure|ollama in your environment or .env file."
    )
