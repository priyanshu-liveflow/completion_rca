"""Trace agent tool definitions and dispatch — consumed by graph_rca/trace_agent.py."""

from __future__ import annotations

import json

from . import queries

TOOLS = [
    {
        "name": "read_function_source",
        "description": "Read the source code of a function. Use fid (preferred) or function_name. fid is unambiguous — use it when available from prior tool responses.",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {"type": "string"},
                "fid": {"type": "integer", "description": "Function ID (from prior tool responses). Preferred over function_name."},
                "max_chars": {"type": "integer", "description": "Max characters to return. Default 1000."},
                "offset": {"type": "integer", "description": "Character offset to start reading from. Default 0."},
            },
            "required": [],
        },
    },
    {
        "name": "get_callers",
        "description": "Get functions that call this function. Returns [{name, fid}, ...]. Use fid to avoid ambiguity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {"type": "string"},
                "fid": {"type": "integer", "description": "Function ID (preferred)."},
            },
            "required": [],
        },
    },
    {
        "name": "get_callees",
        "description": "Get functions that this function calls. Returns [{name, fid}, ...]. Use fid to avoid ambiguity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {"type": "string"},
                "fid": {"type": "integer", "description": "Function ID (preferred)."},
            },
            "required": [],
        },
    },
    {
        "name": "get_class_info",
        "description": "Get class details: methods (with fids), injected dependencies, parent classes",
        "input_schema": {
            "type": "object",
            "properties": {"class_name": {"type": "string"}},
            "required": ["class_name"],
        },
    },
    {
        "name": "get_inheritance",
        "description": "Get parent and child classes in the inheritance chain",
        "input_schema": {
            "type": "object",
            "properties": {"class_name": {"type": "string"}},
            "required": ["class_name"],
        },
    },
    {
        "name": "get_db_tables",
        "description": "Get database tables that a function reads from or writes to. Use fid to avoid ambiguity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {"type": "string"},
                "fid": {"type": "integer", "description": "Function ID (preferred)."},
            },
            "required": [],
        },
    },
    {
        "name": "find_function_by_pattern",
        "description": "Search for functions whose name matches a pattern. Returns [{name, fid}, ...].",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Substring to search for in function names"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "get_call_chain",
        "description": "Get the shortest call chain from one function to another. Returns [{name, fid}, ...].",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_function": {"type": "string"},
                "to_function": {"type": "string"},
                "max_hops": {"type": "integer", "description": "Max depth to search. Default 4."},
            },
            "required": ["from_function", "to_function"],
        },
    },
    {
        "name": "get_log_templates",
        "description": "Get all log templates emitted by a function. Use fid to avoid ambiguity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {"type": "string"},
                "fid": {"type": "integer", "description": "Function ID (preferred)."},
            },
            "required": [],
        },
    },
]


def handle_tool_call(tool_name: str, tool_input: dict, repo_path: str) -> str:
    """Dispatch a tool call to the appropriate query function. Returns string result."""
    repo_key = repo_path.split("/")[-1]
    fid = tool_input.get("fid")  # fid always takes priority when provided
    if fid is not None:
        fid = int(fid)

    if tool_name == "read_function_source":
        return queries.read_source(
            tool_input.get("function_name", ""), repo_key,
            max_chars=tool_input.get("max_chars", 1000),
            offset=tool_input.get("offset", 0),
            fid=fid,
        )

    elif tool_name == "get_callers":
        callers = queries.get_callers(tool_input.get("function_name", ""), repo_key, fid=fid)
        return json.dumps({"callers": callers}) if callers else f"No callers found for '{tool_input.get('function_name', fid)}'"

    elif tool_name == "get_callees":
        callees = queries.get_callees(tool_input.get("function_name", ""), repo_key, fid=fid)
        return json.dumps({"callees": callees}) if callees else f"No callees found for '{tool_input.get('function_name', fid)}'"

    elif tool_name == "get_class_info":
        return json.dumps(queries.get_class_info(tool_input["class_name"], repo_key))

    elif tool_name == "get_inheritance":
        return json.dumps(queries.get_inheritance(tool_input["class_name"], repo_key))

    elif tool_name == "get_db_tables":
        return json.dumps(queries.get_db_tables(tool_input.get("function_name", ""), repo_key, fid=fid))

    elif tool_name == "find_function_by_pattern":
        matches = queries.find_by_pattern(tool_input["pattern"], repo_key)
        return json.dumps({"pattern": tool_input["pattern"], "matches": matches})

    elif tool_name == "get_call_chain":
        chain = queries.get_call_chain(
            tool_input["from_function"], tool_input["to_function"],
            repo_key, max_hops=tool_input.get("max_hops", 4),
        )
        if chain:
            return json.dumps({"chain": chain})
        return json.dumps({"chain": None, "note": f"No path found within {tool_input.get('max_hops', 4)} hops"})

    elif tool_name == "get_log_templates":
        templates = queries.get_log_templates(tool_input.get("function_name", ""), repo_key, fid=fid)
        return json.dumps({"function": tool_input.get("function_name", f"fid:{fid}"), "log_templates": templates})

    return f"Unknown tool: {tool_name}"
