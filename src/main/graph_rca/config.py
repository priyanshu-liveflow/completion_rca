"""Domain config for the code-graph RCA analyzer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base. Lists are replaced, dicts are merged recursively."""
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _ensure_list(val) -> list[str]:
    """Normalize language field: str → [str], list stays list."""
    if isinstance(val, str):
        return [val]
    if isinstance(val, list):
        return val
    return ["java"]


@dataclass
class LogFormat:
    type: str = "text"  # text | json
    entry_start: str = r"^\d{4}-\d{2}-\d{2}"
    line_pattern: str | None = None
    alt_patterns: list[str] = field(default_factory=list)
    message_separators: list[str] = field(default_factory=lambda: [' : ', ' - '])
    continuation_patterns: list[str] = field(default_factory=lambda: [
        r'^\s+at\s+', r'^\s+\.\.\.\s+\d+\s+more', r'^Caused by:', r'^\t',
    ])
    group_by_thread: bool = True
    thread_field: str = "thread"
    error_levels: list[str] = field(default_factory=lambda: ["error", "fatal"])
    # JSON mode
    field_map: dict[str, str] = field(default_factory=dict)
    field_aliases: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "LogFormat":
        return cls(
            type=data.get("type", "text"),
            entry_start=data.get("entry_start", r"^\d{4}-\d{2}-\d{2}"),
            line_pattern=data.get("line_pattern"),
            alt_patterns=data.get("alt_patterns", []),
            message_separators=data.get("message_separators", [' : ', ' - ']),
            continuation_patterns=data.get("continuation_patterns", [
                r'^\s+at\s+', r'^\s+\.\.\.\s+\d+\s+more', r'^Caused by:', r'^\t',
            ]),
            group_by_thread=data.get("group_by_thread", True),
            thread_field=data.get("thread_field", "thread"),
            error_levels=data.get("error_levels", ["error", "fatal"]),
            field_map=data.get("field_map", {}),
            field_aliases=data.get("field_aliases", {}),
        )


@dataclass
class StackTraceConfig:
    format: str = "java"
    frame_pattern: str | None = None
    caused_by_pattern: str | None = None
    exception_pattern: str | None = None
    location_pattern: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "StackTraceConfig":
        return cls(
            format=data.get("format", "java"),
            frame_pattern=data.get("frame_pattern"),
            caused_by_pattern=data.get("caused_by_pattern"),
            exception_pattern=data.get("exception_pattern"),
            location_pattern=data.get("location_pattern"),
        )


@dataclass
class DomainConfig:
    repo: str = ""
    branch: str = ""
    language: list[str] = field(default_factory=lambda: ["java"])
    service_name: str | None = None
    ignore_patterns: list[str] = field(default_factory=list)
    known_errors: list[dict[str, str]] = field(default_factory=list)
    error_markers: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    # Log format
    log_format: LogFormat = field(default_factory=LogFormat)
    stack_trace: StackTraceConfig = field(default_factory=StackTraceConfig)
    # Log extraction (for lite index building)
    log_extraction_patterns: list[str] = field(default_factory=list)
    # Models (set from RuntimeConfig overlay, defaults kept for backward compat)
    model_light: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    model_default: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    model_heavy: str = "us.anthropic.claude-opus-4-6-v1"
    model_router: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    # Budget
    max_trace_agents: int = 5
    max_turns_per_agent: int = 12
    max_lens_judges: int = 4
    budget_cap_usd: float = 2.0
    early_exit_confidence: float = 0.95
    skip_judges_if_single_trace: bool = True
    skip_heavy_model_if_obvious: bool = True

    # Backward-compat properties
    @property
    def entry_start(self) -> str:
        return self.log_format.entry_start

    @property
    def thread_id_pattern(self) -> str | None:
        return None

    @property
    def service_id_pattern(self) -> str | None:
        return None

    @property
    def logger_class_pattern(self) -> str | None:
        # Derived from line_pattern — extract the logger group
        if self.log_format.line_pattern and '(?P<logger>' in self.log_format.line_pattern:
            return self.log_format.line_pattern
        return r'\]\s+([\w.$]+)\s+:'

    @classmethod
    def from_yaml(cls, path: str | Path) -> "DomainConfig":
        """Load config from YAML file, resolving extends."""
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f) or {}

        # Resolve extends
        if "extends" in data:
            base_path = path.parent / data.pop("extends")
            with open(base_path) as f:
                base_data = yaml.safe_load(f) or {}
            data = _deep_merge(base_data, data)

        log_fmt = data.get("log_format", {})
        cost = data.get("cost_limits", {})
        models = data.get("models", {})
        stack = data.get("stack_trace", {})

        return cls(
            repo=data.get("repo", ""),
            branch=data.get("branch", ""),
            language=_ensure_list(data.get("language", ["java"])),
            service_name=data.get("service_name"),
            ignore_patterns=data.get("ignore_patterns", []),
            known_errors=data.get("known_errors", []),
            error_markers=[m.get("pattern", "") if isinstance(m, dict) else m for m in data.get("error_markers", [])],
            entry_points=data.get("entry_points", []),
            log_format=LogFormat.from_dict(log_fmt),
            stack_trace=StackTraceConfig.from_dict(stack),
            log_extraction_patterns=data.get("log_extraction", {}).get("extra_patterns", []),
            model_light=models.get("light", cls.model_light),
            model_default=models.get("default", cls.model_default),
            model_heavy=models.get("heavy", cls.model_heavy),
            model_router=models.get("router", cls.model_router),
            max_trace_agents=cost.get("max_trace_agents", cls.max_trace_agents),
            max_turns_per_agent=cost.get("max_turns_per_agent", cls.max_turns_per_agent),
            max_lens_judges=cost.get("max_lens_judges", cls.max_lens_judges),
            budget_cap_usd=cost.get("budget_cap_usd", cls.budget_cap_usd),
            early_exit_confidence=cost.get("early_exit_confidence", cls.early_exit_confidence),
            skip_judges_if_single_trace=data.get("skip_judges_if_single_trace", cls.skip_judges_if_single_trace),
        )

    def apply_runtime(self, runtime_path: str | Path | None = None):
        """Overlay runtime config (models, budget) onto this config. Mutates self."""
        from .runtime_config import RuntimeConfig
        rt = RuntimeConfig.from_yaml(runtime_path) if runtime_path else RuntimeConfig.default()
        self.model_light = rt.model_light
        self.model_default = rt.model_default
        self.model_heavy = rt.model_heavy
        self.model_router = rt.model_router
        self.max_trace_agents = rt.max_trace_agents
        self.max_turns_per_agent = rt.max_turns_per_agent
        self.max_lens_judges = rt.max_lens_judges
        self.budget_cap_usd = rt.budget_cap_usd
        self.early_exit_confidence = rt.early_exit_confidence
        self.skip_heavy_model_if_obvious = rt.skip_heavy_model_if_obvious

    @classmethod
    def minimal(cls, repo: str, entry_start: str = r"^\d{4}-\d{2}-\d{2}") -> "DomainConfig":
        """Create minimal config with just repo and entry pattern."""
        lf = LogFormat(entry_start=entry_start)
        return cls(repo=repo, log_format=lf)
