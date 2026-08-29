"""Resolve package — log entry to function resolution."""
from .resolver import resolve_entries
from .trie import FragmentTrie
from .class_resolver import extract_logger_class, find_by_class, is_framework_log
