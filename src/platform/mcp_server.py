"""Minimal MCP (JSON-RPC) bridge exposing capture actions as tools."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any, Dict, Optional
from pathlib import Path

# Ensure the `media_ark` brand module is importable when this file is
# invoked as `python3 -m src.platform.mcp_server` (the import path is
# `src.platform.mcp_server`; the brand module lives at `media_ark`).
# The relative import from `.config` works because the package context
# is set by runpy, but the brand module is at the top of `src/`.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.append(str(_SRC))

from media_ark import BRAND_MCP_NAME  # noqa: E402

from .runtime import run_capture_action  # noqa: E402
from .runtime import load_snapshot  # noqa: E402
from .config import (  # noqa: E402
    PlatformValidationError,
    default_out_dir,
    default_source_dir,
    normalize_platform_path,
)


# JSON-RPC error code for an unexpected server-side failure.
INTERNAL_ERROR = -32603

_LOGGER = logging.getLogger("media_ark.mcp")


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
    source = normalize_platform_path(
        arguments.get("source"), default=default_source_dir(), field="source"
    )
    out = normalize_platform_path(
        arguments.get("out"), default=default_out_dir(), field="out"
    )
    snapshot = load_snapshot(Path(out))
    snapshot.update(
        {
            "ok": True,
            "mode": "status",
            "tool": "capture_status",
            "source": str(source),
            "out": str(out),
        }
    )
    return snapshot


def _handle_tool_call(
    message_id: Optional[Any], name: str, arguments: Dict[str, Any]
) -> None:
    if name == "capture_status":
        try:
            response = _status_payload(arguments)
            _reply(message_id, _ok(message_id, response))
        except PlatformValidationError as exc:
            _reply(message_id, _error(message_id, -32602, str(exc)))
        except Exception as exc:  # noqa: BLE001 - keep the stdio loop alive
            _LOGGER.exception("capture_status failed")
            _reply(
                message_id,
                _error(message_id, INTERNAL_ERROR, f"internal error: {exc}"),
            )
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
    _reply(
        message_id,
        _ok(
            message_id,
            {
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
            },
        ),
    )


def _handle_message(message: Dict[str, Any]) -> None:
    message_id = message.get("id")
    method = message.get("method")
    if method is None:
        _reply(message_id, _error(message_id, -32600, "missing method"))
        return

    if isinstance(method, str) and method.startswith("notifications/"):
        return

    if method == "initialize":
        _reply(
            message_id,
            _ok(
                message_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": BRAND_MCP_NAME, "version": "1.0"},
                },
            ),
        )
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
        if not isinstance(message, dict):
            _reply(None, _error(None, -32600, "message must be a JSON object"))
            continue
        try:
            _handle_message(message)
        except Exception as exc:  # noqa: BLE001 - one bad message must not kill the loop
            _LOGGER.exception("Unhandled error processing message")
            _reply(
                message.get("id"),
                _error(message.get("id"), INTERNAL_ERROR, f"internal error: {exc}"),
            )


def _configure_logging() -> None:
    # Protocol responses go to stdout; logs must go to stderr so they
    # never corrupt the JSON-RPC stream a client is parsing.
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture platform MCP stdio bridge")
    _ = parser.parse_args()
    _configure_logging()
    run_stdio()


if __name__ == "__main__":
    main()
