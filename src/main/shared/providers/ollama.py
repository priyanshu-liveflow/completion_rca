"""Ollama provider — local model inference via Ollama's OpenAI-compatible API.

Supports tool calling (Ollama 0.4+ with supported models like Gemma3, Llama3, Qwen2.5).
Uses the /api/chat endpoint with tools parameter.
"""

import asyncio
import json
import uuid
from typing import Any

import httpx

from .base import BaseLLMProvider, LLMResponse, ToolCall


class OllamaProvider(BaseLLMProvider):
    def __init__(self, base_url: str = "http://localhost:11434"):
        self._base_url = base_url
        self._client = httpx.Client(base_url=base_url, timeout=300.0)

    def get_tool_schemas(self, mcp_tools: list[dict]) -> list[dict]:
        """Convert MCP tool schemas to Ollama/OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema") or t.get("inputSchema") or {"type": "object", "properties": {}},
                },
            }
            for t in mcp_tools
        ]

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
        model = model_override or "gemma3:4b"
        ollama_messages = self._to_ollama_messages(messages, system)

        payload: dict[str, Any] = {
            "model": model,
            "messages": ollama_messages,
            "stream": False,
            "options": {"num_ctx": 32768},
        }
        if tools:
            payload["tools"] = tools

        resp = self._client.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

        msg = data.get("message", {})
        content = msg.get("content", "")
        tool_calls: list[ToolCall] = []

        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            tool_calls.append(ToolCall(
                id=str(uuid.uuid4())[:8],
                name=fn.get("name", ""),
                arguments=fn.get("arguments", {}),
            ))

        # Token counts from Ollama response
        input_tokens = data.get("prompt_eval_count", 0) or 0
        output_tokens = data.get("eval_count", 0) or 0

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _to_ollama_messages(self, messages: list[dict], system: str) -> list[dict]:
        """Convert engine's OpenAI-format messages to Ollama chat format."""
        result: list[dict] = []

        if system:
            result.append({"role": "system", "content": system})

        for msg in messages:
            role = msg["role"]

            if role == "user":
                content = msg["content"]
                if isinstance(content, list):
                    # Flatten content blocks to text
                    text = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
                    result.append({"role": "user", "content": text})
                else:
                    result.append({"role": "user", "content": content})

            elif role == "assistant":
                entry: dict[str, Any] = {"role": "assistant", "content": msg.get("content", "")}
                if msg.get("tool_calls"):
                    entry["tool_calls"] = [
                        {
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"],
                            }
                        }
                        for tc in msg["tool_calls"]
                    ]
                result.append(entry)

            elif role == "tool":
                result.append({
                    "role": "tool",
                    "content": msg["content"],
                })

        return result
