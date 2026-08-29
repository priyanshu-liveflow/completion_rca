"""Runtime configuration — models, budgets, provider settings.

Loaded from configs/runtime/*.yaml. Independent of repo config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class RuntimeConfig:
    """Provider, model, and budget settings. Shared across all repos."""
    provider: str = "aws"
    models: dict[str, str] = field(default_factory=lambda: {
        "light": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "default": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "heavy": "us.anthropic.claude-opus-4-6-v1",
        "router": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    })
    max_trace_agents: int = 5
    max_turns_per_agent: int = 12
    extension_turns: int = 5
    max_lens_judges: int = 4
    budget_cap_usd: float = 2.0
    early_exit_confidence: float = 0.95
    skip_heavy_model_if_obvious: bool = True
    # Ollama-specific
    ollama_base_url: str = "http://localhost:11434"
    num_ctx: int = 32768

    @property
    def model_light(self) -> str:
        return self.models.get("light", self.models.get("default", ""))

    @property
    def model_default(self) -> str:
        return self.models.get("default", "")

    @property
    def model_heavy(self) -> str:
        return self.models.get("heavy", self.models.get("default", ""))

    @property
    def model_router(self) -> str:
        return self.models.get("router", self.models.get("light", ""))

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RuntimeConfig":
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls(
            provider=data.get("provider", cls.provider),
            models=data.get("models", {}),
            max_trace_agents=data.get("budget", {}).get("max_trace_agents", cls.max_trace_agents),
            max_turns_per_agent=data.get("budget", {}).get("max_turns_per_agent", cls.max_turns_per_agent),
            extension_turns=data.get("budget", {}).get("extension_turns", cls.extension_turns),
            max_lens_judges=data.get("budget", {}).get("max_lens_judges", cls.max_lens_judges),
            budget_cap_usd=data.get("budget", {}).get("budget_cap_usd", cls.budget_cap_usd),
            early_exit_confidence=data.get("budget", {}).get("early_exit_confidence", cls.early_exit_confidence),
            skip_heavy_model_if_obvious=data.get("budget", {}).get("skip_heavy_model_if_obvious", cls.skip_heavy_model_if_obvious),
            ollama_base_url=data.get("ollama_base_url", cls.ollama_base_url),
            num_ctx=data.get("context", {}).get("num_ctx", cls.num_ctx),
        )

    @classmethod
    def default(cls) -> "RuntimeConfig":
        """Load default runtime config (bedrock)."""
        default_path = Path(__file__).parent.parent.parent.parent / "configs" / "runtime" / "bedrock.yaml"
        if default_path.exists():
            return cls.from_yaml(default_path)
        return cls()
