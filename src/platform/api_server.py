"""HTTP API and lightweight dashboard server for capture platform."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

# Ensure the `media_ark` brand module is importable when this file is
# invoked as `python3 -m src.platform.api_server` (the import path is
# `src.platform.api_server`; the brand module lives at `media_ark`).
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from media_ark import BRAND_SERVER_VERSION, env_key  # noqa: E402

from .auth import (  # noqa: E402
    AuthConflictError,
    AuthCredentialsError,
    AuthError,
    AuthStore,
    AuthUser,
)
from .config import (  # noqa: E402
    PlatformValidationError,
    coerce_int,
    default_out_dir,
    default_source_dir,
    normalize_platform_path,
    validate_choice,
    validate_query,
)
from .export import ExportError, build_export, extract_request_token  # noqa: E402
from .runtime import load_snapshot, run_capture_action  # noqa: E402


MAX_JSON_BODY_BYTES = 1_000_000
PUBLIC_API_ROUTES = {
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
}


class RequestValidationError(ValueError):
    pass


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _static_root() -> Path:
    return _repo_root() / "web"


def _json(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _write_json(
    handler: BaseHTTPRequestHandler,
    status: int,
    payload: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> None:
    encoded = _json(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.send_header("Cache-Control", "no-store")
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(encoded)


def _write_bytes(
    handler: BaseHTTPRequestHandler,
    status: int,
    content: bytes,
    *,
    content_type: str,
    filename: Optional[str] = None,
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(content)))
    handler.send_header("Cache-Control", "no-store")
    if filename:
        handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.end_headers()
    handler.wfile.write(content)


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
    path: str,
    query: Dict[str, Any],
    method: str,
    body: Dict[str, Any],
    user: Optional[AuthUser] = None,
) -> Dict[str, Any]:
    if method.upper() == "GET":
        payload = dict(query)
    else:
        payload = dict(query)
        for key, value in body.items():
            payload[key] = value
    default_source, default_out = _default_paths_for_user(user)
    if "source" not in payload:
        payload.setdefault("source", str(default_source))
    if "out" not in payload:
        payload.setdefault("out", str(default_out))
    payload.setdefault("mode", path.lstrip("/").split("/")[-1])
    return payload


def _is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _normalized_route(path: str) -> str:
    return path.rstrip("/") or "/"


def _default_paths_for_user(user: Optional[AuthUser]) -> tuple[Path, Path]:
    if user is None:
        return default_source_dir(), default_out_dir()
    return user.sandbox / "source", user.sandbox / "out"


def _auth_roots(user: Optional[AuthUser]) -> Optional[list[Path]]:
    if user is None:
        return None
    return [user.sandbox]


def _validated_paths(
    query: Dict[str, Any], user: Optional[AuthUser] = None
) -> tuple[Path, Path]:
    default_source, default_out = _default_paths_for_user(user)
    roots = _auth_roots(user)
    source = normalize_platform_path(
        query.get("source"), default=default_source, field="source", roots=roots
    )
    out = normalize_platform_path(
        query.get("out"), default=default_out, field="out", roots=roots
    )
    return source, out


def _write_validation_error(handler: BaseHTTPRequestHandler, message: str) -> None:
    _write_json(
        handler, 400, {"ok": False, "error": "validation_error", "message": message}
    )


def _auth_response_payload(user: AuthUser, api_key: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ok": True,
        "user": {"id": user.id, "username": user.username},
        "sandbox": str(user.sandbox),
        "source": str(user.sandbox / "source"),
        "out": str(user.sandbox / "out"),
    }
    if api_key is not None:
        payload["api_key"] = api_key
    return payload


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server_version = BRAND_SERVER_VERSION
    auth_user: Optional[AuthUser] = None

    def _auth_store(self) -> AuthStore:
        store = getattr(self.server, "auth_store", None)
        if store is None:
            store = AuthStore()
            setattr(self.server, "auth_store", store)
        return store

    def _write_auth_required(self, message: str = "missing bearer token") -> None:
        _write_json(
            self,
            401,
            {"ok": False, "error": "unauthorized", "message": message},
            headers={"WWW-Authenticate": 'Bearer realm="media-ark"'},
        )

    def _authenticate_api_request(self, method: str, path: str) -> bool:
        self.auth_user = None
        route = _normalized_route(path)
        if (method.upper(), route) in PUBLIC_API_ROUTES or route.startswith(
            "/api/export/"
        ):
            return True
        if not os.environ.get(env_key("USERS_DB")):
            return True

        authorization = self.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            self._write_auth_required()
            return False

        user = self._auth_store().authenticate_api_key(token.strip())
        if user is None:
            self._write_auth_required("invalid bearer token")
            return False

        self.auth_user = user
        return True

    def _read_auth_body(self) -> Dict[str, Any]:
        body = _read_json_body(self)
        if "username" not in body or "password" not in body:
            raise RequestValidationError("username and password are required")
        return body

    def _handle_register(self) -> None:
        try:
            body = self._read_auth_body()
            user, api_key = self._auth_store().register(
                body.get("username"), body.get("password")
            )
        except RequestValidationError as exc:
            _write_validation_error(self, str(exc))
            return
        except AuthConflictError as exc:
            _write_json(
                self,
                409,
                {"ok": False, "error": exc.error, "message": str(exc)},
            )
            return
        except AuthError as exc:
            _write_json(
                self,
                400,
                {"ok": False, "error": exc.error, "message": str(exc)},
            )
            return
        _write_json(self, 201, _auth_response_payload(user, api_key))

    def _handle_login(self) -> None:
        try:
            body = self._read_auth_body()
            user, api_key = self._auth_store().login(
                body.get("username"), body.get("password")
            )
        except RequestValidationError as exc:
            _write_validation_error(self, str(exc))
            return
        except AuthCredentialsError as exc:
            _write_json(
                self,
                401,
                {"ok": False, "error": exc.error, "message": str(exc)},
            )
            return
        except AuthError as exc:
            _write_json(
                self,
                400,
                {"ok": False, "error": exc.error, "message": str(exc)},
            )
            return
        _write_json(self, 200, _auth_response_payload(user, api_key))

    def _handle_api_key(self) -> None:
        if self.auth_user is None:
            self._write_auth_required()
            return
        try:
            user, api_key = self._auth_store().rotate_api_key(self.auth_user.id)
        except AuthError as exc:
            _write_json(
                self,
                401,
                {"ok": False, "error": exc.error, "message": str(exc)},
            )
            return
        _write_json(self, 200, _auth_response_payload(user, api_key))

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
        if _is_api_path(parsed.path) and not self._authenticate_api_request(
            "GET", parsed.path
        ):
            return

        if parsed.path.startswith("/api/status"):
            query = self._read_query()
            try:
                source, out = _validated_paths(query, self.auth_user)
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

        if parsed.path.startswith("/api/export/"):
            query = self._read_query()
            fmt = parsed.path.rsplit("/", 1)[-1]
            try:
                out = normalize_platform_path(
                    query.get("out"),
                    default=default_out_dir(),
                    field="out",
                )
                token = extract_request_token(dict(self.headers), query)
                content, content_type, filename = build_export(fmt, out, token=token)
            except PlatformValidationError as exc:
                _write_validation_error(self, str(exc))
                return
            except ExportError as exc:
                _write_json(
                    self,
                    exc.status,
                    {"ok": False, "error": exc.error, "message": exc.message},
                )
                return
            _write_bytes(
                self,
                200,
                content,
                content_type=content_type,
                filename=filename,
            )
            return

        if parsed.path.startswith("/api/index"):
            query = self._read_query()
            try:
                _, out = _validated_paths(query, self.auth_user)
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
                    query.get("out"),
                    default=_default_paths_for_user(self.auth_user)[1],
                    field="out",
                    roots=_auth_roots(self.auth_user),
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
        if _is_api_path(parsed.path) and not self._authenticate_api_request(
            "POST", parsed.path
        ):
            return

        if route == "/api/auth/register":
            self._handle_register()
            return

        if route == "/api/auth/login":
            self._handle_login()
            return

        if route == "/api/auth/api-key":
            self._handle_api_key()
            return

        if route != "/api/run":
            self.send_error(404, "not found")
            return
        try:
            body = _read_json_body(self)
        except RequestValidationError as exc:
            _write_validation_error(self, str(exc))
            return
        query = self._read_query()
        payload = to_action_payload(
            "run", query=query, body=body, method="POST", user=self.auth_user
        )
        action = str(payload.get("action", payload.get("mode", "process")))
        payload["mode"] = action
        result = run_capture_action(payload, roots=_auth_roots(self.auth_user))
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
