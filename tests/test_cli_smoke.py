from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
import unittest


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestCliSmoke(unittest.TestCase):
    def test_cli_help(self) -> None:
        proc = subprocess.run(
            ["python3", "src/media_ark/process_captures.py", "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        text = proc.stdout.decode("utf-8", errors="ignore")
        self.assertIn("usage:", text.lower())

    def test_cli_dry_run(self) -> None:
        proc = subprocess.run(
            [
                "python3",
                "src/media_ark/process_captures.py",
                "/tmp",
                "--out",
                "/tmp/.media-ark",
                "--dry-run",
                "--json-report",
                "--max-files",
                "1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        raw = (proc.stdout or proc.stderr).decode("utf-8", errors="ignore")
        lines = [line for line in raw.splitlines() if line.strip()]
        self.assertTrue(lines)
        payload = json.loads(lines[-1])
        self.assertIn("mode", payload)
        self.assertIn("stats", payload)

    def test_capture_run_wrapper_resolves_processor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source"
            out = Path(tmpdir) / "out"
            source.mkdir()
            proc = subprocess.run(
                [
                    "./tools/media-ark/run_media_ark.sh",
                    str(source),
                    str(out),
                    "--dry-run",
                    "--json-report",
                    "--no-ocr",
                    "--no-thumbnails",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(
            proc.returncode, 0, proc.stderr.decode("utf-8", errors="ignore")
        )
        payload = json.loads(proc.stdout.decode("utf-8").splitlines()[-1])
        self.assertEqual(payload["mode"], "once")

    def test_capture_pipeline_wrapper_resolves_processor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source"
            out = Path(tmpdir) / "out"
            source.mkdir()
            proc = subprocess.run(
                [
                    "./tools/media-ark/media_ark_pipeline.sh",
                    str(source),
                    str(out),
                    "--no-ocr",
                    "--no-thumbnails",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(
            proc.returncode, 0, proc.stderr.decode("utf-8", errors="ignore")
        )
        self.assertIn(
            "media-ark pipeline complete", proc.stdout.decode("utf-8", errors="ignore")
        )

    def test_capture_watch_wrapper_resolves_processor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source"
            out = Path(tmpdir) / "out"
            source.mkdir()
            env = os.environ.copy()
            env.update(
                {
                    "MEDIA_ARK_MAX_RUNS": "1",
                    "MEDIA_ARK_WATCH_INTERVAL": "1",
                    "MEDIA_ARK_SELF_HEAL": "0",
                }
            )
            proc = subprocess.run(
                [
                    "./tools/media-ark/media_ark_watch.sh",
                    str(source),
                    str(out),
                    "--no-ocr",
                    "--no-thumbnails",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                env=env,
                timeout=20,
            )

        self.assertEqual(
            proc.returncode, 0, proc.stderr.decode("utf-8", errors="ignore")
        )

    def test_platform_start_script_serves_api_and_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            port = _free_port()
            root = Path(tmpdir)
            env = os.environ.copy()
            env.update(
                {
                    "MEDIA_ARK_PORT": str(port),
                    "MEDIA_ARK_SOURCE": str(root / "source"),
                    "MEDIA_ARK_OUT": str(root / "out"),
                    "MEDIA_ARK_USERS_DB": str(root / "auth" / "users.db"),
                    "MEDIA_ARK_USER_SANDBOX_ROOT": str(root / "auth" / "sandboxes"),
                }
            )
            proc = subprocess.Popen(
                ["./tools/media-ark/start_media_ark.sh"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                start_new_session=True,
            )
            try:
                status_payload = None
                page_text = ""
                deadline = time.time() + 20
                while time.time() < deadline:
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/", timeout=1
                        ) as response:
                            page_text = response.read().decode("utf-8")
                        break
                    except Exception:
                        if proc.poll() is not None:
                            break
                        time.sleep(0.25)

                if not page_text:
                    stdout, stderr = proc.communicate(timeout=5)
                    self.fail(
                        f"platform start did not become ready\nstdout={stdout}\nstderr={stderr}"
                    )

                if status_payload is None:
                    register_request = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/auth/register",
                        data=json.dumps(
                            {
                                "username": "tester",
                                "password": "correct horse battery",
                            }
                        ).encode("utf-8"),
                        method="POST",
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(register_request, timeout=2) as response:
                        auth_payload = json.loads(response.read().decode("utf-8"))

                    status_request = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/status",
                        headers={
                            "Authorization": f"Bearer {auth_payload['api_key']}"
                        },
                    )
                    with urllib.request.urlopen(status_request, timeout=2) as response:
                        status_payload = json.loads(response.read().decode("utf-8"))

                self.assertTrue(status_payload["ok"])
                self.assertEqual(status_payload["api_version"], "1.0")
                self.assertIn("Screen Capture Platform", page_text)
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
                if proc.stdout:
                    proc.stdout.close()
                if proc.stderr:
                    proc.stderr.close()

    def test_copy_mode_is_idempotent_for_unchanged_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source"
            out = Path(tmpdir) / "out"
            source.mkdir()
            sample = source / "Screen Shot 2026-06-08 at 10.00.00 AM.png"
            sample.write_bytes(b"sample image bytes")
            base_cmd = [
                "python3",
                "src/media_ark/process_captures.py",
                str(source),
                "--out",
                str(out),
                "--copy",
                "--no-ocr",
                "--no-thumbnails",
                "--json-report",
            ]

            first = subprocess.run(
                base_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
            )
            first_index = (out / "index.jsonl").read_text(encoding="utf-8")
            first_canonical_files = sorted(
                str(path.relative_to(out))
                for path in out.rglob("*")
                if path.is_file()
                and path.suffix.lower()
                in {".png", ".jpg", ".jpeg", ".pdf", ".mov", ".mp4"}
            )
            second = subprocess.run(
                base_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
            )
            second_index = (out / "index.jsonl").read_text(encoding="utf-8")
            second_canonical_files = sorted(
                str(path.relative_to(out))
                for path in out.rglob("*")
                if path.is_file()
                and path.suffix.lower()
                in {".png", ".jpg", ".jpeg", ".pdf", ".mov", ".mp4"}
            )

        self.assertEqual(
            first.returncode, 0, first.stderr.decode("utf-8", errors="ignore")
        )
        self.assertEqual(
            second.returncode, 0, second.stderr.decode("utf-8", errors="ignore")
        )
        first_payload = json.loads(first.stdout.decode("utf-8").splitlines()[-1])
        second_payload = json.loads(second.stdout.decode("utf-8").splitlines()[-1])
        self.assertEqual(first_payload["stats"]["new"], 1)
        self.assertEqual(first_payload["stats"]["skipped"], 0)
        self.assertEqual(second_payload["stats"]["new"], 0)
        self.assertEqual(second_payload["stats"]["skipped"], 1)
        self.assertEqual(second_index, first_index)
        self.assertEqual(second_canonical_files, first_canonical_files)

    def test_repair_recovers_manifest_and_index_from_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source"
            out = Path(tmpdir) / "out"
            source.mkdir()
            sample = source / "Screen Shot 2026-06-08 at 10.00.00 AM.png"
            sample.write_bytes(b"sample image bytes")
            base_cmd = [
                "python3",
                "src/media_ark/process_captures.py",
                str(source),
                "--out",
                str(out),
                "--copy",
                "--no-ocr",
                "--no-thumbnails",
                "--json-report",
            ]

            process = subprocess.run(
                base_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
            )
            self.assertEqual(
                process.returncode, 0, process.stderr.decode("utf-8", errors="ignore")
            )
            self.assertTrue((out / "manifest.json").exists())
            self.assertTrue((out / "index.jsonl").exists())
            sidecars = [
                path
                for path in out.glob("*.json")
                if path.name not in {"manifest.json", "index-summary.json"}
            ]
            self.assertEqual(len(sidecars), 1)

            (out / "manifest.json").unlink()
            (out / "index.jsonl").unlink()
            (out / "index-summary.json").unlink()

            verify_before = subprocess.run(
                base_cmd + ["--verify"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(verify_before.returncode, 2)
            verify_before_payload = json.loads(
                verify_before.stdout.decode("utf-8").splitlines()[-1]
            )
            self.assertEqual(verify_before_payload["health"]["sidecar_unindexed"], 1)

            repair = subprocess.run(
                base_cmd + ["--repair"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(
                repair.returncode, 0, repair.stderr.decode("utf-8", errors="ignore")
            )
            repair_payload = json.loads(repair.stdout.decode("utf-8").splitlines()[-1])
            self.assertEqual(repair_payload["summary"]["recovered_sidecars"], 1)
            self.assertEqual(repair_payload["summary"]["index_rows"], 1)

            verify_after = subprocess.run(
                base_cmd + ["--verify"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(
                verify_after.returncode,
                0,
                verify_after.stderr.decode("utf-8", errors="ignore"),
            )
            verify_after_payload = json.loads(
                verify_after.stdout.decode("utf-8").splitlines()[-1]
            )
            self.assertEqual(verify_after_payload["health"]["status"], "ok")
            self.assertEqual(verify_after_payload["health"]["index_rows"], 1)
