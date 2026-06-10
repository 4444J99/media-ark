from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.platform.runtime import _safe_parse_json, build_command_for_mode, parse_options
from src.platform.config import (
    PlatformValidationError,
    default_out_dir,
    default_source_dir,
    processor_script,
    repo_root,
)


class TestPlatformRuntime(unittest.TestCase):
    def test_parse_options_defaults(self) -> None:
        payload = {}
        options = parse_options(payload)

        self.assertEqual(options.mode, "process")
        self.assertEqual(options.media_types, "all")
        self.assertEqual(options.max_files, 0)
        self.assertEqual(options.query, "")
        self.assertEqual(options.timeout_sec, 120)
        self.assertEqual(options.source, default_source_dir())
        self.assertEqual(options.out, default_out_dir())
        self.assertTrue(str(options.source).startswith(str(repo_root())))
        self.assertTrue(str(options.out).startswith(str(repo_root())))

    def test_parse_options_aliases_and_bool_coercion(self) -> None:
        payload = {
            "source": "foo",
            "out": "bar",
            "copy": "true",
            "noOcr": "1",
            "noThumbnails": "on",
            "maxFiles": "9",
            "queryMedia": "video",
            "queryStatus": "duplicate",
            "queryLimit": "12",
            "timeout": "30",
        }
        options = parse_options(payload)

        self.assertEqual(options.source, Path("foo").resolve())
        self.assertEqual(options.out, Path("bar").resolve())
        self.assertEqual(options.copy, True)
        self.assertEqual(options.no_ocr, True)
        self.assertEqual(options.no_thumbnails, True)
        self.assertEqual(options.max_files, 9)
        self.assertEqual(options.query_media, "video")
        self.assertEqual(options.query_status, "duplicate")
        self.assertEqual(options.query_limit, 12)
        self.assertEqual(options.timeout_sec, 30)

    def test_safe_parse_json_prefers_last_json(self) -> None:
        payload = "\n".join(["log line", '{"answer": 42}', "noise"])
        self.assertEqual(_safe_parse_json(payload), {"answer": 42})

    def test_build_command_for_query_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            payload = {
                "mode": "query",
                "source": str(root / "source"),
                "out": str(root / "out"),
                "query": "meeting",
                "query_media": "image",
                "query_status": "processed",
                "query_limit": 15,
            }
            command = build_command_for_mode(parse_options(payload))

        self.assertIn(str(processor_script()), command)
        self.assertIn("--query", command)
        self.assertIn("meeting", command)
        self.assertIn("--query-media", command)
        self.assertIn("image", command)
        self.assertIn("--query-status", command)
        self.assertIn("processed", command)
        self.assertIn("--query-limit", command)
        self.assertIn("15", command)
        self.assertIn("--event-log", command)
        self.assertIn("--report", command)
        report_path = Path(command[command.index("--report") + 1])
        event_log_path = Path(command[command.index("--event-log") + 1])
        self.assertEqual(event_log_path.name, "platform-events.jsonl")
        self.assertTrue(report_path.name.startswith("platform-query-"))

    def test_parse_options_rejects_paths_outside_allowed_roots(self) -> None:
        with self.assertRaises(PlatformValidationError):
            parse_options({"source": "/etc", "out": str(default_out_dir())})

    def test_parse_options_bounds_numeric_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(PlatformValidationError):
                parse_options(
                    {
                        "source": str(root / "source"),
                        "out": str(root / "out"),
                        "query_limit": 5001,
                    }
                )

    def test_processor_script_is_under_repo_root(self) -> None:
        script = processor_script()
        self.assertEqual(script.name, "process_captures.py")
        self.assertIn("media_ark", str(script))
        self.assertIn("/src/", str(script))
        self.assertNotIn("/src/src/", str(script))
