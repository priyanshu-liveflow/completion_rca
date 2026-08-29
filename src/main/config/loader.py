"""Config loader — mirrors CUAIntegrationAgent's CUAConfigsLoader pattern exactly.

Reads JSON config files from config/jsons/, resolves each key from its env var
(with a typed default), and caches the result for the process lifetime.
"""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

load_dotenv()

_CONFIG_FILES = ["basic.json", "aws.json", "azure.json"]


@lru_cache(maxsize=1)
def get_analyzer_configs() -> Dict[str, Any]:
    """Load and cache all config sections, then merge the active cloud provider config."""
    loader = _ConfigsLoader()
    return loader.load()


def get_cloud_provider_configs() -> Dict[str, Any]:
    all_configs = get_analyzer_configs()
    cloud_provider = all_configs["basic"]["cloud_provider"]
    return all_configs[cloud_provider]


class _ConfigsLoader:
    def load(self) -> Dict[str, Any]:
        base_dir = os.getenv("CONFIG_DIR", "")
        if not base_dir:
            base_dir = Path(__file__).resolve().parent / "jsons"

        all_configs: Dict[str, Any] = {}
        for filename in _CONFIG_FILES:
            key = Path(filename).stem
            all_configs[key] = self._load_file(Path(base_dir) / filename)

        return all_configs

    def _load_file(self, json_path: Path) -> Dict[str, Any]:
        with json_path.open() as f:
            raw = json.load(f)

        resolved: Dict[str, Any] = {}
        for key, meta in raw.items():
            env_key = meta.get("env")
            default = meta.get("default")
            required = meta.get("required", False)
            target_type = meta.get("type", "str")

            raw_value = os.getenv(env_key, default) if env_key else default

            if raw_value is None and required:
                raise RuntimeError(f"Missing required env variable: {env_key}")

            try:
                resolved[key] = self._cast(raw_value, target_type)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to cast config key '{key}' (env={env_key}) "
                    f"to type '{target_type}': {exc}"
                ) from exc

        return resolved

    @staticmethod
    def _cast(value: Any, target_type: str) -> Any:
        if value is None:
            return None
        if target_type == "str":
            return str(value)
        if target_type == "int":
            return int(value)
        if target_type == "float":
            return float(value)
        if target_type == "bool":
            if isinstance(value, bool):
                return value
            return str(value).lower() in {"true", "1", "yes", "y"}
        if target_type == "list":
            if isinstance(value, list):
                return value
            return json.loads(value)
        if target_type == "dict":
            if isinstance(value, dict):
                return value
            return json.loads(value)
        raise ValueError(f"Unsupported config type: {target_type}")
