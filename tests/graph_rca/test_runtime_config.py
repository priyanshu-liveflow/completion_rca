"""Runtime YAML overlays must merge, not replace, the default model map."""

from pathlib import Path

from src.main.graph_rca.runtime_config import _DEFAULT_MODELS, RuntimeConfig


def test_absent_models_keeps_defaults(tmp_path: Path) -> None:
    path = tmp_path / "rt.yaml"
    path.write_text("provider: ollama\n", encoding="utf-8")
    rt = RuntimeConfig.from_yaml(path)
    assert rt.provider == "ollama"
    assert rt.models == _DEFAULT_MODELS


def test_partial_models_keeps_omitted_defaults(tmp_path: Path) -> None:
    path = tmp_path / "rt.yaml"
    path.write_text("provider: ollama\nmodels:\n  light: gemma3:4b\n", encoding="utf-8")
    rt = RuntimeConfig.from_yaml(path)
    assert rt.models["light"] == "gemma3:4b"
    assert rt.models["default"] == _DEFAULT_MODELS["default"]
    assert rt.models["heavy"] == _DEFAULT_MODELS["heavy"]
    assert rt.models["router"] == _DEFAULT_MODELS["router"]
