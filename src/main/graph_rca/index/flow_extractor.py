"""Config-driven flow graph extraction — language-agnostic."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from ..models import FlowNode, FlowEdge, FlowGraph

PATTERNS_DIR = Path(__file__).parent.parent.parent.parent.parent / "configs" / "flow_patterns"

# Language → YAML file mapping
LANGUAGE_MAP = {
    "java": "java.yaml", "groovy": "java.yaml", "kotlin": "java.yaml",
    "python": "python.yaml",
    "javascript": "javascript.yaml", "typescript": "javascript.yaml", "jsx": "javascript.yaml", "tsx": "javascript.yaml",
    "go": "go.yaml",
    "rust": "rust.yaml",
    "powershell": "powershell.yaml", "ps1": "powershell.yaml",
    "c": "c.yaml", "cpp": "c.yaml", "c++": "c.yaml", "h": "c.yaml",
}


@dataclass
class BranchDef:
    name: str
    pattern: re.Pattern
    has_condition: bool = False
    condition_delimiters: list[str] | None = None
    terminator: str | None = None
    single_line_allowed: bool = False
    links_to: str | None = None


@dataclass
class FlowPatterns:
    """Compiled patterns from YAML config."""
    block_style: str  # "braces" | "braces_required" | "indent"
    brace_open: str = "{"
    brace_close: str = "}"
    branches: list[BranchDef] = field(default_factory=list)
    returns: list[re.Pattern] = field(default_factory=list)
    log_calls: list[re.Pattern] = field(default_factory=list)
    call_pattern: re.Pattern | None = None
    skip_receivers: set[str] = field(default_factory=set)
    skip_starts: tuple = ()
    continuations: dict[str, bool] = field(default_factory=dict)
    framework_markers: list[str] = field(default_factory=list)
    function_definitions: list[re.Pattern] = field(default_factory=list)


def load_patterns(language: str) -> FlowPatterns:
    """Load and compile flow patterns from YAML config for a language."""
    yaml_file = LANGUAGE_MAP.get(language.lower())
    if not yaml_file:
        yaml_file = "java.yaml"  # fallback

    path = PATTERNS_DIR / yaml_file
    if not path.exists():
        return _default_patterns()

    with open(path) as f:
        cfg = yaml.safe_load(f)

    fp = FlowPatterns(block_style=cfg.get("block_style", "braces"))
    fp.brace_open = cfg.get("brace_open", "{")
    fp.brace_close = cfg.get("brace_close", "}")

    # Compile branch patterns
    for name, bdef in cfg.get("branches", {}).items():
        fp.branches.append(BranchDef(
            name=name,
            pattern=re.compile(bdef["pattern"]),
            has_condition=bdef.get("has_condition", False),
            condition_delimiters=bdef.get("condition_delimiters"),
            terminator=bdef.get("terminator"),
            single_line_allowed=bdef.get("single_line_allowed", False),
            links_to=bdef.get("links_to"),
        ))

    # Compile return patterns
    for pat in cfg.get("returns", []):
        fp.returns.append(re.compile(pat))

    # Compile log patterns
    for pat in cfg.get("log_calls", []):
        fp.log_calls.append(re.compile(pat, re.IGNORECASE))

    # Method call pattern
    mc = cfg.get("method_calls", {})
    if mc.get("pattern"):
        fp.call_pattern = re.compile(mc["pattern"])
    fp.skip_receivers = set(mc.get("skip_receivers", []))
    fp.skip_starts = tuple(mc.get("skip_starts", []))

    # Continuations
    fp.continuations = cfg.get("continuation", {})

    # Framework markers
    fp.framework_markers = cfg.get("framework_markers", [])

    # Function definition patterns
    for pat in cfg.get("function_definitions", []):
        fp.function_definitions.append(re.compile(pat))

    return fp


def _default_patterns() -> FlowPatterns:
    """Fallback Java-like patterns — hardcoded, no file lookup."""
    fp = FlowPatterns(block_style="braces")
    fp.branches = [
        BranchDef(name="if", pattern=re.compile(r'\s*(if|else\s*if)\s*\('), has_condition=True, condition_delimiters=['(', ')'], single_line_allowed=True),
        BranchDef(name="else", pattern=re.compile(r'\s*else\s*[\{]?'), links_to="if"),
        BranchDef(name="try", pattern=re.compile(r'\s*try\s*[\{\(]?')),
        BranchDef(name="catch", pattern=re.compile(r'\s*catch\s*\('), has_condition=True, links_to="try"),
        BranchDef(name="return", pattern=re.compile(r'\s*(return|throw)\b')),
    ]
    fp.log_calls = [
        re.compile(r'\blog\s*\.\s*(trace|debug|info|warn|error|fatal)\s*[\("]', re.IGNORECASE),
    ]
    fp.call_pattern = re.compile(r'(\w+)\s*\.\s*(\w+)\s*\(')
    fp.skip_receivers = {'log', 'logger', 'LOG', 'System', 'this', 'super'}
    fp.skip_starts = ('if', 'else', 'for', 'while', 'switch', 'return', 'throw', 'try', 'catch', '//', '/*', '*')
    return fp


# --- Block Tracking Strategies ---

class BraceTracker:
    """Tracks block depth via brace counting."""

    def __init__(self, open_ch: str = "{", close_ch: str = "}"):
        self.open_ch = open_ch
        self.close_ch = close_ch
        self.depth = 0
        self.branch_depth = 0
        self.branch_at_depth: dict[int, int] = {}

    def update(self, line: str) -> tuple[int, int]:
        """Update depth after processing line. Returns (depth_delta, branch_closes)."""
        opens = line.count(self.open_ch)
        closes = line.count(self.close_ch)
        self.depth += opens - closes
        branch_closes = max(0, closes - opens)
        if branch_closes > 0:
            self.branch_depth = max(0, self.branch_depth - branch_closes)
        return opens - closes, branch_closes

    def register_branch(self, node_id: int):
        """Register a branch node at the next depth level."""
        self.branch_at_depth[self.depth + 1] = node_id
        self.branch_depth += 1

    def get_parent_branch(self, for_type: str = None) -> int | None:
        """Get the parent branch node for a linking construct (else, catch, etc)."""
        return self.branch_at_depth.get(self.depth + 1)


class IndentTracker:
    """Tracks block depth via indentation level changes."""

    def __init__(self):
        self.indent_stack: list[int] = [0]
        self.branch_depth = 0
        self.branch_at_indent: dict[int, int] = {}
        self._unit: int | None = None

    def update(self, line: str) -> tuple[int, int]:
        """Update depth based on indent. Returns (depth_delta, branch_closes)."""
        stripped = line.lstrip()
        if not stripped:
            return 0, 0

        indent = len(line) - len(stripped)

        # Detect indent unit on first indented line
        if self._unit is None and indent > 0:
            self._unit = indent

        if indent > self.indent_stack[-1]:
            self.indent_stack.append(indent)
            return 1, 0
        elif indent < self.indent_stack[-1]:
            closes = 0
            while len(self.indent_stack) > 1 and self.indent_stack[-1] > indent:
                self.indent_stack.pop()
                closes += 1
            self.branch_depth = max(0, self.branch_depth - closes)
            return -closes, closes
        return 0, 0

    def register_branch(self, node_id: int):
        current_indent = self.indent_stack[-1] if self.indent_stack else 0
        self.branch_at_indent[current_indent] = node_id
        self.branch_depth += 1

    def get_parent_branch(self, for_type: str = None) -> int | None:
        if len(self.indent_stack) >= 2:
            parent_indent = self.indent_stack[-2] if len(self.indent_stack) > 1 else 0
            return self.branch_at_indent.get(parent_indent)
        return None

    @property
    def depth(self) -> int:
        return len(self.indent_stack) - 1


# --- Main Extractor ---

class FlowExtractor:
    """Language-agnostic flow graph extractor driven by FlowPatterns config."""

    def __init__(self, patterns: FlowPatterns, language: str = "java"):
        self.p = patterns
        self._language = language
        if patterns.block_style == "indent":
            self.tracker = IndentTracker()
        else:
            self.tracker = BraceTracker(patterns.brace_open, patterns.brace_close)

    def extract(self, source: str, function_name: str) -> FlowGraph:
        """Extract flow graph with proper branch fork/join edges.
        
        Produces:
        - branch nodes with branch_true/branch_false outgoing edges
        - convergence via join edges after branch blocks close
        - call nodes reference callees (no expansion)
        - return/throw mark exit points (subsequent code is dead)
        """
        fg = FlowGraph(function_name=function_name)
        lines = self._join_continuations(source.split('\n'))

        self._node_id = 0
        self._prev: Optional[int] = None
        self._branch_join: Optional[int] = None
        # Stack of branch contexts: (branch_node_id, depth_when_opened)
        self._branch_stack: list[tuple[int, int, str]] = []  # (node_id, open_depth, type)
        self._depth = 0

        for line_idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or self._is_comment(stripped):
                # Still need to track braces in blank/comment lines
                if self.p.block_style != "indent":
                    self._update_depth(line, fg)
                continue

            line_num = line_idx + 1

            processed = False

            # 1. Returns/throws — mark exit
            if not processed:
                for ret_pat in self.p.returns:
                    if ret_pat.match(line):
                        rtype = "throw" if "throw" in stripped or "raise" in stripped or "panic" in stripped else "return"
                        self._add_node(fg, FlowNode(
                            id=self._node_id, type=rtype, line=line_num,
                            branch_depth=len(self._branch_stack)))
                        fg.exit_nodes.append(self._node_id - 1)
                        self._prev = None
                        processed = True
                        break

            # 2. Branch patterns
            if not processed:
                for bdef in self.p.branches:
                    if bdef.pattern.match(line):
                        condition = self._extract_condition(line, bdef) if bdef.has_condition else ""
                        node = FlowNode(
                            id=self._node_id, type="branch", line=line_num,
                            branch_type=bdef.name, condition=condition,
                            branch_depth=len(self._branch_stack))

                        if bdef.links_to:
                            # else/catch — connects to parent branch as alternate path
                            fg.nodes.append(node)
                            if self._branch_stack:
                                parent_id = self._branch_stack[-1][0]
                                edge_type = "exception" if bdef.name in ("catch", "finally") else "branch_false"
                                fg.edges.append(FlowEdge(src=parent_id, dst=self._node_id, edge_type=edge_type))
                            self._prev = self._node_id
                            self._node_id += 1
                        else:
                            # New fork point — push onto stack
                            self._add_node(fg, node)
                            branch_id = self._node_id - 1
                            self._branch_stack.append((branch_id, self._depth, bdef.name))

                        processed = True
                        break

            # 3. Log calls
            if not processed:
                level, text, frags = self._detect_log(line)
                if level:
                    self._add_node(fg, FlowNode(
                        id=self._node_id, type="log", line=line_num,
                        log_level=level, log_text=text,
                        branch_depth=len(self._branch_stack)))
                    # Store fragments for template generation
                    fg.nodes[-1]._fragments = frags
                    processed = True

            # 4. Method calls — reference only, don't expand
            if not processed:
                target = self._detect_call(line)
                if target:
                    self._add_node(fg, FlowNode(
                        id=self._node_id, type="call", line=line_num,
                        call_target=target,
                        branch_depth=len(self._branch_stack)))
                    processed = True

            # Update depth and check for branch closures
            if self.p.block_style != "indent":
                self._update_depth(line, fg)
            else:
                self.tracker.update(line)

        # Finalize
        if fg.nodes:
            fg.entry_node = fg.nodes[0].id
            if not fg.exit_nodes:
                fg.exit_nodes = [fg.nodes[-1].id]

        return fg

    def _update_depth(self, line: str, fg: FlowGraph):
        """Update brace depth; pop branch stack when blocks close."""
        import re
        clean = re.sub(r'"[^"]*"', '', line)
        clean = re.sub(r"'[^']*'", '', clean)
        for ch in clean:
            if ch == '{':
                self._depth += 1
            elif ch == '}':
                self._depth -= 1
                if self._branch_stack and self._depth == self._branch_stack[-1][1]:
                    branch_id, _, btype = self._branch_stack.pop()
                    # After branch closes, next node must be reachable from BOTH:
                    # - the last node in the body (_prev if not None)
                    # - the branch node itself (fallthrough/false path)
                    # Store branch_id so _add_node can create both edges
                    if self._prev is None:
                        self._prev = branch_id
                    else:
                        # Both body-end and branch-fallthrough should connect to next
                        self._branch_join = branch_id

    def _add_node(self, fg: FlowGraph, node: FlowNode):
        """Add node and edge from previous."""
        fg.nodes.append(node)
        if self._prev is not None:
            fg.edges.append(FlowEdge(src=self._prev, dst=self._node_id))
        # Also connect fallthrough from branch that just closed (if-without-else)
        if hasattr(self, '_branch_join') and self._branch_join is not None:
            fg.edges.append(FlowEdge(src=self._branch_join, dst=self._node_id, edge_type="branch_false"))
            self._branch_join = None
        self._prev = self._node_id
        self._node_id += 1

    def _detect_log(self, line: str) -> tuple[str, str, list[str]]:
        """Match line against configured log patterns. Returns (level, text, static_fragments).
        
        Uses the same extraction logic as lite_index for fragment consistency.
        """
        for p in self.p.log_calls:
            m = p.search(line)
            if not m:
                continue

            level = m.group(1).lower() if m.lastindex else "info"
            # If pattern ended at a quote (no-paren Groovy: log.debug "text"),
            # back up so the quote is included in full_stmt for string extraction
            end_pos = m.end()
            if end_pos > 0 and line[end_pos - 1] == '"':
                end_pos -= 1
            full_stmt = line[end_pos:]

            # Extract quoted string (same as lite_index)
            str_match = re.search(r'"([^"]*(?:"[^"]*)*[^"]*)"', full_stmt)
            if not str_match:
                str_match = re.search(r"'([^']*)'", full_stmt)
            if not str_match:
                return level, "", []

            log_content = str_match.group(1)

            # Use lite_index's fragment extraction for consistency
            from .lite_index import _extract_fragments
            frags, _ = _extract_fragments(log_content, self._language)
            text = ''.join(frags) if frags else log_content
            return level, text.strip(), frags
        return "", "", []

    def _detect_call(self, line: str) -> str:
        """Match line against configured call pattern. Returns target or ''."""
        stripped = line.strip()
        if stripped.startswith(self.p.skip_starts):
            return ""
        if not self.p.call_pattern:
            return ""
        m = self.p.call_pattern.search(stripped)
        if m:
            receiver = m.group(1)
            if receiver in self.p.skip_receivers:
                return ""
            method = m.group(2) if m.lastindex >= 2 else m.group(1)
            return f"{receiver}.{method}"
        return ""

    def _extract_condition(self, line: str, bdef: BranchDef) -> str:
        """Extract condition text from a branch line."""
        if bdef.condition_delimiters:
            open_d, close_d = bdef.condition_delimiters
            start = line.find(open_d)
            end = line.rfind(close_d)
            if start >= 0 and end > start:
                return line[start+1:end][:80]
        elif bdef.terminator:
            # Python-style: condition is between keyword and terminator
            m = bdef.pattern.match(line)
            if m:
                after = line[m.end():]
                idx = after.rfind(bdef.terminator)
                if idx > 0:
                    return after[:idx].strip()[:80]
        return ""

    def _join_continuations(self, lines: list[str]) -> list[str]:
        """Merge multi-line statements based on continuation rules."""
        if not self.p.continuations:
            return lines

        merged = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # Check if this line continues to next
            while i + 1 < len(lines) and self._is_continuation(line):
                i += 1
                line = line.rstrip().rstrip('\\') + ' ' + lines[i].strip()
            merged.append(line)
            i += 1
        return merged

    def _is_continuation(self, line: str) -> bool:
        """Check if line continues to next based on configured rules."""
        stripped = line.rstrip()
        if not stripped:
            return False

        c = self.p.continuations
        if c.get("trailing_backslash") and stripped.endswith('\\'):
            return True
        if c.get("trailing_operator") and stripped[-1] in ('+', '&', '|', '.') and not stripped.endswith('{'):
            return True
        if c.get("trailing_comma") and stripped.endswith(','):
            return True
        if c.get("trailing_pipe") and stripped.endswith('|'):
            return True
        if c.get("trailing_backtick") and stripped.endswith('`'):
            return True
        if c.get("trailing_arrow") and stripped.endswith('=>'):
            return True
        if c.get("trailing_open_paren") or c.get("unclosed_bracket"):
            # Only count parens/brackets, NOT braces (those are block delimiters)
            opens = stripped.count('(') + stripped.count('[')
            closes = stripped.count(')') + stripped.count(']')
            if opens > closes:
                return True
        return False

    def _is_comment(self, stripped: str) -> bool:
        """Check if line is a comment."""
        return stripped.startswith(('//', '/*', '*/', '*', '#')) and not stripped.startswith('#!')


def extract_flow_graph(source: str, function_name: str, language: str = "java") -> FlowGraph:
    """Convenience function: load patterns for language and extract."""
    patterns = load_patterns(language)
    extractor = FlowExtractor(patterns, language)
    return extractor.extract(source, function_name)
