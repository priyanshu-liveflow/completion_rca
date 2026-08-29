"""Visualize walkable path and trace agent results as SVG using graphviz."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import graphviz

from .models import WalkablePath
from .trace_agent import TraceReport
from .judges import FinalVerdict

BASE_OUTPUT = Path(__file__).resolve().parent.parent.parent.parent / "output" / "images"


def _ensure_output_dir(output_dir: str = "") -> Path:
    d = Path(output_dir) if output_dir else BASE_OUTPUT
    d.mkdir(parents=True, exist_ok=True)
    return d


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


TIER_COLORS = {
    1: "#4CAF50",  # green — stack trace
    2: "#2196F3",  # blue — unique match
    3: "#FFC107",  # yellow — contextual
    4: "#9E9E9E",  # gray — unmapped
}


def render_walkable_path(path: WalkablePath, output_dir: str = "") -> str:
    """Render the walkable path as an SVG. Returns path to SVG file."""
    out_dir = _ensure_output_dir(output_dir)
    ts = _timestamp()
    dot = graphviz.Digraph("walkable_path", format="svg")
    dot.attr(rankdir="TB", fontname="Helvetica", fontsize="10")
    dot.attr("node", shape="box", style="rounded,filled", fontname="Helvetica", fontsize="9")
    dot.attr("edge", fontname="Helvetica", fontsize="8")

    for i, entry in enumerate(path.entries):
        func = entry.originated_from[0] if entry.originated_from else "UNMAPPED"
        # Truncate for display
        label = f"L{entry.line_number} [{entry.level}]\n{func.split('.')[-1]}"

        color = TIER_COLORS.get(entry.resolution_tier, "#9E9E9E")
        border = "red" if i in path.error_points else "#333333"
        penwidth = "2.5" if i in path.error_points else "1"

        dot.node(str(i), label=label, fillcolor=color, color=border, penwidth=penwidth)

        if i > 0:
            dot.edge(str(i - 1), str(i))

    # Mark branches
    for bp in path.branches:
        for candidate in bp.candidates[1:]:
            dot.node(f"branch_{bp.entry_index}_{candidate}", label=f"? {candidate.split('.')[-1]}",
                     fillcolor="#FFF9C4", style="rounded,filled,dashed")
            dot.edge(str(bp.entry_index), f"branch_{bp.entry_index}_{candidate}", style="dashed", color="#999")

    # Legend
    with dot.subgraph(name="cluster_legend") as legend:
        legend.attr(label="Legend", style="rounded", color="#999")
        legend.node("leg1", "Tier 1: Stack trace", fillcolor=TIER_COLORS[1])
        legend.node("leg2", "Tier 2: Unique match", fillcolor=TIER_COLORS[2])
        legend.node("leg3", "Tier 3: Contextual", fillcolor=TIER_COLORS[3])
        legend.node("leg4", "Tier 4: Unmapped", fillcolor=TIER_COLORS[4])
        legend.node("leg5", "ERROR", fillcolor="white", color="red", penwidth="2.5")

    out = Path(out_dir) / f"walkable_path_{ts}"
    dot.render(str(out), cleanup=True)
    return f"{out}.svg"


def render_traces(trace_reports: list[TraceReport], output_dir: str = "") -> str:
    """Render all trace agent paths in one SVG. Returns path to SVG file."""
    out_dir = _ensure_output_dir(output_dir)
    ts = _timestamp()
    dot = graphviz.Digraph("trace_agents", format="svg")
    dot.attr(rankdir="LR", fontname="Helvetica", fontsize="10")
    dot.attr("node", shape="box", style="rounded,filled", fontname="Helvetica", fontsize="9")

    colors = ["#E3F2FD", "#FFF3E0", "#E8F5E9", "#FCE4EC", "#F3E5F5"]

    for idx, report in enumerate(trace_reports):
        color = colors[idx % len(colors)]
        with dot.subgraph(name=f"cluster_{report.agent_id}") as sub:
            sub.attr(label=f"{report.agent_id} (conf={report.confidence:.2f})", style="rounded", color="#666")

            for j, node in enumerate(report.path_walked):
                node_id = f"{report.agent_id}_{j}"
                short = node.split(".")[-1] if "." in node else node
                is_root = node == report.root_cause_node
                sub.node(node_id, label=short,
                         fillcolor="#FF5252" if is_root else color,
                         fontcolor="white" if is_root else "black",
                         penwidth="2.5" if is_root else "1")
                if j > 0:
                    sub.edge(f"{report.agent_id}_{j-1}", node_id)

            # Dead ends
            for k, dead in enumerate(report.dead_ends):
                dead_id = f"{report.agent_id}_dead_{k}"
                short = dead.split(".")[-1] if "." in dead else dead
                sub.node(dead_id, label=f"✗ {short}", fillcolor="#FFCDD2", style="rounded,filled,dashed")

    out = Path(out_dir) / f"trace_agents_{ts}"
    dot.render(str(out), cleanup=True)
    return f"{out}.svg"


def render_verdict(verdict: FinalVerdict, trace_reports: list[TraceReport], output_dir: str = "") -> str:
    """Render the final RCA verdict as a propagation tree SVG."""
    out_dir = _ensure_output_dir(output_dir)
    ts = _timestamp()
    dot = graphviz.Digraph("rca_verdict", format="svg")
    dot.attr(rankdir="TB", fontname="Helvetica", fontsize="10")
    dot.attr("node", shape="box", style="rounded,filled", fontname="Helvetica", fontsize="9")

    # Root cause node
    root_short = verdict.root_cause_node.split(".")[-1] if verdict.root_cause_node and "." in verdict.root_cause_node else (verdict.root_cause_node or "?")
    dot.node("root", label=f"ROOT CAUSE\n{root_short}\n\nconf={verdict.confidence:.0%}\n{verdict.category}",
             fillcolor="#FF5252", fontcolor="white", shape="doubleoctagon")

    # Evidence chain
    for i, evidence in enumerate(verdict.evidence_chain):
        short = evidence[:60].replace("\n", " ")
        dot.node(f"ev_{i}", label=short, fillcolor="#FFECB3")
        if i == 0:
            dot.edge("root", f"ev_{i}", label="evidence")
        else:
            dot.edge(f"ev_{i-1}", f"ev_{i}")

    # Trace convergence
    for report in trace_reports:
        if report.confidence >= 0.5 and report.root_cause_node:
            short = report.root_cause_node.split(".")[-1] if "." in report.root_cause_node else report.root_cause_node
            node_id = f"trace_{report.agent_id}"
            dot.node(node_id, label=f"{report.agent_id}\n{short}\nconf={report.confidence:.2f}",
                     fillcolor="#E3F2FD")
            dot.edge(node_id, "root", style="dashed", label=f"{report.confidence:.0%}")

    # Suggested fix
    if verdict.suggested_fix:
        dot.node("fix", label=f"FIX: {verdict.suggested_fix[:80]}...", fillcolor="#C8E6C9", shape="note")
        dot.edge("root", "fix", style="dotted")

    out = Path(out_dir) / f"rca_verdict_{ts}"
    dot.render(str(out), cleanup=True)
    return f"{out}.svg"
