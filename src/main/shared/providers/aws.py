"""AWS Bedrock provider — mirrors CUAIntegrationAgent's CUAAWSHandler._get_bedrock_client_model.

boto3 client is created with the same botocore.config.Config (retry mode, read timeout)
as in cua_aws_handler.py. AWS credentials come from the SDK default credential chain
(IAM roles / env vars / ~/.aws/credentials) — no credentials stored in config.
"""

import asyncio
import json
from typing import Any

import boto3
from botocore.config import Config

from src.main.config import get_cloud_provider_configs
from .base import BaseLLMProvider, LLMResponse, ToolCall


class AWSBedrockProvider(BaseLLMProvider):
    def __init__(self):
        self._cfg = get_cloud_provider_configs()
        # Eagerly create client on main thread so MFA/stdin prompts work correctly.
        self._client = self._create_client()

    def _create_client(self):
        """Exact replica of CUAAWSHandler._get_bedrock_client_model for the main model."""
        retry_mode: str = self._cfg.get("bedrock_retry_mode", "adaptive")
        retry_attempts: int = self._cfg.get("bedrock_retries", 3)
        read_timeout: int = self._cfg.get("bedrock_read_timeout", 1200)
        region: str = self._cfg.get("same_region", "us-east-1")
        service: str = self._cfg.get("bedrock-runtime", "bedrock-runtime")

        bedrock_config = Config(
            retries={"max_attempts": retry_attempts, "mode": retry_mode},
            read_timeout=read_timeout,
        )
        return boto3.client(service, region_name=region, config=bedrock_config)

    def _get_client(self):
        return self._client

    # ── Tool schema conversion (MCP → Bedrock Converse format) ──

    def get_tool_schemas(self, mcp_tools: list[dict]) -> list[dict]:
        return [
            {
                "toolSpec": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "inputSchema": {
                        "json": t.get("inputSchema") or {"type": "object", "properties": {}}
                    },
                }
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
        return await asyncio.to_thread(self._invoke_sync, messages, tools, system, model_override)

    def _invoke_sync(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
        model_override: str = "",
    ) -> LLMResponse:
        model_id: str = model_override or self._cfg.get("main_model", "")
        bedrock_messages = self._to_bedrock_messages(messages, model_id)
        client = self._get_client()

        cache_enabled: bool = self._cfg.get("bedrock_prompt_cache", False)
        # Prompt caching only works with Anthropic models
        if cache_enabled and "anthropic" not in model_id:
            cache_enabled = False
        cache_point = {"cachePoint": {"type": "default"}}

        max_tokens: int = self._cfg.get("anthropic_max_tokens", 4096)

        kwargs: dict[str, Any] = {
            "modelId": model_id,
            "messages": bedrock_messages,
            "system": (
                [{"text": system}, cache_point]
                if cache_enabled else
                [{"text": system}]
            ),
            "inferenceConfig": {"maxTokens": max_tokens},
        }
        if tools:
            cached = list(tools) + [cache_point] if cache_enabled else tools
            kwargs["toolConfig"] = {"tools": cached}

        response = client.converse(**kwargs)
        output_content = response["output"]["message"].get("content", [])

        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []
        for block in output_content:
            if "text" in block:
                text_parts.append(block["text"])
            elif "toolUse" in block:
                tc = block["toolUse"]
                tool_calls.append(ToolCall(
                    id=tc["toolUseId"],
                    name=tc["name"],
                    arguments=tc["input"],
                ))

        usage = response.get("usage", {})
        return LLMResponse(
            content=" ".join(text_parts),
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else response.get("stopReason", "end_turn"),
            input_tokens=usage.get("inputTokens", 0) or 0,
            output_tokens=usage.get("outputTokens", 0) or 0,
            cache_read_tokens=usage.get("cacheReadInputTokens", 0) or 0,
            cache_creation_tokens=usage.get("cacheWriteInputTokens", 0) or 0,
        )

    # ── Message format conversion (OpenAI canonical → Bedrock Converse) ──

    def _to_bedrock_messages(self, messages: list[dict], model_id: str = "") -> list[dict]:
        """Convert engine's OpenAI-format messages to Bedrock Converse format.

        Bedrock differences from OpenAI:
        - Tool results go in a "user" role message, not a "tool" role message
        - Multiple consecutive tool results merge into one user message
        - Tool calls in assistant messages use toolUse content blocks

        Cache strategy: place a cachePoint on the second-to-last message so that
        on the next turn, everything up to that point is a cache hit.
        """
        result: list[dict] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg["role"]

            if role == "user":
                content = msg["content"]
                if isinstance(content, str):
                    result.append({"role": "user", "content": [{"text": content}]})
                else:
                    result.append({"role": "user", "content": content})
                i += 1

            elif role == "assistant":
                content_blocks: list[dict] = []
                if msg.get("content"):
                    content_blocks.append({"text": msg["content"]})
                for tc in msg.get("tool_calls", []):
                    content_blocks.append({
                        "toolUse": {
                            "toolUseId": tc["id"],
                            "name": tc["function"]["name"],
                            "input": json.loads(tc["function"]["arguments"]),
                        }
                    })
                result.append({"role": "assistant", "content": content_blocks})
                i += 1

            elif role == "tool":
                # Merge all consecutive tool results into one user message
                tool_result_blocks: list[dict] = []
                while i < len(messages) and messages[i]["role"] == "tool":
                    tmsg = messages[i]
                    tool_result_blocks.append({
                        "toolResult": {
                            "toolUseId": tmsg["tool_call_id"],
                            "content": [{"text": tmsg["content"]}],
                        }
                    })
                    i += 1
                result.append({"role": "user", "content": tool_result_blocks})

            else:
                i += 1

        # Place cache point on the second-to-last message when caching is enabled.
        # For single-message conversations, place it on the user message itself
        # (the system prompt alone is often under the 4096-token minimum).
        cache_enabled: bool = self._cfg.get("bedrock_prompt_cache", False)
        if cache_enabled and "anthropic" not in model_id:
            cache_enabled = False
        if cache_enabled:
            if len(result) == 1:
                # Single turn: cache the user message (often large context)
                target = result[0]
                if isinstance(target.get("content"), list):
                    target["content"].append({"cachePoint": {"type": "default"}})
            elif len(result) >= 2:
                target = result[-2]
                if isinstance(target.get("content"), list):
                    target["content"].append({"cachePoint": {"type": "default"}})

        return result
