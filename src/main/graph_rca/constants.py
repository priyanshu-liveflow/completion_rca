"""Constants and environment configuration — single source of truth."""
import os

# ── Embedding model ──
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
EMBED_DIM = 384
EMBED_DEVICE = "cpu"

# ── HuggingFace / tokenizers noise suppression ──
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
