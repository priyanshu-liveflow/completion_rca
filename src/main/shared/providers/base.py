"""Base types shared by all LLM providers."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


class BaseLLMProvider:
    def get_tool_schemas(self, mcp_tools: list[dict]) -> list[dict]:
        """Convert MCP tool schemas to provider-specific function-calling format."""
        raise NotImplementedError

    async def invoke(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
        model_override: str = "",
    ) -> LLMResponse:
        raise NotImplementedError
