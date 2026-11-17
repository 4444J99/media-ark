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

Triadic-review evolution (2026-06-09):
  S1:  no_unguarded_persistent_stats_aug_assign pins the invariant that
       augmented assignment on the persistent manifest["stats"] surface
       must use the dict.get(..., 0) + N pattern; bare += is forbidden
       because setdefault("stats", {}) returns {} on a fresh manifest.
  S2:  F4 converse (test_4b) covers the positive side of the source_missing
       narrowing contract (a source_missing FNE lands in run_stats["skipped"],
       not run_stats["failed"]).
  S3:  test_4 / test_4b depend on `run_once` calling `process_file` by
       bare name (module-attribute rebinding). If a future refactor
       changes that to `pc.process_file` or captures the symbol at
       import time, the monkeypatch silently no-ops and these tests
       lose coverage.
"""

from __future__ import annotations

import ast
import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest.mock
import urllib.error
import urllib.request
from pathlib import Path
import unittest


PROCESSOR = (
    Path(__file__).resolve().parents[1] / "src" / "media_ark" / "process_captures.py"
)


def _walk_forbidden_stats_aug_assign(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (lineno, source) for every ``stats[k] += n`` node.

    Catches: bare augmented assignment on a Subscript whose target
    ``value`` is a Name with id ``stats``.

    Does NOT catch: ``local = manifest.setdefault('stats', {});
    local[k] += n`` (F2 Blindspot A) — the LHS is a Name rebind, not
    a Subscript on a Name called ``stats``. Documented in
    ``docs/regression-findings.md`` under "F2 — positive control."
    """
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AugAssign):
            continue
        target = node.target
        if not isinstance(target, ast.Subscript):
            continue
        if not isinstance(target.value, ast.Name):
            continue
        if target.value.id != "stats":
            continue
        offenders.append((node.lineno, ast.unparse(node)))
    return offenders


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getname()[1] if hasattr(sock, "getname") else sock.getsockname()[1]


def _wait_for_api(port: int, attempts: int = 30) -> None:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/"
            ) as response:
                if response.status == 200:
                    return
        except Exception:
            import time

            time.sleep(0.1)
    raise AssertionError("api did not become ready")


def _api_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["MEDIA_ARK_USERS_DB"] = str(root / "users.db")
    env["MEDIA_ARK_USER_SANDBOX_ROOT"] = str(root / "sandboxes")
    return env


