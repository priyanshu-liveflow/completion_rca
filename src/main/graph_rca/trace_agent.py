"""Trace Agent — walks code graph following assigned path, collects evidence."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from src.main.shared.llm import call_llm_loop, parse_json
from src.main.shared.base import BlockContext
from src.main.shared.logging import get_logger
from src.main.code_tools.trace_tools import TOOLS, handle_tool_call
from .models.agents import AgentAssignment, Evidence, TraceReport
from .config import DomainConfig

log = get_logger("trace_agent")

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


def _is_incomplete(text: str) -> bool:
    """Detect if agent output indicates it ran out of turns before finishing."""
    if not text:
        return True
    t = text.lower()
    return any(phrase in t for phrase in [
        "turn budget exhausted",
        "investigation incomplete",
        "insufficient to make definitive",
        "cut short due to turn",
        "unable to provide verified",
        "unable to provide a complete",
    ])


async def run_trace_agent(
    assignment: AgentAssignment,
    config: DomainConfig,
    ctx: BlockContext,
    repo_path: str,
    log_context: str = "",
    system_override: str = "",
    raw_output: bool = False,
) -> TraceReport:
    """Run a single trace agent with its assignment."""
    model = {
        "light": config.model_light,
        "default": config.model_default,
        "heavy": config.model_heavy,
    }.get(assignment.model, config.model_default)

    if ctx.verbose:
        log.debug("trace_start", agent=assignment.id, start=assignment.starting_node, model=model, direction=assignment.direction)

    import time as _time
    _t0 = _time.monotonic()

    system = system_override if system_override else _load_prompt("trace_agent").format(
        starting_node=assignment.starting_node,
        scope=assignment.scope,
        direction=assignment.direction,
    )

    user_msg = f"""{log_context}

## Your Assignment
Start at: {assignment.starting_node}
Scope: {assignment.scope}
Direction: {assignment.direction}

## Instructions
- The source code, flow graph, and log entries above are PRE-LOADED for you.
- Do NOT call read_function_source for your starting function.
- Use tools only to explore DEEPER (callees, related functions you haven't seen).
- At ERROR points, trace the failing value back to its origin.
- If source is NOT available (⚠️ NOT_IN_GRAPH), search for app-level callers instead."""
    if assignment.path_slice:
        user_msg += f"\n\n## Your path to walk:\n{' → '.join(assignment.path_slice)}\nRead each function in this sequence. Verify the connections. Find where it breaks and WHY."
    if assignment.context_from_parent:
        user_msg += f"\n\n## Context from parent investigation:\n{assignment.context_from_parent}"

    provider_tools = ctx.provider.get_tool_schemas(TOOLS)
    dispatcher = _TraceDispatcher(repo_path, starting_node=assignment.starting_node)

    def _on_turn(turn, response):
        if ctx.verbose:
            reasoning = (response.content or "").strip().replace("\n", " ")
            if reasoning:
                log.debug("trace_turn", agent=assignment.id, turn=turn, reasoning=reasoning)

    def _on_tool(name, args, result):
        if ctx.verbose:
            arg_str = args.get("function_name") or args.get("class_name") or args.get("pattern") or str(args)[:50]
            found = not ("not found" in result.lower() or "no " in result.lower()[:20] or "error" in result.lower()[:20])
            log.debug("trace_tool", agent=assignment.id, tool=name, arg=arg_str, found=found, result=result)

    text, metrics = await call_llm_loop(
        provider=ctx.provider,
        system_prompt=system,
        user_message=user_msg,
        tools=provider_tools if provider_tools else None,
        dispatcher=dispatcher,
        max_turns=config.max_turns_per_agent,
        model=model,
        on_turn=_on_turn,
        on_tool=_on_tool,
    )
    ctx.metrics.add(metrics, model=model)

    if ctx.verbose:
        log.debug("trace_done", agent=assignment.id, model=model, turns=metrics['turns'], input_tokens=metrics['input_tokens'], output_tokens=metrics['output_tokens'], cache_read=metrics['cache_read'], cache_write=metrics['cache_write'], duration_s=round(_time.monotonic() - _t0, 1))

    if raw_output:
        return TraceReport(
            agent_id=assignment.id, path_walked=[assignment.starting_node],
            evidence=[], assessment=text, root_cause_node=None,
            is_input_issue=False, confidence=1.0, model=model, token_usage=metrics,
        )

    parsed = parse_json(text)
    if parsed and "assessment" in parsed:
        report = _build_report(assignment.id, parsed)
        report.model = model
        report.token_usage = metrics
        if ctx.verbose:
            log.debug("trace_result", agent=assignment.id, confidence=f"{report.confidence:.2f}", root=report.root_cause_node)
        return report

    if ctx.verbose:
        log.warning("trace_parse_failed", agent=assignment.id, text_len=len(text), text_preview=text)
    return TraceReport(
        agent_id=assignment.id,
        path_walked=[assignment.starting_node],
        evidence=[],
        assessment=text[:2000],
        root_cause_node=None,
        is_input_issue=False,
        confidence=0.3,
        model=model,
        token_usage=metrics,
    )


class _TraceDispatcher:
    """Minimal dispatcher that routes tool calls to the code graph."""
    def __init__(self, repo_path: str, starting_node: str = ""):
        self.repo_path = repo_path
        self.starting_node = starting_node

    async def call_tool(self, name: str, arguments: dict) -> str:
        try:
            # Auto-fill from starting_node if model passes empty args and no fid
            if "fid" not in arguments and "function_name" not in arguments:
                if name in ("read_function_source", "get_callers", "get_callees", "get_db_tables", "get_log_templates"):
                    if self.starting_node:
                        arguments["function_name"] = self.starting_node
                elif name in ("get_class_info", "get_inheritance"):
                    if "class_name" not in arguments and self.starting_node:
                        parts = self.starting_node.split(".")
                        arguments["class_name"] = parts[-2] if len(parts) >= 2 else self.starting_node
            if name in ("get_class_info", "get_inheritance") and "class_name" not in arguments:
                return f"Error: missing required argument 'class_name'."
            if name == "find_function_by_pattern" and "pattern" not in arguments:
                return f"Error: missing required argument 'pattern'."
            if name == "get_call_chain" and ("from_function" not in arguments or "to_function" not in arguments):
                return f"Error: missing required arguments 'from_function' and 'to_function'."
            return await asyncio.to_thread(handle_tool_call, name, arguments, self.repo_path)
        except Exception as e:
            return f"Error executing {name}: {type(e).__name__}: {e}"


def _build_report(agent_id: str, parsed: dict) -> TraceReport:
    return TraceReport(
        agent_id=agent_id,
        path_walked=parsed.get("path_walked", []),
        evidence=[
            Evidence(
                type=e.get("type", ""),
                content=e.get("content", ""),
                location=e.get("location", ""),
            )
            for e in parsed.get("evidence", [])
        ],
        assessment=parsed.get("assessment", ""),
        root_cause_node=parsed.get("root_cause_node"),
        is_input_issue=parsed.get("is_input_issue", False),
        confidence=parsed.get("confidence", 0.5),
        dead_ends=parsed.get("dead_ends", []),
    )
