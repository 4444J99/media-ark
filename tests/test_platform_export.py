from __future__ import annotations

import csv
import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
import tempfile
import unittest

from src.platform.export import (
    ExportError,
    authorize_pro,
    build_export,
    check_ownership,
    extract_request_token,
    load_pro_tokens,
    render_csv,
)


def _seed_archive(out: Path, *, owner: str | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"run_id": "case-1", "status": "ok"}
    if owner is not None:
        manifest["owner"] = owner
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "index.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "aaaa",
                        "status": "processed",
                        "media_type": "image",
                        "canonical_path": "a.png",
                        "tags": ["invoice", "scan"],
                        "ocr_text": "invoice one",
                    }
                ),
                json.dumps(
                    {
                        "id": "bbbb",
                        "status": "duplicate",
                        "media_type": "document",
                        "canonical_path": "b.pdf",
                        "ocr_text": "draft meeting",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "index-summary.json").write_text(
        json.dumps({"count": 2, "images": 1, "documents": 1}), encoding="utf-8"
    )
    # An OCR sidecar plus files that must be excluded from the zip bundle.
    (out / "a_aaaaaaaaaa.png.json").write_text(
        json.dumps({"id": "aaaa", "ocr": "invoice one"}), encoding="utf-8"
    )
    (out / "config.json").write_text(json.dumps({"ignore": True}), encoding="utf-8")
    (out / "old.backup.json").write_text(json.dumps({"ignore": True}), encoding="utf-8")


class TestExportUnit(unittest.TestCase):
    def test_load_pro_tokens_parses_principals(self) -> None:
        tokens = load_pro_tokens({"MEDIA_ARK_PRO_TOKENS": "tok1:alice, tok2 ,tok3:bob"})
        self.assertEqual(tokens, {"tok1": "alice", "tok2": "tok2", "tok3": "bob"})

    def test_load_pro_tokens_empty(self) -> None:
        self.assertEqual(load_pro_tokens({}), {})
        self.assertEqual(load_pro_tokens({"MEDIA_ARK_PRO_TOKENS": "  "}), {})

    def test_extract_request_token_precedence(self) -> None:
        self.assertEqual(
            extract_request_token({"Authorization": "Bearer abc"}, {}), "abc"
        )
        self.assertEqual(extract_request_token({"X-Api-Key": "key1"}, {}), "key1")
        self.assertEqual(extract_request_token({}, {"token": "qtok"}), "qtok")
        self.assertEqual(extract_request_token(None, {}), "")

    def test_authorize_pro_paths(self) -> None:
        with self.assertRaises(ExportError) as ctx:
            authorize_pro("tok", {})
        self.assertEqual(ctx.exception.error, "pro_tier_required")

        with self.assertRaises(ExportError) as ctx:
            authorize_pro("", {"tok": "alice"})
        self.assertEqual(ctx.exception.error, "missing_token")
        self.assertEqual(ctx.exception.status, 401)

        with self.assertRaises(ExportError) as ctx:
            authorize_pro("nope", {"tok": "alice"})
        self.assertEqual(ctx.exception.error, "pro_tier_required")

        self.assertEqual(authorize_pro("tok", {"tok": "alice"}), "alice")

    def test_check_ownership(self) -> None:
        check_ownership("alice", None)  # unowned -> allowed
        check_ownership("alice", {})  # no owner field -> allowed
        check_ownership("alice", {"owner": "alice"})  # match -> allowed
        with self.assertRaises(ExportError) as ctx:
            check_ownership("alice", {"owner": "bob"})
        self.assertEqual(ctx.exception.error, "ownership_denied")
        self.assertEqual(ctx.exception.status, 403)

    def test_render_csv_stable_header(self) -> None:
        rows = [{"id": "x", "status": "processed", "tags": ["a", "b"]}]
        decoded = render_csv(rows).decode("utf-8")
        parsed = list(csv.reader(io.StringIO(decoded)))
        self.assertEqual(parsed[0][:2], ["id", "status"])
        # nested values are JSON-encoded into a single cell
        tag_col = parsed[0].index("tags")
        self.assertEqual(parsed[1][tag_col], '["a", "b"]')

    def test_build_export_unknown_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            _seed_archive(out)
            with self.assertRaises(ExportError) as ctx:
                build_export(
                    "xml", out, token="tok", env={"MEDIA_ARK_PRO_TOKENS": "tok"}
                )
            self.assertEqual(ctx.exception.error, "unknown_format")
            self.assertEqual(ctx.exception.status, 404)

    def test_build_export_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            _seed_archive(out)
            content, content_type, filename = build_export(
                "csv", out, token="tok", env={"MEDIA_ARK_PRO_TOKENS": "tok"}
            )
            self.assertIn("text/csv", content_type)
            self.assertEqual(filename, "media-ark-export.csv")
            parsed = list(csv.reader(io.StringIO(content.decode("utf-8"))))
            self.assertEqual(len(parsed), 3)  # header + 2 rows
            self.assertIn("a.png", content.decode("utf-8"))

    def test_build_export_zip_contains_manifest_and_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            _seed_archive(out)
            content, content_type, filename = build_export(
                "zip", out, token="tok", env={"MEDIA_ARK_PRO_TOKENS": "tok"}
            )
            self.assertEqual(content_type, "application/zip")
            self.assertEqual(filename, "media-ark-export.zip")
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
                self.assertIn("manifest.json", names)
                self.assertIn("sidecars/a_aaaaaaaaaa.png.json", names)
                # excluded helper files must not leak into the bundle
                self.assertNotIn("sidecars/config.json", names)
                self.assertNotIn("sidecars/old.backup.json", names)
                self.assertNotIn("sidecars/index-summary.json", names)

    def test_build_export_json_full(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            _seed_archive(out, owner="alice")
            content, content_type, filename = build_export(
                "json", out, token="tok", env={"MEDIA_ARK_PRO_TOKENS": "tok:alice"}
            )
            self.assertIn("application/json", content_type)
            self.assertEqual(filename, "media-ark-export.json")
            doc = json.loads(content.decode("utf-8"))
            self.assertEqual(doc["owner"], "alice")
            self.assertEqual(doc["manifest"]["run_id"], "case-1")
            self.assertEqual(len(doc["index"]), 2)
            self.assertEqual(doc["counts"]["index_rows"], 2)
            self.assertEqual(doc["counts"]["sidecars"], 1)

    def test_build_export_ownership_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            _seed_archive(out, owner="bob")
            with self.assertRaises(ExportError) as ctx:
                build_export(
                    "json", out, token="tok", env={"MEDIA_ARK_PRO_TOKENS": "tok:alice"}
                )
            self.assertEqual(ctx.exception.error, "ownership_denied")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_api(port: int, attempts: int = 30) -> None:
    # Probe the public static root: /api/status now requires a bearer token
    # (see test_platform_api.test_status_requires_auth), so an unauthenticated
    # readiness check against it would loop on 401 forever. Root serves the
    # dashboard without auth -- the canonical liveness probe used across the suite.
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise AssertionError("api did not become ready")


class TestExportApi(unittest.TestCase):
    def _start_server(self, port: int, pro_tokens: str | None):
        env = dict(os.environ)
        if pro_tokens is not None:
            env["MEDIA_ARK_PRO_TOKENS"] = pro_tokens
        else:
            env.pop("MEDIA_ARK_PRO_TOKENS", None)
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "src.platform.api_server",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )

    def test_export_csv_with_bearer_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth_db = root / "users.db"
            sandboxes = root / "sandboxes"
            env = dict(os.environ)
            env["MEDIA_ARK_USERS_DB"] = str(auth_db)
            env["MEDIA_ARK_USER_SANDBOX_ROOT"] = str(sandboxes)
            env["MEDIA_ARK_PRO_TOKENS"] = "tok1:alice"

            port = _free_port()
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "src.platform.api_server",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            try:
                _wait_for_api(port)
                # Register user alice
                reg_req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/auth/register",
                    data=json.dumps({"username": "alice", "password": "password123"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(reg_req) as resp:
                    alice_auth = json.loads(resp.read().decode("utf-8"))
                user_api_key = alice_auth["api_key"]
                alice_out = Path(alice_auth["out"])
                _seed_archive(alice_out)

                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/export/csv?out={alice_out}&token=tok1",
                    headers={"Authorization": f"Bearer {user_api_key}"},
                )
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(response.status, 200)
                    disposition = response.headers.get("Content-Disposition", "")
                    self.assertIn("media-ark-export.csv", disposition)
                    body = response.read().decode("utf-8")
                self.assertIn("a.png", body)
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_export_requires_bearer_auth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = dict(os.environ)
            env["MEDIA_ARK_USERS_DB"] = str(root / "users.db")
            env["MEDIA_ARK_USER_SANDBOX_ROOT"] = str(root / "sandboxes")
            env["MEDIA_ARK_PRO_TOKENS"] = "tok1"

            port = _free_port()
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "src.platform.api_server",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            try:
                _wait_for_api(port)
                # Request without AuthStore bearer token should return 401
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/export/json?token=tok1"
                    )
                self.assertEqual(ctx.exception.code, 401)
                payload = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertEqual(payload["error"], "unauthorized")
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_cross_sandbox_export_and_missing_manifest_owner_prevented(self) -> None:
        """Integration test with two users (attacker and victim) to ensure:
        - An authenticated Pro user cannot export another user's sandbox out path.
        - A missing/unreadable manifest.json owner never allows cross-user export.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = dict(os.environ)
            env["MEDIA_ARK_USERS_DB"] = str(root / "users.db")
            env["MEDIA_ARK_USER_SANDBOX_ROOT"] = str(root / "sandboxes")
            env["MEDIA_ARK_PRO_TOKENS"] = "attacker-pro-token:attacker"

            port = _free_port()
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "src.platform.api_server",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            try:
                _wait_for_api(port)
                # Register victim
                v_req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/auth/register",
                    data=json.dumps({"username": "victim", "password": "password123"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(v_req) as resp:
                    v_auth = json.loads(resp.read().decode("utf-8"))
                v_out = Path(v_auth["out"])
                # Seed victim archive without owner (unowned synthetic archive)
                _seed_archive(v_out, owner=None)

                # Register attacker
                a_req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/auth/register",
                    data=json.dumps({"username": "attacker", "password": "password123"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(a_req) as resp:
                    a_auth = json.loads(resp.read().decode("utf-8"))
                attacker_api_key = a_auth["api_key"]

                # Attacker tries to export victim's out directory
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/export/zip?out={v_out}&token=attacker-pro-token",
                    headers={"Authorization": f"Bearer {attacker_api_key}"},
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 400) # validation error: path outside allowed roots
                payload = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertEqual(payload["error"], "validation_error")
            finally:
                proc.terminate()
                proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
