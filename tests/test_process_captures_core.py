from __future__ import annotations

import argparse
import contextlib
import io
import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.media_ark import process_captures as pc


def _manifest(out: Path) -> dict:
    return pc.load_manifest(out / "manifest.json")


def _run_once(source: Path, out: Path, manifest: dict, **overrides) -> dict:
    params = {
        "source_root": source,
        "out_root": out,
        "do_ocr": False,
        "make_thumbnail": False,
        "do_copy": True,
        "dry_run": False,
        "manifest": manifest,
        "post_hooks": [],
        "post_hook_on": "processed",
        "post_hook_timeout": 10,
        "post_hook_stop_on_failure": False,
        "post_hook_max_attempts": 0,
        "post_hook_retry_delay": 0.0,
        "post_hook_shell": False,
        "run_id": "test-run",
        "cleanup_raw": False,
        "cleanup_raw_days": 0,
        "cleanup_state_days": 0,
        "include_patterns": [],
        "exclude_patterns": [],
        "max_files": 0,
        "allowed_media_types": {"all", "image", "video", "document"},
        "min_size_bytes": 0,
        "max_size_bytes": 0,
        "follow_symlinks": False,
        "ocr_lang": "eng",
        "thumbnail_size": 320,
        "video_seek": "00:00:01",
    }
    params.update(overrides)
    with mock.patch.object(pc, "command_exists", return_value=False):
        return pc.run_once(**params)


