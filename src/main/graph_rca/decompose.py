"""DECOMPOSE block — LLM decides investigation strategy from walkable path."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.main.shared.llm import call_llm_loop, parse_json
from src.main.shared.base import BlockContext
from src.main.shared.logging import get_logger
from .models import WalkablePath
from .models.agents import AgentAssignment
from .config import DomainConfig

log = get_logger("decompose")

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


async def decompose(
    path: WalkablePath,
    config: DomainConfig,
    ctx: BlockContext,
    flow_context: str = "",
    focus_prompt: str = "",
) -> list[AgentAssignment]:
    """Analyze walkable path and produce agent assignments."""
    summary = _build_path_summary(path)
    if flow_context:
        summary += "\n\n" + flow_context
    if focus_prompt:
        if focus_prompt.startswith("## TIER"):
            # Structured tiered context from prompt_search — inject as-is
            summary = f"{focus_prompt}\n---\n\n{summary}"
        else:
            # Plain text prompt — wrap with instruction
            summary = f"## INVESTIGATION FOCUS\n{focus_prompt}\nPrioritize clusters and errors related to the above. Assign your strongest agents (heavy model) to these areas.\n\n{summary}"
    if ctx.verbose:
        log.debug("decompose_start", errors=len(path.error_points), branches=len(path.branches), summary_chars=len(summary))

    system = _load_prompt("decompose").format(max_agents=config.max_trace_agents)

    text, metrics = await call_llm_loop(
        provider=ctx.provider,
        system_prompt=system,
        user_message=summary,
        tools=None,
        max_turns=1,
        model=config.model_heavy,
    )
    ctx.metrics.add(metrics, model=config.model_heavy)

    if ctx.verbose:
        log.debug("decompose_tokens", input=metrics.get('input_tokens', 0), output=metrics.get('output_tokens', 0), cache_read=metrics.get('cache_read', 0))

    parsed = parse_json(text)
    if not parsed or "agents" not in parsed:
        if ctx.verbose:
            log.warning("decompose_parse_failed")
        return _fallback_assignments(path, config)

    if ctx.verbose and parsed.get("strategy"):
        log.debug("decompose_strategy", strategy=parsed['strategy'])

    assignments = []
    seen_starts = set()
    for a in parsed["agents"]:
        node = a.get("starting_node", "")
        # Skip duplicate starting nodes
        if node in seen_starts:
            continue
        seen_starts.add(node)
        assignments.append(AgentAssignment(
            id=a.get("id", f"trace_{len(assignments)+1}"),
            starting_node=node,
            scope=a.get("scope", ""),
            direction=a.get("direction", "backward"),
            model=a.get("model", "default"),
            tools=a.get("tools", "graph_only"),
            parent_agent=a.get("parent_agent"),
            context_from_parent=a.get("context_from_parent"),
            path_slice=a.get("path_slice"),
        ))

    return assignments[:config.max_trace_agents]


def _build_path_summary(path: WalkablePath) -> str:
    """Build concise summary of the walkable path for the LLM."""
    lines = [
        f"## Log Analysis Summary",
        f"- Total entries: {len(path.entries)}",
        f"- Coverage: {path.coverage_pct}%",
        f"- Error points: {len(path.error_points)}",
        f"- Branch points (ambiguity): {len(path.branches)}",
        f"- Repo: {path.repo}",
        "",
        "## Error Entries",
    ]

    for idx in path.error_points:
        e = path.entries[idx]
        func = e.originated_from[0] if e.originated_from else "UNMAPPED"
        stack_info = ""
        if e.stack_trace:
            stack_info = f" | Exception: {e.stack_trace.exception}: {e.stack_trace.message}"
            if e.stack_trace.frames:
                top_frames = [f"{f.class_name}.{f.method}" for f in e.stack_trace.frames[:3]]
                stack_info += f" | Frames: {' → '.join(top_frames)}"
            if e.stack_trace.caused_by:
                cb = e.stack_trace.caused_by[0]
                stack_info += f" | Caused by: {cb.exception}: {cb.message}"

        lines.append(f"  L{e.line_number} [{e.level}] → {func}{stack_info}")
        lines.append(f"    Message: {e.static_text}")
        lines.append("")

    # Execution flow around errors
    lines.append("## Execution Flow (around errors)")
    for idx in path.error_points:
        start = max(0, idx - 3)
        end = min(len(path.entries), idx + 3)
        lines.append(f"  --- Around error at index {idx} ---")
        for i in range(start, end):
            e = path.entries[i]
            func = e.originated_from[0] if e.originated_from else "?"
            marker = " <<<ERROR" if i == idx else ""
            lines.append(f"    [{e.level:5}] {func}{marker}")
        lines.append("")

    if path.branches:
        lines.append("## Ambiguity Points")
        for bp in path.branches:
            lines.append(f"  Entry {bp.entry_index}: candidates={bp.candidates}")

    return "\n".join(lines)


def _fallback_assignments(path: WalkablePath, config: DomainConfig) -> list[AgentAssignment]:
    """Fallback: one agent per error point."""
    assignments = []
    for i, idx in enumerate(path.error_points[:config.max_trace_agents]):
        e = path.entries[idx]
        func = e.originated_from[0] if e.originated_from else "unknown"
        assignments.append(AgentAssignment(
            id=f"trace_{i+1}",
            starting_node=func,
            scope=f"Investigate error at L{e.line_number}: {e.static_text}",
            direction="backward",
            model="default",
            tools="graph_only",
        ))
    return assignments
