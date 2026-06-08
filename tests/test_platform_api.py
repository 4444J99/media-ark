from __future__ import annotations

import json
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
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise AssertionError("api did not become ready")


def _read_json(url: str) -> dict:
    with urllib.request.urlopen(url) as response:
        assert response.status == 200
        return json.loads(response.read().decode("utf-8"))


def _read_json_allow_error(url: str) -> dict:
    try:
        return _read_json(url)
    except Exception as exc:
        if isinstance(exc, urllib.error.HTTPError):
            body = ""
            try:
                body = exc.read().decode("utf-8")
            finally:
                exc.close()
            return json.loads(body) if body else {"ok": False, "error": str(exc)}
        raise


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
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


class TestApiServer(unittest.TestCase):
    def test_api_status_and_index_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "out"
            out.mkdir()
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

            port = _free_port()
            proc = subprocess.Popen(
                [sys.executable, "-m", "src.platform.api_server", "--host", "127.0.0.1", "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                _wait_for_api(port)

                status = _read_json(f"http://127.0.0.1:{port}/api/status?out={out}")
                self.assertTrue(status["ok"])
                self.assertEqual(status["index_rows"], 2)
                self.assertEqual(status["manifest"]["status"], "ok")

                index = _read_json(
                    f"http://127.0.0.1:{port}/api/index?out={out}&query=invoice&status=all&media=all&limit=25"
                )
                self.assertEqual(len(index["records"]), 1)
                self.assertEqual(index["records"][0]["path"], "a.png")
                self.assertEqual(index["records"][0]["status"], "processed")

                index_media = _read_json(
                    f"http://127.0.0.1:{port}/api/index?out={out}&status=processed&media=image&query=meeting&limit=25"
                )
                self.assertEqual(len(index_media["records"]), 0)
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_api_run_check_source_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source"
            out = Path(tmpdir) / "out"
            source.mkdir()
            out.mkdir()
            port = _free_port()
            proc = subprocess.Popen(
                [sys.executable, "-m", "src.platform.api_server", "--host", "127.0.0.1", "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                _wait_for_api(port)
                response = _post_json(
                    f"http://127.0.0.1:{port}/api/run",
                    {"action": "check-source", "source": str(source), "out": str(out)},
                )
                self.assertEqual(response["mode"], "check-source")
                self.assertIsInstance(response["run_id"], str)
                self.assertTrue(response["ok"])
                self.assertTrue(Path(response["event_log"]).exists())
                self.assertTrue(Path(response["report"]).exists())
                status = _read_json(f"http://127.0.0.1:{port}/api/status?out={out}")
                self.assertTrue(status["platform_events_exists"])
                self.assertGreaterEqual(status["report_count"], 1)
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_api_rejects_paths_outside_allowed_roots(self) -> None:
        port = _free_port()
        proc = subprocess.Popen(
            [sys.executable, "-m", "src.platform.api_server", "--host", "127.0.0.1", "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_for_api(port)
            response = _read_json_allow_error(f"http://127.0.0.1:{port}/api/status?out=/etc")
            self.assertFalse(response["ok"])
            self.assertEqual(response["error"], "validation_error")

            run_response = _post_json(
                f"http://127.0.0.1:{port}/api/run",
                {"action": "check-source", "source": "/etc", "out": "/etc"},
            )
            self.assertFalse(run_response["ok"])
            self.assertEqual(run_response["error"], "validation_error")
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_api_rejects_invalid_json_body(self) -> None:
        port = _free_port()
        proc = subprocess.Popen(
            [sys.executable, "-m", "src.platform.api_server", "--host", "127.0.0.1", "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_for_api(port)
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/run",
                data=b"{not-json",
                method="POST",
                headers={"Content-Type": "application/json"},
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

    def test_dashboard_static_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "out"
            out.mkdir()
            port = _free_port()
            proc = subprocess.Popen(
                [sys.executable, "-m", "src.platform.api_server", "--host", "127.0.0.1", "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                _wait_for_api(port)

                index = _read_json(f"http://127.0.0.1:{port}/api/status?out={out}")
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
