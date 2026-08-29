"""Index package — builds and caches flow graphs + log templates."""
from .cache import is_stale, get_commit_hash, save_cache, load_cache
from .lite_index import extract_log_templates, _extract_fragments
from .flow_extractor import extract_flow_graph, load_patterns
from .flow_builder import build_flow_index
from .classifier import classify_node, classify_all
from .supplement import _find_function_end
from .indexer import index_repo, check_and_reindex
