"""Minimal MCP (JSON-RPC) bridge exposing capture actions as tools."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional
from pathlib import Path

from .runtime import run_capture_action
from .runtime import load_snapshot
from .config import PlatformValidationError, default_out_dir, default_source_dir, normalize_platform_path


def _reply(correlation: Optional[Any], payload: Dict[str, Any]) -> None:
    body = json.dumps(payload)
    print(body, flush=True)


def _ok(message_id: Optional[Any], result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id: Optional[Any], code: int, message: str) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": code, "message": message},
    }


def tool_list() -> Dict[str, Any]:
    return {
        "tools": [
            {
                "name": "capture_status",
                "description": "Read manifest/index snapshot for a source/out pair.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "out": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "capture_check",
                "description": "Run --check-source against capture root.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "out": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "capture_run",
                "description": "Run capture processing once.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "out": {"type": "string"},
                        "copy": {"type": "boolean"},
                        "max_files": {"type": "integer"},
                        "dry_run": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "capture_verify",
                "description": "Run --verify checks on manifest/index consistency.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "out": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "capture_query",
                "description": "Search indexed captures by text and status/media filters.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "out": {"type": "string"},
                        "query": {"type": "string"},
                        "query_media": {"type": "string"},
                        "query_status": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
        ]
    }


def _status_payload(arguments: Dict[str, Any]) -> Dict[str, Any]:
    source = normalize_platform_path(arguments.get("source"), default=default_source_dir(), field="source")
    out = normalize_platform_path(arguments.get("out"), default=default_out_dir(), field="out")
    snapshot = load_snapshot(Path(out))
    snapshot.update({
        "ok": True,
        "mode": "status",
        "tool": "capture_status",
        "source": str(source),
        "out": str(out),
    })
    return snapshot


def _handle_tool_call(message_id: Optional[Any], name: str, arguments: Dict[str, Any]) -> None:
    if name == "capture_status":
        try:
            response = _status_payload(arguments)
            _reply(message_id, _ok(message_id, response))
        except PlatformValidationError as exc:
            _reply(message_id, _error(message_id, -32602, str(exc)))
        return

    mode = {
        "capture_check": "check-source",
        "capture_run": "process",
        "capture_verify": "verify",
        "capture_query": "query",
    }.get(name)

    if not mode:
        _reply(message_id, _error(message_id, -32602, f"unknown tool: {name}"))
        return

    payload = dict(arguments or {})
    payload["mode"] = mode
    result = run_capture_action(payload)
    if result.error == "validation_error":
        _reply(message_id, _error(message_id, -32602, result.stderr))
        return
    _reply(message_id, _ok(message_id, {
        "tool": name,
        "ok": result.ok,
        "run_id": result.run_id,
        "mode": result.mode,
        "duration_ms": result.duration_ms,
        "return_code": result.return_code,
        "payload": result.payload,
        "error": result.error,
        "event_log": result.event_log,
        "report": result.report,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }))


def _handle_message(message: Dict[str, Any]) -> None:
    message_id = message.get("id")
    method = message.get("method")
    if method is None:
        _reply(message_id, _error(message_id, -32600, "missing method"))
        return

    if method == "initialize":
        _reply(message_id, _ok(message_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "screen-capture-platform", "version": "1.0"},
        }))
        return

    if method == "tools/list":
        _reply(message_id, _ok(message_id, tool_list()))
        return

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name") or params.get("tool")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        if not name:
            _reply(message_id, _error(message_id, -32602, "missing tool name"))
            return
        _handle_tool_call(message_id, str(name), arguments)
        return

    _reply(message_id, _error(message_id, -32601, f"unknown method: {method}"))


def run_stdio() -> None:
    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except Exception as exc:
            response = _error(None, -32700, f"invalid json: {exc}")
            print(json.dumps(response), flush=True)
            continue
        _handle_message(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture platform MCP stdio bridge")
    _ = parser.parse_args()
    run_stdio()


if __name__ == "__main__":
    main()
