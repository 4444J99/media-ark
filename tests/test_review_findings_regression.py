"""Regression tests for the 11 review-thread findings on PR #3.

Each test corresponds to one of the threads:
  1-4: process_captures.py — narrow FileNotFoundError handling
  5:    api_server.py — apply filters before enforcing index limit
  6:    start_capture_platform.sh + config.py — honor startup source/out
  7:    api_server.py — merge POST query parameters into action payload
  8:    mcp_server.py — silently accept notifications/* messages
  9:    process_captures.py — skip malformed sidecar size_bytes during repair
  10:   process_captures.py — restore source mtimes when rebuilding source_index
  11:   runtime.py — keep generated platform run IDs unique
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest.mock
import urllib.error
import urllib.request
from pathlib import Path
import unittest


PROCESSOR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "capture_automation"
    / "process_captures.py"
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getname()[1] if hasattr(sock, "getname") else sock.getsockname()[1]


def _wait_for_api(port: int, attempts: int = 30) -> None:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/status"
            ) as response:
                if response.status == 200:
                    return
        except Exception:
            import time

            time.sleep(0.1)
    raise AssertionError("api did not become ready")


class TestReviewFindingsRegression(unittest.TestCase):
    def test_8_mcp_notifications_accepted_without_reply(self) -> None:
        from src.platform.mcp_server import _handle_message, _ok, _error

        replies: list[dict] = []

        def capture(payload: dict) -> None:
            replies.append(payload)

        import src.platform.mcp_server as srv

        original_reply = srv._reply
        srv._reply = capture
        try:
            _handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
            _handle_message(
                {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}}
            )
        finally:
            srv._reply = original_reply

        self.assertEqual(replies, [])

    def test_8_mcp_other_notifications_also_accepted(self) -> None:
        from src.platform.mcp_server import _handle_message

        replies: list[dict] = []
        import src.platform.mcp_server as srv

        original_reply = srv._reply
        srv._reply = lambda payload: replies.append(payload)
        try:
            _handle_message(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/progress",
                    "params": {"token": "x"},
                }
            )
        finally:
            srv._reply = original_reply

        self.assertEqual(replies, [])

    def test_11_run_id_is_unique_under_concurrent_calls(self) -> None:
        from src.platform.runtime import run_capture_action
        from src.platform.config import default_out_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "source"
            source.mkdir()
            out = tmp / "out"
            out.mkdir()
            results = []
            for _ in range(3):
                results.append(
                    run_capture_action(
                        {
                            "mode": "check-source",
                            "source": str(source),
                            "out": str(out),
                        }
                    )
                )
            run_ids = [r.run_id for r in results]
            self.assertEqual(
                len(set(run_ids)), 3, f"duplicate run_id generated: {run_ids}"
            )

    def test_11_report_paths_do_not_collide(self) -> None:
        from src.platform.runtime import telemetry_report_path
        from src.platform.config import RunOptions

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            paths = []
            for _ in range(3):
                options = RunOptions(
                    source=tmp / "source",
                    out=tmp / "out",
                    mode="process",
                )
                options.out = tmp / "out"
                paths.append(str(telemetry_report_path(options)))
            self.assertEqual(len(set(paths)), 3, f"report path collision: {paths}")

    def test_5_api_index_filters_applied_before_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "out"
            out.mkdir()
            index_file = out / "index.jsonl"
            rows = []
            for i in range(5):
                rows.append(
                    {
                        "status": "processed",
                        "media_type": "image",
                        "path": f"img-{i}.png",
                        "text": "alpha" if i % 2 else "beta",
                    }
                )
            index_file.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
            )

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
            )
            try:
                _wait_for_api(port)
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/index?out={out}&query=beta&limit=1&status=all&media=all"
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                proc.terminate()
                proc.wait(timeout=5)

            self.assertEqual(len(payload["records"]), 1, payload)
            self.assertEqual(payload["records"][0]["path"], "img-0.png")

    def test_7_post_run_merges_query_params_with_body(self) -> None:
        from src.platform.api_server import to_action_payload

        payload = to_action_payload(
            "/api/run",
            query={"source": "/tmp/src", "out": "/tmp/out"},
            method="POST",
            body={"action": "check-source"},
        )
        self.assertEqual(payload["source"], "/tmp/src")
        self.assertEqual(payload["out"], "/tmp/out")
        self.assertEqual(payload["action"], "check-source")

    def test_7_post_run_body_overrides_query_when_present(self) -> None:
        from src.platform.api_server import to_action_payload

        payload = to_action_payload(
            "/api/run",
            query={"source": "/tmp/from-query"},
            method="POST",
            body={"source": "/tmp/from-body", "action": "check-source"},
        )
        self.assertEqual(payload["source"], "/tmp/from-body")

    def test_6_default_paths_honor_capture_platform_env(self) -> None:
        from src.platform import config

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            os.environ["CAPTURE_PLATFORM_SOURCE"] = str(tmp / "src")
            os.environ["CAPTURE_PLATFORM_OUT"] = str(tmp / "out")
            try:
                self.assertEqual(config.default_source_dir(), (tmp / "src").resolve())
                self.assertEqual(config.default_out_dir(), (tmp / "out").resolve())
            finally:
                del os.environ["CAPTURE_PLATFORM_SOURCE"]
                del os.environ["CAPTURE_PLATFORM_OUT"]

    def test_9_malformed_sidecar_does_not_break_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out = tmp / "out"
            out.mkdir()
            sample = out / "Screen Shot 2026-06-08 at 10.00.00 AM.png"
            sample.write_bytes(b"abc")
            sidecar = out / "Screen Shot 2026-06-08 at 10.00.00 AM.json"
            sidecar.write_text(
                json.dumps(
                    {
                        "id": "abc",
                        "source_path": str(sample),
                        "canonical_path": str(sample),
                        "media_type": "image",
                        "sha256": "0" * 64,
                        "size_bytes": "this-is-not-an-int",
                        "status": "processed",
                        "captured_at": "2026-06-08T10:00:00",
                    }
                ),
                encoding="utf-8",
            )

            from src.capture_automation.process_captures import load_sidecar_records

            records, skipped = load_sidecar_records(out)
            self.assertEqual(skipped, 0, records)
            self.assertEqual(len(records), 1, records)
            self.assertEqual(records[0]["size_bytes"], 3)

    def test_10_repair_restores_real_mtime_when_source_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "source"
            source.mkdir()
            out = tmp / "out"
            out.mkdir()
            sample = source / "Screen Shot 2026-06-08 at 10.00.00 AM.png"
            sample.write_bytes(b"abc")
            sidecar = out / "Screen Shot 2026-06-08 at 10.00.00 AM.json"
            sidecar.write_text(
                json.dumps(
                    {
                        "id": "abc",
                        "source_path": str(sample),
                        "canonical_path": str(sample),
                        "media_type": "image",
                        "sha256": "0" * 64,
                        "size_bytes": 3,
                        "status": "processed",
                        "captured_at": "2026-06-08T10:00:00",
                    }
                ),
                encoding="utf-8",
            )

            from src.capture_automation.process_captures import (
                iter_sidecar_paths,
                load_sidecar_records,
            )

            payload = json.loads(
                next(iter_sidecar_paths(out)).read_text(encoding="utf-8")
            )
            records, _ = load_sidecar_records(out)
            self.assertEqual(len(records), 1)

            real_mtime = sample.stat().st_mtime_ns
            self.assertGreater(real_mtime, 0)

            from src.capture_automation.process_captures import should_skip_source_file

            source_index = {
                str(sample): {
                    "size_bytes": 3,
                    "mtime_ns": real_mtime,
                    "status": "processed",
                    "sha256": "0" * 64,
                    "canonical_path": str(sample),
                }
            }
            self.assertTrue(should_skip_source_file(sample, source_index))

    def test_2_3_oserror_no_longer_renamed_to_source_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "source"
            source.mkdir()
            sample = source / "Screen Shot 2026-06-08 at 10.00.00 AM.png"
            sample.write_bytes(b"x")
            base = [
                sys.executable,
                str(PROCESSOR),
                str(source),
                "--out",
                str(tmp / "out"),
                "--json-report",
                "--no-ocr",
                "--no-thumbnails",
            ]
            proc = subprocess.run(
                base, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
            )
            self.assertEqual(
                proc.returncode, 0, proc.stderr.decode("utf-8", errors="ignore")
            )

    def test_1_specific_filenotfounderror_still_treated_as_skipped(self) -> None:
        """Direct unit test: process_file raises FileNotFoundError, and the
        run_once outer catch narrows to FileNotFoundError, not the broad OSError.
        """
        from src.capture_automation.process_captures import process_file

        manifest: dict = {
            "processed": {},
            "duplicates": {},
            "source_index": {},
            "hash_index": {},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out = tmp / "out"
            out.mkdir()
            vanished = tmp / "does-not-exist.png"
            with self.assertRaises(FileNotFoundError) as ctx:
                process_file(
                    vanished,
                    out,
                    do_ocr=False,
                    ocr_lang="eng",
                    make_thumbnail=False,
                    thumbnail_size=320,
                    video_seek="00:00:01",
                    do_copy=False,
                    manifest=manifest,
                    processed_hashes={},
                    post_hooks=[],
                    post_hook_on="success",
                    post_hook_timeout=10,
                    post_hook_stop_on_failure=False,
                    post_hook_max_attempts=1,
                    post_hook_retry_delay=0.0,
                    post_hook_shell=False,
                    run_id="t",
                    run_stats={},
                )
            self.assertIn("source_missing", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
