"""Azure AI Foundry provider — mirrors CUAIntegrationAgent's CUAAzureHandler credential logic.

Auth flow (identical to cua_azure_handler.py):
  IS_USE_SECRET_KEY=true  → API key from AZURE_API_KEY
  IS_USE_SECRET_KEY=false → ManagedIdentityCredential with AZURE_CLIENT_ID

Client: AsyncAnthropicFoundry  (Claude models on Azure AI Foundry)
"""

import json
from typing import Any

from anthropic import AsyncAnthropicFoundry, omit
from azure.identity import ManagedIdentityCredential, get_bearer_token_provider

from src.main.config import get_cloud_provider_configs
from .base import BaseLLMProvider, LLMResponse, ToolCall


class AzureProvider(BaseLLMProvider):
    def __init__(self):
        self._cfg = get_cloud_provider_configs()
        self._token_provider = None  # cached — mirrors CUAAzureHandler

    # ── Client creation (exact logic from cua_azure_handler._azure_client_helper) ──

    async def _get_client(self) -> AsyncAnthropicFoundry:
        is_use_key: bool = self._cfg.get("is_use_key", False)
        time_out: int = self._cfg.get("client_read_timeout", 120)
        max_retries: int = self._cfg.get("azure_client_retries", 3)
        endpoint: str = self._cfg.get("azure_ai_foundry_anthropic_endpoint", "")

        if is_use_key:
            api_key: Any = self._cfg.get("azure_api_key", "")
            return AsyncAnthropicFoundry(
                api_key=api_key,
                base_url=endpoint,
                timeout=time_out,
                max_retries=max_retries,
            )
        else:
            # Build token provider once and reuse — WorkloadIdentityCredential handles caching
            if self._token_provider is None:
                self._token_provider = get_bearer_token_provider(
                    ManagedIdentityCredential(client_id=self._cfg.get("azure_client_id", "")),
                    "https://cognitiveservices.azure.com/.default",
                )
            return AsyncAnthropicFoundry(
                azure_ad_token_provider=self._token_provider,
                base_url=endpoint,
                timeout=time_out,
                max_retries=max_retries,
            )

    # ── Tool schema conversion (MCP → Anthropic format) ──

    def get_tool_schemas(self, mcp_tools: list[dict]) -> list[dict]:
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("inputSchema") or {"type": "object", "properties": {}},
            }
            for t in mcp_tools
        ]

    # ── Invocation ──

    async def invoke(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
        model_override: str = "",
    ) -> LLMResponse:
        client = await self._get_client()
        model_id: str = model_override or self._cfg.get("main_model", "")
        anthropic_messages = self._to_anthropic_messages(messages)

        # Cache the system prompt (one breakpoint)
        system_param = (
            [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            if system else omit
        )

        # Cache after the last tool definition (second breakpoint)
        cached_tools: Any = omit
        if tools:
            cached_tools = list(tools)
            cached_tools[-1] = {**cached_tools[-1], "cache_control": {"type": "ephemeral"}}

        response = await client.messages.create(
            model=model_id,
            messages=anthropic_messages,
            system=system_param,
            tools=cached_tools,
            max_tokens=self._cfg.get("anthropic_max_tokens", 4096),
            thinking={"type": "adaptive"},
            output_config={"effort": "xhigh"},
        )

        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []
        for block in response.content:
            if block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))
            elif block.type == "text":
                text_parts.append(block.text)

        usage = response.usage
        return LLMResponse(
            content=" ".join(text_parts),
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else (response.stop_reason or "end_turn"),
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )

    # ── Message format conversion (OpenAI canonical → Anthropic) ──

    def _to_anthropic_messages(self, messages: list[dict]) -> list[dict]:
        """Convert engine's OpenAI-format messages to Anthropic messages.create() format.

        Key differences from OpenAI:
        - Tool calls in assistant message use content blocks (type: tool_use)
        - Tool results are user-role messages with tool_result content blocks
        - Multiple consecutive tool results merge into one user message
        """
        result: list[dict] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg["role"]

            if role == "user":
                content = msg["content"]
                if isinstance(content, str):
                    result.append({"role": "user", "content": content})
                else:
                    result.append({"role": "user", "content": content})
                i += 1

            elif role == "assistant":
                content_blocks: list[dict] = []
                if msg.get("content"):
                    content_blocks.append({"type": "text", "text": msg["content"]})
                for tc in msg.get("tool_calls", []):
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": json.loads(tc["function"]["arguments"]),
                    })
                result.append({"role": "assistant", "content": content_blocks})
                i += 1

            elif role == "tool":
                # Merge all consecutive tool results into one user message
                tool_result_blocks: list[dict] = []
                while i < len(messages) and messages[i]["role"] == "tool":
                    tmsg = messages[i]
                    tool_result_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": tmsg["tool_call_id"],
                        "content": tmsg["content"],
                    })
                    i += 1
                result.append({"role": "user", "content": tool_result_blocks})

            else:
                i += 1

        return result
