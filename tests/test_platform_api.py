from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
import tempfile
import unittest


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_api(port: int, attempts: int = 30) -> None:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise AssertionError("api did not become ready")


def _api_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["MEDIA_ARK_USERS_DB"] = str(root / "users.db")
    env["MEDIA_ARK_USER_SANDBOX_ROOT"] = str(root / "sandboxes")
    return env


def _auth_headers(token: str | None = None) -> dict[str, str]:
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _read_json(url: str, token: str | None = None) -> dict:
    request = urllib.request.Request(url, headers=_auth_headers(token))
    with urllib.request.urlopen(request) as response:
        assert response.status == 200
        return json.loads(response.read().decode("utf-8"))


def _read_json_allow_error(url: str, token: str | None = None) -> dict:
    try:
        return _read_json(url, token=token)
    except Exception as exc:
        if isinstance(exc, urllib.error.HTTPError):
            body = ""
            try:
                body = exc.read().decode("utf-8")
            finally:
                exc.close()
            return json.loads(body) if body else {"ok": False, "error": str(exc)}
        raise


def _post_json(url: str, payload: dict, token: str | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    headers.update(_auth_headers(token))
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        if isinstance(exc, urllib.error.HTTPError):
            body = ""
            try:
                body = exc.read().decode("utf-8")
            finally:
                exc.close()
            return json.loads(body) if body else {"ok": False, "error": str(exc)}
        raise


def _register_user(port: int, username: str = "tester") -> dict:
    return _post_json(
        f"http://127.0.0.1:{port}/api/auth/register",
        {"username": username, "password": "correct horse battery"},
    )


class TestApiServer(unittest.TestCase):
    def test_api_status_and_index_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            port = _free_port()
            proc = subprocess.Popen(
                [sys.executable, "-m", "src.platform.api_server", "--host", "127.0.0.1", "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_api_env(tmp / "auth"),
            )
            try:
                _wait_for_api(port)
                auth = _register_user(port)
                token = auth["api_key"]
                out = Path(auth["out"])
                manifest = out / "manifest.json"
                manifest.write_text(json.dumps({"run_id": "case-1", "status": "ok"}, indent=2), encoding="utf-8")
                index_file = out / "index.jsonl"
                index_file.write_text(
                    "\n".join(
                        [
                            json.dumps(
                                {
                                    "status": "processed",
                                    "media_type": "image",
                                    "path": "a.png",
                                    "text": "invoice one",
                                },
                            ),
                            json.dumps(
                                {
                                    "status": "duplicate",
                                    "media_type": "document",
                                    "path": "b.pdf",
                                    "text": "draft meeting",
                                },
                            ),
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )

                status = _read_json(f"http://127.0.0.1:{port}/api/status?out={out}", token)
                self.assertTrue(status["ok"])
                self.assertEqual(status["index_rows"], 2)
                self.assertEqual(status["manifest"]["status"], "ok")

                index = _read_json(
                    f"http://127.0.0.1:{port}/api/index?out={out}&query=invoice&status=all&media=all&limit=25",
                    token,
                )
                self.assertEqual(len(index["records"]), 1)
                self.assertEqual(index["records"][0]["path"], "a.png")
                self.assertEqual(index["records"][0]["status"], "processed")

                index_media = _read_json(
                    f"http://127.0.0.1:{port}/api/index?out={out}&status=processed&media=image&query=meeting&limit=25",
                    token,
                )
                self.assertEqual(len(index_media["records"]), 0)
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_api_run_check_source_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            port = _free_port()
            proc = subprocess.Popen(
                [sys.executable, "-m", "src.platform.api_server", "--host", "127.0.0.1", "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_api_env(tmp / "auth"),
            )
            try:
                _wait_for_api(port)
                auth = _register_user(port)
                token = auth["api_key"]
                source = Path(auth["source"])
                out = Path(auth["out"])
                response = _post_json(
                    f"http://127.0.0.1:{port}/api/run",
                    {"action": "check-source", "source": str(source), "out": str(out)},
                    token,
                )
                self.assertEqual(response["mode"], "check-source")
                self.assertIsInstance(response["run_id"], str)
                self.assertTrue(response["ok"])
                self.assertTrue(Path(response["event_log"]).exists())
                self.assertTrue(Path(response["report"]).exists())
                status = _read_json(f"http://127.0.0.1:{port}/api/status?out={out}", token)
                self.assertTrue(status["platform_events_exists"])
                self.assertGreaterEqual(status["report_count"], 1)
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_api_rejects_paths_outside_allowed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            outside_sandbox = tmp / "outside"
            outside_sandbox.mkdir()
            port = _free_port()
            proc = subprocess.Popen(
                [sys.executable, "-m", "src.platform.api_server", "--host", "127.0.0.1", "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_api_env(tmp / "auth"),
            )
            try:
                _wait_for_api(port)
                auth = _register_user(port)
                token = auth["api_key"]
                response = _read_json_allow_error(
                    f"http://127.0.0.1:{port}/api/status?out={outside_sandbox}",
                    token,
                )
                self.assertFalse(response["ok"])
                self.assertEqual(response["error"], "validation_error")

                run_response = _post_json(
                    f"http://127.0.0.1:{port}/api/run",
                    {
                        "action": "check-source",
                        "source": str(outside_sandbox),
                        "out": str(outside_sandbox),
                    },
                    token,
                )
                self.assertFalse(run_response["ok"])
                self.assertEqual(run_response["error"], "validation_error")
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_api_requires_bearer_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            port = _free_port()
            proc = subprocess.Popen(
                [sys.executable, "-m", "src.platform.api_server", "--host", "127.0.0.1", "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_api_env(tmp / "auth"),
            )
            try:
                _wait_for_api(port)
                response = _read_json_allow_error(
                    f"http://127.0.0.1:{port}/api/status"
                )
                self.assertFalse(response["ok"])
                self.assertEqual(response["error"], "unauthorized")

                auth = _register_user(port)
                status = _read_json(
                    f"http://127.0.0.1:{port}/api/status", auth["api_key"]
                )
                self.assertTrue(status["ok"])
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_api_key_endpoint_rotates_bearer_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            port = _free_port()
            proc = subprocess.Popen(
                [sys.executable, "-m", "src.platform.api_server", "--host", "127.0.0.1", "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_api_env(tmp / "auth"),
            )
            try:
                _wait_for_api(port)
                auth = _register_user(port)
                old_token = auth["api_key"]
                rotated = _post_json(
                    f"http://127.0.0.1:{port}/api/auth/api-key", {}, old_token
                )
                new_token = rotated["api_key"]
                self.assertNotEqual(old_token, new_token)

                old_response = _read_json_allow_error(
                    f"http://127.0.0.1:{port}/api/status", old_token
                )
                self.assertFalse(old_response["ok"])
                self.assertEqual(old_response["error"], "unauthorized")

                status = _read_json(f"http://127.0.0.1:{port}/api/status", new_token)
                self.assertTrue(status["ok"])
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_api_rejects_invalid_json_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            port = _free_port()
            proc = subprocess.Popen(
                [sys.executable, "-m", "src.platform.api_server", "--host", "127.0.0.1", "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_api_env(tmp / "auth"),
            )
            try:
                _wait_for_api(port)
                auth = _register_user(port)
                headers = {"Content-Type": "application/json"}
                headers.update(_auth_headers(auth["api_key"]))
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/run",
                    data=b"{not-json",
                    method="POST",
                    headers=headers,
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request)
                self.assertEqual(ctx.exception.code, 400)
                try:
                    payload = json.loads(ctx.exception.read().decode("utf-8"))
                    self.assertEqual(payload["error"], "validation_error")
                finally:
                    ctx.exception.close()
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_api_unexpected_error_returns_structured_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            port = _free_port()
            proc = subprocess.Popen(
                [sys.executable, "-m", "src.platform.api_server", "--host", "127.0.0.1", "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_api_env(tmp / "auth"),
            )
            try:
                _wait_for_api(port)
                auth = _register_user(port)
                token = auth["api_key"]
                out = Path(auth["out"])
                # Force an unexpected OSError deep inside the handler: a
                # directory where index.jsonl is expected makes the
                # snapshot read raise IsADirectoryError. The top-level
                # guard must convert that into a structured 500 instead
                # of leaking a traceback.
                (out / "index.jsonl").mkdir(parents=True, exist_ok=True)
                response = _read_json_allow_error(
                    f"http://127.0.0.1:{port}/api/status?out={out}", token
                )
                self.assertFalse(response["ok"])
                self.assertEqual(response["error"], "internal_error")
                # The generic message must not leak internals (paths,
                # exception type, traceback).
                self.assertNotIn("Traceback", json.dumps(response))

                # The server stays up and serves later requests normally.
                (out / "index.jsonl").rmdir()
                ok_status = _read_json(
                    f"http://127.0.0.1:{port}/api/status?out={out}", token
                )
                self.assertTrue(ok_status["ok"])
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_dashboard_static_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            port = _free_port()
            proc = subprocess.Popen(
                [sys.executable, "-m", "src.platform.api_server", "--host", "127.0.0.1", "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_api_env(tmp / "auth"),
            )
            try:
                _wait_for_api(port)
                auth = _register_user(port)

                index = _read_json(
                    f"http://127.0.0.1:{port}/api/status?out={auth['out']}",
                    auth["api_key"],
                )
                self.assertTrue(index["ok"])

                with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as response:
                    page = response.read().decode("utf-8")
                self.assertIn("Screen Capture Platform", page)
                self.assertIn("script src=\"/app.js\"", page)

                with urllib.request.urlopen(f"http://127.0.0.1:{port}/styles.css") as response:
                    css = response.read().decode("utf-8")
                self.assertIn("body {", css)
                self.assertIn("background", css)
            finally:
                proc.terminate()
                proc.wait(timeout=5)
