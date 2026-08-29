"""Block protocol and execution context.

A Block is the smallest reusable unit in the system:
- Has a name, a prompt, typed I/O, a tool list, and a model hint
- Runs independently — no knowledge of other blocks
- Can be wired into any pipeline via a DAG runner

BlockContext carries everything a block needs to execute without
knowing about the broader system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from src.main.shared.providers.base import BaseLLMProvider


@dataclass
class RunMetrics:
    """Accumulated metrics across a pipeline run."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    turns: int = 0
    by_model: dict = field(default_factory=dict)  # model_id → {input, output, cache_read, cache_write, turns}

    def add(self, metrics: dict, model: str = ""):
        self.input_tokens += metrics.get("input_tokens", 0)
        self.output_tokens += metrics.get("output_tokens", 0)
        self.cache_read += metrics.get("cache_read", 0)
        self.cache_write += metrics.get("cache_write", 0)
        self.turns += metrics.get("turns", 0)
        if model:
            if model not in self.by_model:
                self.by_model[model] = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0, "turns": 0}
            m = self.by_model[model]
            m["input_tokens"] += metrics.get("input_tokens", 0)
            m["output_tokens"] += metrics.get("output_tokens", 0)
            m["cache_read"] += metrics.get("cache_read", 0)
            m["cache_write"] += metrics.get("cache_write", 0)
            m["turns"] += metrics.get("turns", 0)


@dataclass
class BlockContext:
    """Everything a block needs to execute. Passed by the pipeline runner."""
    provider: BaseLLMProvider
    domain: str = ""
    dispatcher: Any = None  # scoped tool dispatcher (only tools this block declared)
    metrics: RunMetrics = field(default_factory=RunMetrics)
    verbose: bool = False

    def log(self, msg: str):
        if self.verbose:
            from src.main.shared.logging import get_logger
            get_logger("block_context").info(msg)


@runtime_checkable
class Block(Protocol):
    """Protocol that all blocks implement."""

    name: str
    description: str
    tools: list[str]        # tool names this block may call (empty = no tools)
    model_hint: str         # "small" | "large" | specific model id | "" for default
    max_turns: int          # LLM-loop budget

    async def run(self, ctx: BlockContext, **inputs) -> dict[str, Any]:
        """Execute the block. Returns structured output as a dict."""
        ...
