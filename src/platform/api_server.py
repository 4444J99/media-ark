"""HTTP API and lightweight dashboard server for capture platform."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

# Ensure the `media_ark` brand module is importable when this file is
# invoked as `python3 -m src.platform.api_server` (the import path is
# `src.platform.api_server`; the brand module lives at `media_ark`).
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from media_ark import BRAND_SERVER_VERSION, env_key  # noqa: E402

from .config import (  # noqa: E402
    PlatformValidationError,
    coerce_int,
    default_out_dir,
    default_source_dir,
    normalize_platform_path,
    validate_choice,
    validate_query,
)
from .quota import (  # noqa: E402
    DEFAULT_TIER,
    QuotaExceeded,
    QuotaStore,
    directory_size,
)
from .runtime import _coerce_bool, load_snapshot, run_capture_action  # noqa: E402


MAX_JSON_BODY_BYTES = 1_000_000

# Modes that drive the capture pipeline and therefore run OCR (unless the
# caller opts out with no_ocr). Used to decide whether a /api/run request
# consumes an OCR call against the user's monthly budget.
_OCR_MODES = {"process", "run", "once"}

_QUOTA_STORE = QuotaStore()


def _quota_store() -> QuotaStore:
    return _QUOTA_STORE


def _write_quota_error(handler: BaseHTTPRequestHandler, exc: QuotaExceeded) -> None:
    _write_json(handler, 429, exc.to_payload())


class RequestValidationError(ValueError):
    pass


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _static_root() -> Path:
    return _repo_root() / "web"


def _json(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _write_json(
    handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]
) -> None:
    encoded = _json(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(encoded)


def _read_json_body(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    length_header = handler.headers.get("Content-Length")
    if not length_header:
        return {}
    try:
        length = int(length_header)
    except ValueError as exc:
        raise RequestValidationError("Content-Length must be an integer") from exc
    if length > MAX_JSON_BODY_BYTES:
        raise RequestValidationError(
            f"request body must be <= {MAX_JSON_BODY_BYTES} bytes"
        )
    body = handler.rfile.read(length)
    if not body:
        return {}
    try:
        payload: Dict[str, Any] = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RequestValidationError(f"invalid JSON body: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise RequestValidationError("JSON body must be an object")
    return payload


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def to_action_payload(
    path: str, query: Dict[str, Any], method: str, body: Dict[str, Any]
) -> Dict[str, Any]:
    if method.upper() == "GET":
        payload = dict(query)
    else:
        payload = dict(query)
        for key, value in body.items():
            payload[key] = value
    if "source" not in payload:
        payload.setdefault("source", str(default_source_dir()))
    if "out" not in payload:
        payload.setdefault("out", str(default_out_dir()))
    payload.setdefault("mode", path.lstrip("/").split("/")[-1])
    return payload


def _validated_paths(query: Dict[str, Any]) -> tuple[Path, Path]:
    source = normalize_platform_path(
        query.get("source"), default=default_source_dir(), field="source"
    )
    out = normalize_platform_path(
        query.get("out"), default=default_out_dir(), field="out"
    )
    return source, out


def _write_validation_error(handler: BaseHTTPRequestHandler, message: str) -> None:
    _write_json(
        handler, 400, {"ok": False, "error": "validation_error", "message": message}
    )


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server_version = BRAND_SERVER_VERSION

    def _read_query(self) -> Dict[str, Any]:
        parsed = urlparse(self.path)
        raw = parse_qs(parsed.query, keep_blank_values=True)
        normalized: Dict[str, Any] = {}
        for key, value in raw.items():
            if not value:
                continue
            if len(value) == 1:
                normalized[key] = value[0]
            else:
                normalized[key] = value
        return normalized

    def _identify_user(self) -> tuple[str, str]:
        """Derive (user_id, tier) for the current request from headers.

        The hosted edge is expected to set ``X-User-Id`` / ``X-User-Tier``
        after authenticating; absent those, requests fall to a shared
        ``anonymous`` user on the default tier.
        """

        user_id = (self.headers.get("X-User-Id") or "").strip() or "anonymous"
        tier = (self.headers.get("X-User-Tier") or "").strip() or DEFAULT_TIER
        return user_id, tier

    def _enforce_quota(
        self, *, api_calls: int = 1, ocr_calls: int = 0, storage_bytes: int | None = None
    ) -> bool:
        """Consume quota for this request; write a 429 and return False if over."""

        user_id, tier = self._identify_user()
        try:
            _quota_store().consume(
                user_id,
                tier=tier,
                api_calls=api_calls,
                ocr_calls=ocr_calls,
                storage_bytes=storage_bytes,
            )
        except QuotaExceeded as exc:
            _write_quota_error(self, exc)
            return False
        return True

    def _serve_static(self, parsed_path: str) -> None:
        safe_name = parsed_path.lstrip("/")
        if not safe_name:
            safe_name = "index.html"
        target = (_static_root() / safe_name).resolve()
        static_root = _static_root().resolve()
        try:
            target.relative_to(static_root)
        except ValueError:
            self.send_error(403, "forbidden")
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.exists() or not target.is_file():
            self.send_error(404, "not found")
            return
        mime, _ = mimetypes.guess_type(str(target))
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/quota"):
            # Reading your own meter is free — it must not be the thing
            # that pushes you over the call budget.
            user_id, tier = self._identify_user()
            usage = _quota_store().get_usage(user_id)
            _write_json(
                self,
                200,
                {
                    "ok": True,
                    "user": user_id,
                    "tier": usage.tier or tier,
                    "usage": usage.to_dict(),
                },
            )
            return

        if parsed.path.startswith("/api/status"):
            query = self._read_query()
            try:
                source, out = _validated_paths(query)
            except PlatformValidationError as exc:
                _write_validation_error(self, str(exc))
                return
            status = {
                "ok": True,
                "api_version": "1.0",
                "source": str(source),
                "out": str(out),
            }
            status.update(load_snapshot(out))
            _write_json(self, 200, status)
            return

        if parsed.path.startswith("/api/index"):
            query = self._read_query()
            try:
                _, out = _validated_paths(query)
                limit = coerce_int(
                    query.get("limit", 25),
                    field="limit",
                    default=25,
                    minimum=0,
                    maximum=1000,
                )
                query_text = (
                    validate_query(query.get("query", ""), max_chars=500)
                    .strip()
                    .lower()
                )
                status_filter = validate_choice(
                    str(query.get("status", "all")),
                    field="status",
                    allowed={"all", "processed", "duplicate"},
                )
                media_filter = validate_choice(
                    str(query.get("media", "all")),
                    field="media",
                    allowed={"all", "image", "video", "document"},
                )
            except PlatformValidationError as exc:
                _write_validation_error(self, str(exc))
                return
            manifest = load_snapshot(out)
            status = {
                "index_rows": manifest.get("index_rows", 0),
            }
            if manifest.get("index_rows", 0) and (out / "index.jsonl").exists():
                with (out / "index.jsonl").open(encoding="utf-8") as handle:
                    records = []
                    for line in handle:
                        raw = line.strip()
                        if not raw:
                            continue
                        try:
                            row = json.loads(raw)
                        except Exception:
                            continue
                        if (
                            query_text
                            and query_text
                            not in json.dumps(row, ensure_ascii=False).lower()
                        ):
                            continue
                        if (
                            status_filter != "all"
                            and row.get("status") != status_filter
                        ):
                            continue
                        if (
                            media_filter != "all"
                            and row.get("media_type") != media_filter
                        ):
                            continue
                        records.append(row)
                    if limit > 0:
                        records = records[:limit]
                    status["records"] = records
            _write_json(self, 200, status)
            return

        if parsed.path.startswith("/api/manifest"):
            query = self._read_query()
            try:
                out = normalize_platform_path(
                    query.get("out"), default=default_out_dir(), field="out"
                )
            except PlatformValidationError as exc:
                _write_validation_error(self, str(exc))
                return
            manifest_payload = load_snapshot(out).get("manifest", {})
            _write_json(self, 200, {"manifest": manifest_payload})
            return

        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/")
        if route != "/api/run":
            self.send_error(404, "not found")
            return
        try:
            body = _read_json_body(self)
        except RequestValidationError as exc:
            _write_validation_error(self, str(exc))
            return
        query = self._read_query()
        payload = to_action_payload("run", query=query, body=body, method="POST")
        action = str(payload.get("action", payload.get("mode", "process")))
        payload["mode"] = action

        # OCR runs for the capture pipeline modes unless the caller opts
        # out; charge an OCR call only when it will actually happen.
        no_ocr = _coerce_bool(payload.get("no_ocr", payload.get("noOcr", False)))
        ocr_calls = 1 if (action in _OCR_MODES and not no_ocr) else 0

        # Measure the user's archive before running so an already-overflowing
        # archive is rejected up front. Best-effort: a bad path is left to
        # run_capture_action to validate and report as 400.
        out_for_storage: int | None = None
        try:
            out_for_storage = directory_size(
                normalize_platform_path(
                    payload.get("out"), default=default_out_dir(), field="out"
                )
            )
        except PlatformValidationError:
            out_for_storage = None

        if not self._enforce_quota(
            api_calls=1, ocr_calls=ocr_calls, storage_bytes=out_for_storage
        ):
            return

        result = run_capture_action(payload)

        # Reflect the post-run archive size so the next request sees it.
        if result.ok and result.out:
            user_id, _ = self._identify_user()
            _quota_store().update_storage(user_id, directory_size(Path(result.out)))
        response: Dict[str, Any] = {
            "mode": action,
            "ok": result.ok,
            "run_id": result.run_id,
            "duration_ms": result.duration_ms,
            "return_code": result.return_code,
            "source": result.source,
            "out": result.out,
            "event_log": result.event_log,
            "report": result.report,
            "payload": result.payload,
        }
        if result.error:
            response["error"] = result.error
            response["stdout"] = result.stdout
            response["stderr"] = result.stderr
            _write_json(
                self, 400 if result.error == "validation_error" else 500, response
            )
            return
        _write_json(self, 200, response)

    def log_message(self, fmt: str, *args) -> None:
        if os.environ.get(env_key("VERBOSE")) == "1":
            super().log_message(fmt, *args)


def make_handler() -> type[DashboardRequestHandler]:
    return DashboardRequestHandler


def run_server(host: str = "127.0.0.1", port: int = 8787) -> None:
    handler_class = make_handler()
    server = ThreadingHTTPServer((host, port), handler_class)
    print(f"Capture platform server listening on http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture platform API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
