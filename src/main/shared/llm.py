"""Core LLM utilities — extracted from graph_engine for reuse across blocks.

These are the building blocks every block uses:
- call_llm_loop: run an LLM with optional tools until it produces text
- parse_json: extract JSON from messy LLM responses
- fill_template: safe string substitution that doesn't break on JSON
"""

import json
import re
from typing import Any

from src.main.shared.providers.base import BaseLLMProvider, LLMResponse


async def call_llm_loop(
    provider: BaseLLMProvider,
    system_prompt: str,
    user_message: str,
    tools: list[dict] | None = None,
    dispatcher=None,
    max_turns: int = 10,
    model: str = "",
    tool_response_cap: int = 30000,
    on_turn=None,
    on_tool=None,
) -> tuple[str, dict]:
    """Run an LLM loop with optional tool access until text response.

    Returns (final_text, metrics) where metrics has token counts and turn count.
    """
    import asyncio

    messages = [{"role": "user", "content": user_message}]
    provider_tools = tools or []
    last_assistant_text = ""
    metrics = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0, "turns": 0}
    budget = max_turns
    turn = 0

    while turn < budget:
        response: LLMResponse = await provider.invoke(
            messages, provider_tools, system_prompt, model_override=model
        )
        metrics["input_tokens"] += response.input_tokens
        metrics["output_tokens"] += response.output_tokens
        metrics["cache_read"] += response.cache_read_tokens
        metrics["cache_write"] += response.cache_creation_tokens
        metrics["turns"] += 1

        if on_turn:
            on_turn(turn, response)

        if response.content:
            last_assistant_text = response.content

        if not response.tool_calls:
            return response.content, metrics

        # Record assistant message
        messages.append({
            "role": "assistant",
            "content": response.content or None,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in response.tool_calls
            ],
        })

        # Execute tools
        if dispatcher:
            results = await asyncio.gather(
                *[dispatcher.call_tool(tc.name, tc.arguments) for tc in response.tool_calls]
            )
            for tc, result_text in zip(response.tool_calls, results):
                if len(result_text) > tool_response_cap:
                    result_text = result_text[:tool_response_cap] + f"\n\n[TRUNCATED — showing first {tool_response_cap} of {len(result_text)} chars]"
                if on_tool:
                    on_tool(tc.name, tc.arguments, result_text)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_text})

            # Warn the LLM to wrap up when approaching budget
            if turn >= budget - 2:
                last_msg = messages[-1]
                last_msg["content"] += "\n\n[SYSTEM: You are running out of turns. Your next response MUST be your final JSON report. Do NOT make more tool calls.]"

        turn += 1

    # Budget exhausted — extend by 5 turns with context preserved
    if provider_tools and dispatcher:
        messages.append({"role": "user", "content": "[SYSTEM: Turn budget exhausted. You have 5 extra turns. Finish your investigation and provide your final answer now.]"})
        budget = turn + 5
        while turn < budget:
            response = await provider.invoke(messages, provider_tools, system_prompt, model_override=model)
            metrics["input_tokens"] += response.input_tokens
            metrics["output_tokens"] += response.output_tokens
            metrics["cache_read"] += response.cache_read_tokens
            metrics["cache_write"] += response.cache_creation_tokens
            metrics["turns"] += 1
            if response.content:
                last_assistant_text = response.content
            if not response.tool_calls:
                return response.content or last_assistant_text, metrics
            messages.append({
                "role": "assistant", "content": response.content or None,
                "tool_calls": [{"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}} for tc in response.tool_calls],
            })
            if dispatcher:
                results = await asyncio.gather(*[dispatcher.call_tool(tc.name, tc.arguments) for tc in response.tool_calls])
                for tc, result_text in zip(response.tool_calls, results):
                    if len(result_text) > tool_response_cap:
                        result_text = result_text[:tool_response_cap] + f"\n\n[TRUNCATED]"
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_text})
            turn += 1
        if response.content:
            last_assistant_text = response.content

    return last_assistant_text, metrics


def parse_json(text: str) -> Any:
    """Extract JSON from LLM response (handles markdown fences, mixed text)."""
    text = text.strip()

    # Strip markdown fences
    if "```" in text:
        parts = text.split("```")
        for part in parts[1:]:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            candidate = candidate.rstrip("`").strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find largest JSON structure
    for pattern in [r'\[[\s\S]*\]', r'\{[\s\S]*\}']:
        matches = re.findall(pattern, text)
        for match in sorted(matches, key=len, reverse=True):
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue

    return None


def fill_template(template: str, **kwargs) -> str:
    """Safe string substitution that doesn't break on JSON braces."""
    for key, value in kwargs.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, indent=2, default=str)
        template = template.replace("{" + key + "}", str(value))
    return template