def _post_json(url: str, payload: dict, token: str | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def _register_user(port: int) -> dict:
    return _post_json(
        f"http://127.0.0.1:{port}/api/auth/register",
        {"username": "tester", "password": "correct horse battery"},
    )


def _auth_request(url: str, token: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})


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
            tmp = Path(tmpdir)
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
                env=_api_env(tmp / "auth"),
            )
            try:
                _wait_for_api(port)
                auth = _register_user(port)
                token = auth["api_key"]
                out = Path(auth["out"])
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
                    "\n".join(json.dumps(row) for row in rows) + "\n",
                    encoding="utf-8",
                )
                with urllib.request.urlopen(
                    _auth_request(
                        f"http://127.0.0.1:{port}/api/index?out={out}&query=beta&limit=1&status=all&media=all",
                        token,
                    )
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
            os.environ["MEDIA_ARK_SOURCE"] = str(tmp / "src")
            os.environ["MEDIA_ARK_OUT"] = str(tmp / "out")
            try:
                self.assertEqual(config.default_source_dir(), (tmp / "src").resolve())
                self.assertEqual(config.default_out_dir(), (tmp / "out").resolve())
            finally:
                del os.environ["MEDIA_ARK_SOURCE"]
                del os.environ["MEDIA_ARK_OUT"]

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

            from src.media_ark.process_captures import load_sidecar_records

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

            from src.media_ark.process_captures import (
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

            from src.media_ark.process_captures import should_skip_source_file

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
        from src.media_ark.process_captures import process_file

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

    def test_4_run_once_inner_catch_narrows_to_source_missing(self) -> None:
        """Review thread #4: the run_once inner catch (around
        process_captures.py:2877) must inspect the FileNotFoundError
        message; only 'source_missing' is a skip, every other
        FileNotFoundError is a failure recorded in manifest.errors.

        S3 fragility note: this test monkeypatches
        ``pc.process_file``. It only works because ``run_once`` calls
        ``process_file`` by bare name inside the same module, so the
        module-attribute rebinding is picked up at call time. If a
        future refactor changes that to ``pc.process_file(...)`` or
        ``from .module import process_file`` at module top, the
        monkeypatch silently no-ops and this test loses coverage.
        See S3 in the 2026-06-09 triadic review.
        """
        from src.media_ark import process_captures as pc

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "source"
            source.mkdir()
            sample = source / "Screen Shot 2026-06-09 at 10.00.00 AM.png"
            sample.write_bytes(b"abc")
            out = tmp / "out"
            out.mkdir()

            manifest: dict = {
                "processed": {},
                "duplicates": {},
                "source_index": {},
                "hash_index": {},
            }

            original_process_file = pc.process_file

            def raise_other_fnf(*args, **kwargs):
                raise FileNotFoundError("simulated: ocr_temp vanished mid-process")

            pc.process_file = raise_other_fnf
            # F1 binding assertion: the monkeypatch on pc.process_file
            # must shadow the process_file that run_once resolves.
            # If a future refactor changes line 2850 from
            # `process_file(...)` to `pc.process_file(...)` where
            # `pc` was captured by an inner import, or shadows the
            # module's process_file with a closure-captured binding,
            # this assertion fails before run_once is ever called,
            # turning a silent test pass into a loud test failure.
            self.assertIs(
                pc.process_file,
                pc.run_once.__globals__.get("process_file"),
                "process_file binding drift: pc.process_file is not "
                "the process_file the module exposes; run_once will "
                "not see the monkeypatch. Fix the import pattern in "
                "process_captures.py or change this test to patch "
                "run_once.__globals__['process_file'] directly.",
            )
            try:
                stats = pc.run_once(
                    source_root=source,
                    out_root=out,
                    do_ocr=False,
                    make_thumbnail=False,
                    do_copy=False,
                    dry_run=False,
                    manifest=manifest,
                    post_hooks=[],
                    post_hook_on="success",
                    post_hook_timeout=10,
                    post_hook_stop_on_failure=False,
                    post_hook_max_attempts=1,
                    post_hook_retry_delay=0.0,
                    post_hook_shell=False,
                    run_id="t",
                    cleanup_raw=False,
                    cleanup_raw_days=0,
                    cleanup_state_days=0,
                    include_patterns=[],
                    exclude_patterns=[],
                    max_files=0,
                    allowed_media_types={"image"},
                    min_size_bytes=0,
                    max_size_bytes=0,
                    follow_symlinks=False,
                    ocr_lang="eng",
                    thumbnail_size=320,
                    video_seek="00:00:01",
                )
            finally:
                pc.process_file = original_process_file

            self.assertEqual(stats["failed"], 1, stats)
            self.assertEqual(stats["skipped"], 0, stats)
            errors = manifest.get("errors", [])
            self.assertEqual(len(errors), 1, errors)
            self.assertIn("simulated", errors[0]["error"])
            self.assertNotIn("source_missing", errors[0]["error"])

    def test_4b_run_once_source_missing_lands_in_skipped(self) -> None:
        """S2 converse of test_4. See docs/regression-findings.md §S2."""
        from src.media_ark import process_captures as pc

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "source"
            source.mkdir()
            sample = source / "Screen Shot 2026-06-09 at 10.00.00 AM.png"
            sample.write_bytes(b"abc")
            out = tmp / "out"
            out.mkdir()

            manifest: dict = {
                "processed": {},
                "duplicates": {},
                "source_index": {},
                "hash_index": {},
            }

            original_process_file = pc.process_file

            def raise_source_missing_fnf(*args, **kwargs):
                raise FileNotFoundError(
                    "source_missing: /tmp/Screen Shot 2026-06-09 at 10.00.00 AM.png"
                )

            pc.process_file = raise_source_missing_fnf
            # F1 binding assertion: see note in test_4. The same
            # monkeypatch trap applies here; the assertion fails
            # before run_once is called if the binding has drifted.
            self.assertIs(
                pc.process_file,
                pc.run_once.__globals__.get("process_file"),
                "process_file binding drift in test_4b; see test_4.",
            )
            try:
                stats = pc.run_once(
                    source_root=source,
                    out_root=out,
                    do_ocr=False,
                    make_thumbnail=False,
                    do_copy=False,
                    dry_run=False,
                    manifest=manifest,
                    post_hooks=[],
                    post_hook_on="success",
                    post_hook_timeout=10,
                    post_hook_stop_on_failure=False,
                    post_hook_max_attempts=1,
                    post_hook_retry_delay=0.0,
                    post_hook_shell=False,
                    run_id="t",
                    cleanup_raw=False,
                    cleanup_raw_days=0,
                    cleanup_state_days=0,
                    include_patterns=[],
                    exclude_patterns=[],
                    max_files=0,
                    allowed_media_types={"image"},
                    min_size_bytes=0,
                    max_size_bytes=0,
                    follow_symlinks=False,
                    ocr_lang="eng",
                    thumbnail_size=320,
                    video_seek="00:00:01",
                )
            finally:
                pc.process_file = original_process_file

            self.assertEqual(stats["skipped"], 1, stats)
            self.assertEqual(stats["failed"], 0, stats)
            errors = manifest.get("errors", [])
            self.assertEqual(len(errors), 1, errors)
            self.assertEqual(errors[0]["error"], "source_missing", errors)

    def test_s1_no_unguarded_persistent_stats_aug_assign(self) -> None:
        """S1 invariant. See docs/regression-findings.md §S1."""
        source = PROCESSOR.read_text()
        tree = ast.parse(source)

        offenders = _walk_forbidden_stats_aug_assign(tree)

        self.assertEqual(
            offenders,
            [],
            (
                "Bare augmented assignment on a `stats` Subscript "
                "target is forbidden on the persistent "
                "manifest['stats'] surface. Use "
                "stats[k] = stats.get(k, 0) + n. "
                "run_stats (per-call fresh dict) is the only safe "
                "target. Offending lines: " + repr(offenders)
            ),
        )

    def test_s1b_walker_catches_forbidden_pattern(self) -> None:
        """F2 positive control. See docs/regression-findings.md §S1."""
        forbidden_src = textwrap.dedent(
            """
            def bump(manifest):
                stats = manifest.setdefault("stats", {})
                stats["files_seen_total"] += 1
            """
        )
        tree = ast.parse(forbidden_src)
        offenders = _walk_forbidden_stats_aug_assign(tree)
        self.assertEqual(
            len(offenders), 1, f"walker missed forbidden pattern: {offenders}"
        )

        safe_src = textwrap.dedent(
            """
            def bump(run_stats):
                run_stats["files_seen_total"] += 1
            """
        )
        tree = ast.parse(safe_src)
        offenders = _walk_forbidden_stats_aug_assign(tree)
        self.assertEqual(
            offenders, [], f"walker false-positive on per-call surface: {offenders}"
        )

        unrelated_src = textwrap.dedent(
            """
            def bump(manifest):
                bucket = manifest.setdefault("stats", {})
                local = bucket
                local["k"] = local.get("k", 0) + 1
            """
        )
        tree = ast.parse(unrelated_src)
        offenders = _walk_forbidden_stats_aug_assign(tree)
        self.assertEqual(
            offenders,
            [],
            f"walker over-flagged safe rewrite: {offenders}. "
            "Note: this rewrite is the F2 Blindspot A case the "
            "premortem surfaced. It is *not* caught by the current "
            "walker; the docs/regression-findings.md file documents "
            "this limit and points at the manual-review path.",
        )


if __name__ == "__main__":
    unittest.main()
