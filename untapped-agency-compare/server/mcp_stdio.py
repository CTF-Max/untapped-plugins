"""Small newline-delimited JSON-RPC MCP server for stdio transports."""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, TextIO


SUPPORTED_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}


class ToolError(Exception):
    """An expected, safe-to-show tool failure message."""


def _identity(value: str) -> str:
    return value


def _clean(value: Any, sanitize: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        try:
            safe = sanitize(value)
        except Exception:
            safe = "Output could not be sanitized"
        return safe if isinstance(safe, str) else ""
    if isinstance(value, dict):
        return {str(_clean(k, sanitize)): _clean(v, sanitize) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item, sanitize) for item in value]
    return value


def serve(
    tools: list,
    call: Callable[[str, dict], dict],
    name: str = "untapped-serp",
    version: str = "0.1.0",
    sanitize: Callable[[str], str] = _identity,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> None:
    """Serve MCP JSON-RPC messages until EOF.

    Optional streams make the protocol directly testable without replacing stdio.
    """
    # MCP stdio is UTF-8. On Windows the default console codec (cp1252) crashes on the first non-Latin character
    # in a result (found 2026-10-09 by a live sandbox call returning '・').
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    source = input_stream if input_stream is not None else sys.stdin
    sink = output_stream if output_stream is not None else sys.stdout
    tool_list = _clean(tools, sanitize)

    def respond(message_id: Any, result: Any = None, error: dict | None = None) -> None:
        packet: dict[str, Any] = {"jsonrpc": "2.0", "id": message_id}
        if error is not None:
            packet["error"] = error
        else:
            packet["result"] = _clean(result, sanitize)
        sink.write(json.dumps(packet, ensure_ascii=False, separators=(",", ":")) + "\n")
        sink.flush()

    for raw in source:
        try:
            request = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError):
            respond(None, error={"code": -32700, "message": "Parse error"})
            continue
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
            respond(request.get("id") if isinstance(request, dict) else None,
                    error={"code": -32600, "message": "Invalid Request"})
            continue

        method = request["method"]
        params = request.get("params", {})
        has_id = "id" in request
        request_id = request.get("id")
        if method == "notifications/initialized":
            continue
        if method == "initialize":
            if not isinstance(params, dict):
                respond(request_id, error={"code": -32602, "message": "Invalid params"})
                continue
            requested = params.get("protocolVersion")
            chosen = requested if requested in SUPPORTED_VERSIONS else "2025-06-18"
            respond(request_id, {"protocolVersion": chosen, "capabilities": {"tools": {}},
                                 "serverInfo": {"name": name, "version": version}})
            continue
        if method == "ping":
            respond(request_id, {})
            continue
        if method == "tools/list":
            respond(request_id, {"tools": tool_list})
            continue
        if method == "tools/call":
            if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                respond(request_id, error={"code": -32602, "message": "Invalid params"})
                continue
            args = params.get("arguments", {})
            if not isinstance(args, dict):
                respond(request_id, error={"code": -32602, "message": "Invalid params"})
                continue
            try:
                value = call(params["name"], args)
                if not isinstance(value, dict):
                    raise ToolError("Tool returned an invalid result")
                safe_value = _clean(value, sanitize)
                wrapped = {"content": [{"type": "text", "text": json.dumps(safe_value, ensure_ascii=False)}],
                           "structuredContent": safe_value, "isError": False}
            except ToolError as exc:
                safe_message = _clean(str(exc), sanitize)
                error_value = {"error": safe_message}
                wrapped = {"content": [{"type": "text", "text": json.dumps(error_value, ensure_ascii=False)}],
                           "structuredContent": error_value, "isError": True}
            except Exception:
                error_value = {"error": "Tool execution failed"}
                wrapped = {"content": [{"type": "text", "text": json.dumps(error_value)}],
                           "structuredContent": error_value, "isError": True}
            respond(request_id, wrapped)
            continue
        if has_id:
            respond(request_id, error={"code": -32601, "message": "Method not found"})

