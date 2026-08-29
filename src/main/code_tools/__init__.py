"""Code graph operations — unified FalkorDB access for MCP tools and trace agents."""

from .graph_conn import get_graph, query
from .queries import (
    get_callers, get_callees, get_class_info, get_inheritance,
    read_source, find_by_pattern, get_call_chain, get_log_templates, get_db_tables,
)
