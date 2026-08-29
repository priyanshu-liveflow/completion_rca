"""Router + Judges — evaluate trace reports from multiple angles, produce final verdict."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.main.shared.llm import call_llm_loop, parse_json
from src.main.shared.base import BlockContext
from src.main.shared.logging import get_logger
from .trace_agent import TraceReport
from .config import DomainConfig
from .models.judges import LensVerdict, FinalVerdict

log = get_logger("judges")

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


# --- Router ---

async def route(
    trace_reports: list[TraceReport],
    config: DomainConfig,
    ctx: BlockContext,
) -> list[str]:
    """Decide which lens judges to spin up based on trace reports."""
    if ctx.verbose:
        log.debug("router_start", reports=len(trace_reports))
    system = _load_prompt("router")
    summary = _build_traces_summary(trace_reports)

    text, metrics = await call_llm_loop(
        provider=ctx.provider,
        system_prompt=system,
        user_message=summary,
        tools=None,
        max_turns=1,
        model=config.model_default,
    )
    ctx.metrics.add(metrics, model=config.model_default)

    if ctx.verbose:
        log.debug("router_tokens", input=metrics.get('input_tokens', 0), output=metrics.get('output_tokens', 0), cache_read=metrics.get('cache_read', 0), cache_write=metrics.get('cache_write', 0))

    parsed = parse_json(text)
    if parsed and "lenses" in parsed:
        lenses = parsed["lenses"][:config.max_lens_judges]
        if ctx.verbose:
            log.debug("router_lenses", lenses=lenses)
        return lenses

    if ctx.verbose:
        log.warning("router_parse_failed")
    return ["general_failure_analysis"]


# --- Lens Judge ---

async def run_lens_judge(
    lens_name: str,
    trace_reports: list[TraceReport],
    jira_context: str | None,
    config: DomainConfig,
    ctx: BlockContext,
) -> LensVerdict:
    """Run a single lens judge."""
    if ctx.verbose:
        log.debug("lens_judge_start", lens=lens_name)
    system = _load_prompt("lens_judge").format(lens_name=lens_name)

    content = _build_traces_summary(trace_reports)
    if jira_context:
        content += f"\n\n## Historical Context (JIRA)\n{jira_context}"

    text, metrics = await call_llm_loop(
        provider=ctx.provider,
        system_prompt=system,
        user_message=content,
        tools=None,
        max_turns=1,
        model=config.model_heavy,
    )
    ctx.metrics.add(metrics, model=config.model_heavy)

    if ctx.verbose:
        log.debug("lens_judge_tokens", lens=lens_name,
                  input=metrics.get('input_tokens', 0),
                  output=metrics.get('output_tokens', 0),
                  cache_read=metrics.get('cache_read', 0),
                  cache_write=metrics.get('cache_write', 0),
                  system_chars=len(system),
                  user_chars=len(content))

    parsed = parse_json(text)
    if parsed:
        v = LensVerdict(
            lens=parsed.get("lens", lens_name),
            verdict=parsed.get("verdict", ""),
            root_cause=parsed.get("root_cause", ""),
            confidence=parsed.get("confidence", 0.5),
            supporting_evidence=parsed.get("supporting_evidence", []),
            contradicting_evidence=parsed.get("contradicting_evidence", []),
            reasoning=parsed.get("reasoning", ""),
        )
        if ctx.verbose:
            log.debug("lens_judge_result", lens=lens_name, confidence=f"{v.confidence:.2f}", root=v.root_cause)
        return v

    return LensVerdict(lens=lens_name, verdict=text, root_cause="", confidence=0.3)


# --- Final Judge ---

async def run_final_judge(
    lens_verdicts: list[LensVerdict],
    trace_reports: list[TraceReport],
    config: DomainConfig,
    ctx: BlockContext,
) -> FinalVerdict:
    """Run the final meta-judge."""
    if ctx.verbose:
        log.debug("final_judge_start", verdicts=len(lens_verdicts), traces=len(trace_reports))
    system = _load_prompt("final_judge")

    content = "## Lens Verdicts\n\n"
    for v in lens_verdicts:
        content += f"### Lens: {v.lens} (confidence: {v.confidence})\n"
        content += f"Verdict: {v.verdict}\n"
        content += f"Root cause: {v.root_cause}\n"
        content += f"Reasoning: {v.reasoning}\n"
        content += f"Supporting: {v.supporting_evidence}\n"
        content += f"Contradicting: {v.contradicting_evidence}\n\n"

    content += "## Original Trace Reports\n\n"
    for r in trace_reports:
        content += f"### Agent: {r.agent_id} (confidence: {r.confidence})\n"
        content += f"Assessment: {r.assessment}\n"
        content += f"Root cause: {r.root_cause_node}\n"
        content += f"Path: {' → '.join(r.path_walked)}\n"
        content += f"Is input issue: {r.is_input_issue}\n\n"

    text, metrics = await call_llm_loop(
        provider=ctx.provider,
        system_prompt=system,
        user_message=content,
        tools=None,
        max_turns=1,
        model=config.model_heavy,
    )
    ctx.metrics.add(metrics, model=config.model_heavy)

    if ctx.verbose:
        log.debug("final_judge_tokens", input=metrics.get('input_tokens', 0), output=metrics.get('output_tokens', 0), cache_read=metrics.get('cache_read', 0), cache_write=metrics.get('cache_write', 0))

    parsed = parse_json(text)
    if parsed:
        verdict = FinalVerdict(
            root_cause=parsed.get("root_cause", ""),
            root_cause_node=parsed.get("root_cause_node"),
            category=parsed.get("category", "unknown"),
            confidence=parsed.get("confidence", 0.5),
            evidence_chain=parsed.get("evidence_chain", []),
            winning_lens=parsed.get("winning_lens", ""),
            explanation=parsed.get("explanation", ""),
            suggested_fix=parsed.get("suggested_fix"),
        )
        if ctx.verbose:
            log.debug("final_judge_result", confidence=f"{verdict.confidence:.2f}", node=verdict.root_cause_node, category=verdict.category)
        return verdict

    return FinalVerdict(
        root_cause=text,
        root_cause_node=None,
        category="unknown",
        confidence=0.3,
        evidence_chain=[],
        winning_lens="",
        explanation="Final judge did not produce structured output",
    )


# --- Helpers ---

def _build_traces_summary(reports: list[TraceReport]) -> str:
    # Only include reports with meaningful findings (confidence > 0.3)
    relevant = [r for r in reports if r.confidence > 0.3]
    if not relevant:
        relevant = reports[:3]  # fallback: at least show top 3

    lines = [f"## Trace Reports ({len(relevant)} of {len(reports)} with confidence > 0.3)\n"]
    for r in relevant:
        lines.append(f"### Agent: {r.agent_id} (confidence: {r.confidence})")
        lines.append(f"Path: {' → '.join(r.path_walked)}")
        lines.append(f"Root cause: {r.root_cause_node or 'not identified'}")
        lines.append(f"Assessment: {r.assessment}")
        if r.evidence:
            lines.append("Evidence:")
            for e in r.evidence:
                lines.append(f"  [{e.type}] {e.location}: {e.content}")
        if r.dead_ends:
            lines.append(f"Dead ends: {', '.join(r.dead_ends)}")
        lines.append("")
    return "\n".join(lines)
