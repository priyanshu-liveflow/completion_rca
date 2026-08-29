"""Shared MCP plumbing: register, validate, dispatch, serve.

Handlers never raise across the MCP boundary. Failures become
`{"error": {"type": ..., "message": ...}}`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

JsonObject = dict[str, Any]


@dataclass(frozen=True)
class ToolSpec:
    """One registered MCP tool."""

    name: str
    description: str
    schema: JsonObject
    handler: Callable[..., Any]


_REGISTRY: dict[str, ToolSpec] = {}


class ToolError(Exception):
    """Typed failure turned into the uniform error envelope."""

    def __init__(self, type_: str, message: str) -> None:
        super().__init__(message)
        self.type = type_
        self.message = message


def tool(
    name: str, description: str, schema: JsonObject
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register an MCP handler. Input is validated against `schema` before call."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        _REGISTRY[name] = ToolSpec(
            name=name, description=description, schema=schema, handler=fn
        )
        return fn

    return decorator


def list_tools() -> list[ToolSpec]:
    """Registered tools, in insertion order."""
    return list(_REGISTRY.values())


def clear_tools() -> None:
    """Drop all registrations. Tests use this to isolate modules."""
    _REGISTRY.clear()


def validate_input(schema: JsonObject, arguments: JsonObject) -> None:
    """Check required fields and primitive types. Raises ToolError on mismatch."""
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        raise ToolError("invalid_schema", "tool schema is missing properties")
    required = schema.get("required") or []
    if not isinstance(required, list):
        raise ToolError("invalid_schema", "tool schema required must be a list")
    for key in required:
        if key not in arguments:
            raise ToolError("invalid_input", f"missing required field {key!r}")
    for key, value in arguments.items():
        if key not in properties:
            raise ToolError("invalid_input", f"unexpected field {key!r}")
        spec = properties[key]
        if not isinstance(spec, dict):
            continue
        expected = spec.get("type")
        if expected == "string" and not isinstance(value, str):
            raise ToolError("invalid_input", f"{key!r} must be a string")
        if expected == "integer" and not isinstance(value, int):
            raise ToolError("invalid_input", f"{key!r} must be an integer")


def _dump(result: Any) -> Any:
    if isinstance(result, BaseModel):
        return result.model_dump()
    if isinstance(result, list):
        return [_dump(item) for item in result]
    return result


def dispatch(name: str, arguments: JsonObject | None = None) -> Any:
    """Validate, call the handler, return a contract dump or an error envelope."""
    spec = _REGISTRY.get(name)
    if spec is None:
        return {"error": {"type": "unknown_tool", "message": f"unknown tool {name!r}"}}
    payload = arguments or {}
    try:
        validate_input(spec.schema, payload)
        return _dump(spec.handler(**payload))
    except ToolError as exc:
        return {"error": {"type": exc.type, "message": exc.message}}
    except TypeError as exc:
        return {"error": {"type": "invalid_input", "message": str(exc)}}
    except Exception as exc:
        return {"error": {"type": "internal", "message": str(exc)}}


def serve(name: str, port: int) -> None:
    """Bind registered tools as an MCP SSE server on 127.0.0.1:`port`."""
    import uvicorn
    from mcp.server.lowlevel import Server
    from mcp.server.sse import SseServerTransport
    from mcp.types import TextContent, Tool
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.routing import Mount, Route

    server = Server(name)
    sse = SseServerTransport("/messages/")

    @server.list_tools()  # type: ignore[untyped-decorator]
    async def _list_tools() -> list[Tool]:
        return [
            Tool(name=spec.name, description=spec.description, inputSchema=spec.schema)
            for spec in list_tools()
        ]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def _call_tool(tool_name: str, arguments: JsonObject) -> list[TextContent]:
        payload = dispatch(tool_name, arguments)
        return [TextContent(type="text", text=json.dumps(payload))]

    async def handle_sse(request: Request) -> None:
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0], streams[1], server.create_initialization_options()
            )

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )
    uvicorn.run(app, host="127.0.0.1", port=port)