class TestProcessCapturesCore(unittest.TestCase):
    def test_discover_media_files_applies_filters_and_skips_output_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source"
            out = source / ".media-ark"
            docs = source / "docs"
            docs.mkdir(parents=True)
            out.mkdir(parents=True)

            (source / "keep.png").write_bytes(b"image")
            (source / "tiny.png").write_bytes(b"x")
            (source / "movie.mp4").write_bytes(b"video")
            (source / ".hidden.png").write_bytes(b"hidden")
            (docs / "report.pdf").write_bytes(b"pdfdata")
            (docs / "private.pdf").write_bytes(b"pdfdata")
            (out / "leaked.png").write_bytes(b"image")

            files = list(
                pc.discover_media_files(
                    source,
                    out_root=out,
                    include_patterns=["*.png", "docs/*.pdf", ".media-ark/*.png"],
                    exclude_patterns=["docs/private.pdf"],
                    allowed_media_types={"image", "document"},
                    min_size_bytes=2,
                    max_size_bytes=10,
                    follow_symlinks=False,
                )
            )

        self.assertEqual(
            sorted(path.relative_to(source.resolve()).as_posix() for path in files),
            ["docs/report.pdf", "keep.png"],
        )

    def test_run_once_processes_image_and_writes_manifest_index_and_sidecar(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            out = root / "out"
            source.mkdir()
            sample = source / "Screen Shot 2026-06-10 at 03.04.05 PM.png"
            sample.write_bytes(b"image-one")
            manifest = _manifest(out)

            stats = _run_once(source, out, manifest)

            processed = manifest["processed"][str(sample.resolve())]
            canonical = Path(processed["canonical_path"])
            sidecar = out / f"{canonical.name}.json"
            rows = pc.load_index_records(out)
            source_exists = sample.exists()
            canonical_exists = canonical.exists()
            sidecar_exists = sidecar.exists()

        self.assertEqual(stats["discovered"], 1)
        self.assertEqual(stats["new"], 1)
        self.assertEqual(stats["duplicates"], 0)
        self.assertEqual(stats["index_rows"], 1)
        self.assertTrue(source_exists, "copy mode should preserve the raw source")
        self.assertTrue(canonical_exists)
        self.assertEqual(canonical.parent, out / "image" / "2026" / "06")
        self.assertTrue(canonical.name.startswith("20260610_150405_"))
        self.assertTrue(sidecar_exists)
        self.assertEqual(rows[0]["canonical_path"], str(canonical))
        self.assertEqual(rows[0]["captured_at"], "2026-06-10T15:04:05")
        self.assertEqual(rows[0]["status"], "processed")
        self.assertEqual(
            manifest["source_index"][str(sample.resolve())]["status"], "processed"
        )

    def test_duplicate_sources_are_preserved_as_queryable_index_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            out = root / "out"
            source.mkdir()
            first = source / "Screen Shot 2026-06-10 at 10.00.00 AM.png"
            duplicate = source / "Screen Shot 2026-06-10 at 10.01.00 AM.png"
            first.write_bytes(b"same-bytes")
            duplicate.write_bytes(b"same-bytes")
            manifest = _manifest(out)

            stats = _run_once(source, out, manifest)
            rows = pc.load_index_records(out)
            summary = json.loads((out / "index-summary.json").read_text())

        self.assertEqual(stats["new"], 1)
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual(stats["index_rows"], 2)
        self.assertEqual(manifest["stats"]["duplicates"], 1)
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["duplicates"], 1)
        self.assertEqual(
            sorted(row["status"] for row in rows), ["duplicate", "processed"]
        )
        self.assertEqual(
            {row["source_path"] for row in rows},
            {str(first.resolve()), str(duplicate.resolve())},
        )
        canonical_paths = {row["canonical_path"] for row in rows}
        self.assertEqual(len(canonical_paths), 1)

    def test_processed_post_hook_results_are_persisted_to_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            out = root / "out"
            source.mkdir()
            sample = source / "Screen Shot 2026-06-10 at 11.00.00 AM.png"
            sample.write_bytes(b"hooked")
            manifest = _manifest(out)
            hook = shlex.join(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdin.read(); print('hook-ok')",
                ]
            )

            stats = _run_once(source, out, manifest, post_hooks=[hook])
            canonical = Path(
                manifest["processed"][str(sample.resolve())]["canonical_path"]
            )
            sidecar = json.loads((out / f"{canonical.name}.json").read_text())

        self.assertEqual(stats["post_hook_attempts"], 1)
        self.assertEqual(stats["post_hook_success"], 1)
        self.assertEqual(manifest["stats"]["post_hook_success"], 1)
        self.assertEqual(sidecar["post_hook_results"][0]["status"], "ok")
        self.assertEqual(sidecar["post_hook_results"][0]["stdout"], "hook-ok")

    def test_run_query_filters_status_media_dates_and_emits_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "out"
            out.mkdir()
            pc.write_index_rows(
                out,
                [
                    {
                        "id": "1",
                        "source_path": "/tmp/a.png",
                        "canonical_path": "/tmp/a.png",
                        "media_type": "image",
                        "status": "processed",
                        "captured_at": "2026-06-12T09:00:00",
                        "title": "Quarterly planning",
                        "ocr_text": "budget planning notes",
                        "tags": ["budget"],
                        "sha256": "a" * 64,
                        "size_bytes": 10,
                    },
                    {
                        "id": "2",
                        "source_path": "/tmp/b.mp4",
                        "canonical_path": "/tmp/b.mp4",
                        "media_type": "video",
                        "status": "processed",
                        "captured_at": "2026-06-12T10:00:00",
                        "title": "Budget recording",
                        "ocr_text": "",
                        "tags": [],
                        "sha256": "b" * 64,
                        "size_bytes": 20,
                    },
                    {
                        "id": "3",
                        "source_path": "/tmp/c.png",
                        "canonical_path": "/tmp/a.png",
                        "media_type": "image",
                        "status": "duplicate",
                        "captured_at": "2026-06-13T09:00:00",
                        "title": "budget duplicate",
                        "ocr_text": "",
                        "tags": [],
                        "sha256": "a" * 64,
                        "size_bytes": 10,
                    },
                ],
            )
            args = argparse.Namespace(
                query="budget",
                query_media="image",
                query_status="processed",
                query_limit=10,
                query_format="json",
                since="2026-06-11",
                until="2026-06-12T23:59:59",
                json_report=True,
                report="",
                json_report_format="json",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                matched = pc.run_query(out, args)
            payload = json.loads(stdout.getvalue())

        self.assertEqual(matched, 1)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["matches"][0]["id"], "1")
        self.assertEqual(payload["matches_paths"], ["/tmp/a.png"])

    def test_repair_prunes_missing_index_rows_and_recovers_sidecar_records(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            out = root / "out"
            canonical = out / "image" / "2026" / "06" / "capture.png"
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(b"image")
            sidecar = out / "capture.png.json"
            sidecar.write_text(
                json.dumps(
                    {
                        "id": "abc",
                        "source_path": str(root / "source" / "capture.png"),
                        "canonical_path": str(canonical),
                        "media_type": "image",
                        "sha256": "0" * 64,
                        "size_bytes": 5,
                        "status": "processed",
                        "captured_at": "2026-06-10T12:00:00",
                    }
                ),
                encoding="utf-8",
            )
            missing = out / "image" / "2026" / "06" / "missing.png"
            pc.write_index_rows(
                out,
                [
                    {
                        "id": "missing",
                        "source_path": str(root / "source" / "missing.png"),
                        "canonical_path": str(missing),
                        "media_type": "image",
                        "status": "processed",
                        "captured_at": "2026-06-09T12:00:00",
                        "sha256": "1" * 64,
                        "size_bytes": 1,
                    }
                ],
            )
            manifest = {
                "processed": {
                    "stale": {
                        "canonical_path": str(missing),
                        "sha256": "1" * 64,
                        "size_bytes": 1,
                        "status": "processed",
                    }
                },
                "duplicates": {},
                "source_index": {},
                "hash_index": {"1" * 64: str(missing)},
                "stats": {},
            }

            before = pc.run_health_check(out, manifest)
            summary = pc.run_repair_state(out, manifest)
            after = pc.run_health_check(out, manifest)
            rows = pc.load_index_records(out)

        self.assertEqual(before["status"], "degraded")
        self.assertEqual(before["index_orphaned"], 1)
        self.assertEqual(summary["pruned_index_rows"], 1)
        self.assertEqual(summary["recovered_sidecars"], 1)
        self.assertEqual(summary["index_rows"], 1)
        self.assertEqual(after["status"], "ok")
        self.assertEqual(rows[0]["canonical_path"], str(canonical.resolve()))
        self.assertIn(str(root / "source" / "capture.png"), manifest["processed"])


if __name__ == "__main__":
    unittest.main()
