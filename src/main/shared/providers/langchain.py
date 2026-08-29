"""OpenAI-compatible LLM provider via LangChain ChatOpenAI.

Covers NVIDIA NIM, OpenAI, vLLM, Groq, and any other OpenAI-compatible endpoint.
"""

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from src.main.config import get_cloud_provider_configs
from .base import BaseLLMProvider, LLMResponse, ToolCall


class LangChainProvider(BaseLLMProvider):
    """LLM provider backed by langchain_openai.ChatOpenAI."""

    def __init__(self) -> None:
        self._cfg = get_cloud_provider_configs()
        self._client = ChatOpenAI(
            base_url=self._cfg["llm_base_url"],
            api_key=self._cfg["llm_api_key"],
            model=self._cfg["llm_model"],
        )

    def get_tool_schemas(self, mcp_tools: list[dict]) -> list[dict]:
        """Convert MCP tool schemas to OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema")
                    or t.get("inputSchema")
                    or {"type": "object", "properties": {}},
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
        model = model_override or self._cfg["llm_model"]
        # bind_tools is a ChatOpenAI method, so it must be called on the model
        # itself. Runnable.bind returns a generic RunnableBinding that does not
        # expose it — binding the model override first raises AttributeError
        # before any request is made, and the trace-agent path always supplies
        # both an override and tools.
        client: Any = self._client
        if tools:
            client = client.bind_tools(tools)
        if model_override:
            client = client.bind(model=model)

        lc_messages = self._to_lc_messages(messages, system)
        response: AIMessage = await client.ainvoke(lc_messages)

        tool_calls: list[ToolCall] = []
        for tc in response.tool_calls or []:
            args = tc.get("args", {})
            if isinstance(args, str):
                args = json.loads(args)
            tool_calls.append(
                ToolCall(
                    id=tc["id"],
                    name=tc["name"],
                    arguments=args,
                )
            )

        usage = (response.response_metadata or {}).get("token_usage", {})
        return LLMResponse(
            content=response.content or "",
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
            input_tokens=usage.get("prompt_tokens", 0) or 0,
            output_tokens=usage.get("completion_tokens", 0) or 0,
        )

    def _to_lc_messages(self, messages: list[dict], system: str) -> list[Any]:
        """Convert engine OpenAI-format messages to LangChain message types."""
        result: list[Any] = []
        if system:
            result.append(SystemMessage(content=system))

        for msg in messages:
            role = msg["role"]
            if role == "user":
                content = msg["content"]
                if isinstance(content, list):
                    text = " ".join(
                        block.get("text", "") for block in content if isinstance(block, dict)
                    )
                    result.append(HumanMessage(content=text))
                else:
                    result.append(HumanMessage(content=content))

            elif role == "assistant":
                lc_tool_calls: list[dict[str, Any]] = []
                for tc in msg.get("tool_calls", []):
                    raw_args = tc["function"]["arguments"]
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    lc_tool_calls.append(
                        {
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "args": args,
                        }
                    )
                result.append(AIMessage(content=msg.get("content") or "", tool_calls=lc_tool_calls))

            elif role == "tool":
                result.append(
                    ToolMessage(content=msg["content"], tool_call_id=msg["tool_call_id"])
                )

        return result
