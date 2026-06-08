#!/usr/bin/env python3
"""
Capture processing pipeline for screenshot/video folders.

Stages:
1) Ingest: discover media files and compute fingerprint
2) Process: move/copy to canonical structure and normalize metadata
3) Enrich: extract OCR, thumbnails, and generated metadata index

No external Python dependencies required. Optional tooling used if present:
- tesseract: OCR
- ffprobe / ffmpeg: video metadata + optional poster frame
- sips: image metadata and thumbnail generation (macOS)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import csv
import errno
from contextlib import contextmanager
import fnmatch
import shlex
import re
import shutil
import subprocess
import sys
import time
import random
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Iterator
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unicodedata

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".heic", ".avif"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".webm", ".avi", ".mkv", ".mpg", ".mpeg"}
DOCUMENT_EXTS = {".pdf"}
ALL_EXTS = IMAGE_EXTS | VIDEO_EXTS | DOCUMENT_EXTS

TIMESTAMP_PATTERNS = [
    re.compile(r"(?P<ymd>\d{4}-\d{2}-\d{2}) at (?P<time>\d{2}[.:]\d{2}[.:]\d{2}) (?P<ampm>AM|PM)", re.IGNORECASE),
    re.compile(r"(?P<ymd>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}[.:]\d{2}[.:]\d{2})"),
]

STOP_WORDS = {
    "the", "and", "you", "that", "was", "for", "with", "this", "have", "just", "into", "from",
    "about", "were", "will", "your", "their", "when", "where", "what", "which", "there", "here",
    "would", "could", "should", "them", "then", "been", "they", "than",
}


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s: %(message)s",
    )


def run_cmd(cmd: List[str], *, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)


def truncate_text(value: Optional[str], *, max_chars: int = 1600) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        return False


def read_lock_payload(lock_path: Path) -> Dict[str, Any]:
    try:
        return json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@contextmanager
def acquire_run_lock(
    lock_path: Path,
    *,
    run_id: str,
    timeout_seconds: int,
    stale_seconds: int,
) -> None:
    lock_path = lock_path.resolve()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "pid": os.getpid(),
        "started_at": now_utc_iso(),
        "started_at_epoch": time.time(),
    }
    deadline = time.time() + max(0.0, float(timeout_seconds))
    while True:
        try:
            with lock_path.open("x", encoding="utf-8") as fp:
                fp.write(json.dumps(payload))
            logging.info("Acquired run lock: %s", lock_path)
            break
        except FileExistsError:
            existing = read_lock_payload(lock_path)
            existing_pid = existing.get("pid")
            existing_run_id = str(existing.get("run_id", ""))
            existing_epoch = existing.get("started_at_epoch", 0.0)
            if not isinstance(existing_epoch, (int, float)):
                existing_epoch = 0.0

            is_stale = False
            if not isinstance(existing_pid, int) or not is_process_alive(existing_pid):
                is_stale = True
            elif time.time() - float(existing_epoch) > max(1.0, float(stale_seconds)):
                is_stale = True

            if is_stale:
                try:
                    lock_path.unlink()
                    logging.warning(
                        "Removed stale lock (run_id=%s pid=%s). Taking over.",
                        existing_run_id,
                        existing_pid,
                    )
                except OSError:
                    logging.exception("Failed to remove stale lock at %s", lock_path)
                continue

            if timeout_seconds <= 0 or time.time() >= deadline:
                raise SystemExit(
                    f"Another capture run is active (run_id={existing_run_id}, pid={existing_pid}). "
                    "Use --disable-lock or wait and retry."
                )
            time.sleep(1.0)

    try:
        yield
    finally:
        try:
            current = read_lock_payload(lock_path)
            if current.get("run_id") == run_id:
                lock_path.unlink()
                logging.info("Released run lock: %s", lock_path)
        except FileNotFoundError:
            pass
        except OSError:
            logging.debug("Unable to release run lock %s cleanly", lock_path)


@contextmanager
def noop_run_lock() -> Iterator[None]:
    yield


def command_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def sha256_for_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    path = resolve_media_path(path)
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def is_within_dir(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    except OSError:
        return False
    return True


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_filename_lookup(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\u00a0", " ")
    normalized = normalized.replace("\u202f", " ")
    normalized = normalized.replace("\u2009", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def resolve_media_path(path: Path) -> Path:
    if path.exists():
        return path

    parent = path.parent
    if not parent.is_dir():
        return path

    target = normalize_filename_lookup(path.name)
    matches: List[Path] = []
    try:
        for candidate in parent.iterdir():
            if normalize_filename_lookup(candidate.name) == target:
                matches.append(candidate)
    except OSError:
        return path

    if len(matches) == 1:
        return matches[0]

    return path


def parse_capture_time(file_path: Path) -> datetime:
    stem = file_path.stem
    for pat in TIMESTAMP_PATTERNS:
        match = pat.search(stem)
        if not match:
            continue
        groups = match.groupdict()
        ymd = groups.get("ymd")
        t = groups.get("time", "00:00:00")
        ampm = groups.get("ampm")

        time_norm = t.replace(".", ":")
        fmt_variants = ["%Y-%m-%d %H:%M:%S"]
        if ampm:
            fmt_variants.append("%Y-%m-%d %I:%M:%S %p")
            value = f"{ymd} {time_norm} {ampm.upper()}"
        else:
            value = f"{ymd} {time_norm}"

        for fmt in fmt_variants:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue

    ts = datetime.fromtimestamp(file_path.stat().st_mtime)
    return ts


def media_type_for_ext(ext: str) -> str:
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return "document"


def clean_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def extract_keywords(text: str, *, top_n: int = 8) -> List[str]:
    tokens = clean_token(text).split()
    filtered = [t for t in tokens if len(t) > 3 and t not in STOP_WORDS]
    if not filtered:
        return []
    counts = Counter(filtered)
    return [tok for tok, _ in counts.most_common(top_n)]


def make_capture_title(ocr_text: str, file_path: Path, captured_at: datetime) -> str:
    if ocr_text:
        first_non_empty = None
        for line in ocr_text.splitlines():
            candidate = line.strip()
            if candidate:
                first_non_empty = candidate
                break
        if first_non_empty:
            title = " ".join(first_non_empty.split())
            title = title[:96]
            if title:
                return title

    stem = re.sub(r"[\W_]+", " ", file_path.stem).strip()
    if stem:
        return stem[:96]

    return f"Capture {captured_at:%Y-%m-%d %H:%M:%S}"


def run_post_hook(
    command: str,
    *,
    payload: Dict[str, Any],
    timeout: int = 60,
    max_attempts: int = 0,
    retry_delay: float = 1.0,
    use_shell: bool = False,
) -> Tuple[bool, Dict[str, Any]]:
    max_attempts = max(0, max_attempts)
    retry_delay = max(0.0, retry_delay)

    for attempt in range(1, max_attempts + 2):
        start = time.time()
        try:
            if use_shell:
                result = subprocess.run(
                    command,
                    input=json.dumps(payload),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=timeout,
                    shell=True,
                )
            else:
                cmd = shlex.split(command)
                if not cmd:
                    return (
                        False,
                        {
                            "status": "failed",
                            "attempt": attempt,
                            "return_code": -1,
                            "duration_ms": 0,
                            "stdout": "",
                            "stderr": "empty command",
                        },
                    )
                result = subprocess.run(
                    cmd,
                    input=json.dumps(payload),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=timeout,
                )
            duration_ms = int((time.time() - start) * 1000)
            hook_detail: Dict[str, Any] = {
                "status": "ok" if result.returncode == 0 else "failed",
                "attempt": attempt,
                "return_code": result.returncode,
                "duration_ms": duration_ms,
                "stdout": truncate_text(result.stdout),
                "stderr": truncate_text(result.stderr),
            }
            if result.returncode == 0:
                logging.debug("Post-hook stdout (%s): %s", command, hook_detail["stdout"])
                return True, hook_detail
            logging.warning("Post-hook failed (%s): %s", command, hook_detail["stderr"])
        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start) * 1000)
            hook_detail = {
                "status": "failed",
                "attempt": attempt,
                "return_code": -1,
                "duration_ms": duration_ms,
                "stdout": "",
                "stderr": f"timeout after {timeout}s",
            }
            logging.warning("Post-hook timeout (%s): %s", command, hook_detail["stderr"])
        except Exception as exc:
            duration_ms = int((time.time() - start) * 1000)
            hook_detail = {
                "status": "failed",
                "attempt": attempt,
                "return_code": -1,
                "duration_ms": duration_ms,
                "stdout": "",
                "stderr": str(exc),
            }
            logging.warning("Post-hook exception (%s): %s", command, exc)

        if attempt <= max_attempts:
            if retry_delay:
                logging.debug("Retrying post-hook (%s) after %.1fs", command, retry_delay)
                time.sleep(retry_delay)
            continue
        return False, hook_detail

    return False, {
        "status": "failed",
        "attempt": max_attempts + 1,
        "return_code": -1,
        "duration_ms": 0,
        "stdout": "",
        "stderr": "unreachable",
    }


def execute_post_hooks(
    post_hooks: List[str],
    *,
    base_payload: Dict[str, Any],
    manifest: Dict[str, Any],
    run_stats: Dict[str, int],
    timeout: int,
    stop_on_failure: bool,
    max_attempts: int,
    retry_delay: float,
    use_shell: bool,
) -> List[Dict[str, Any]]:
    if not post_hooks:
        return []

    results: List[Dict[str, Any]] = []
    for hook_index, hook_command in enumerate(post_hooks):
        if not hook_command:
            continue

        hook_payload = dict(base_payload)
        hook_payload["post_hook"] = {
            "index": hook_index,
            "command": hook_command,
            "run_id": base_payload.get("run_id"),
        }
        hook_success, hook_detail = run_post_hook(
            hook_command,
            payload=hook_payload,
            timeout=max(1, timeout),
            max_attempts=max_attempts,
            retry_delay=retry_delay,
            use_shell=use_shell,
        )
        bump_stat(manifest, "post_hook_attempts")
        run_stats["post_hook_attempts"] = run_stats.get("post_hook_attempts", 0) + 1

        if hook_success:
            bump_stat(manifest, "post_hook_success")
            run_stats["post_hook_success"] = run_stats.get("post_hook_success", 0) + 1
        else:
            bump_stat(manifest, "post_hook_failures")
            run_stats["post_hook_failures"] = run_stats.get("post_hook_failures", 0) + 1

        result_row: Dict[str, Any] = {
            "index": hook_index,
            "command": hook_command,
            "timestamp": now_utc_iso(),
        }
        result_row.update(hook_detail)
        results.append(result_row)
        if not hook_success and stop_on_failure:
            raise RuntimeError(f"post-hook failed: {hook_command}")

    return results


def parse_query_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return datetime.strptime(text, "%Y-%m-%d")
    try:
        parsed = datetime.fromisoformat(text.rstrip("Z"))
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def image_metadata(path: Path) -> Dict[str, Any]:
    if not command_exists("sips"):
        return {}

    result = run_cmd(["sips", "-g", "pixelWidth", "-g", "pixelHeight", "-g", "format", str(path)])
    if result.returncode != 0:
        return {}

    out = result.stdout
    meta: Dict[str, Any] = {}
    for line in out.splitlines():
        parts = line.strip().split(":", 1)
        if len(parts) != 2:
            continue
        key = parts[0].strip().lower().replace(" ", "_")
        value = parts[1].strip()
        if key in {"pixelwidth", "pixelheight"}:
            try:
                meta[key] = int(value)
            except ValueError:
                continue
        elif key == "format":
            meta[key] = value
    return meta


def document_metadata(path: Path) -> Dict[str, Any]:
    if not command_exists("pdfinfo"):
        return {}
    result = run_cmd(["pdfinfo", str(path)])
    if result.returncode != 0:
        return {}

    meta: Dict[str, Any] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower().replace(" ", "_")
        value = value.strip()
        if not value:
            continue

        if key == "pages":
            try:
                meta[key] = int(value.split()[0])
            except (ValueError, IndexError):
                meta[key] = value
        elif key in {"file_size", "page_count"}:
            meta[key] = value
        elif key == "page_size":
            match = re.search(r"([0-9.]+) x ([0-9.]+)", value)
            if match:
                try:
                    meta["page_width"] = float(match.group(1))
                    meta["page_height"] = float(match.group(2))
                except ValueError:
                    pass
            meta[key] = value
        else:
            meta[key] = value
    return meta


def video_metadata(path: Path) -> Dict[str, Any]:
    if not command_exists("ffprobe"):
        return {}

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,duration",
        "-of",
        "json",
        str(path),
    ]

    result = run_cmd(cmd, timeout=45)
    if result.returncode != 0:
        return {}

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {}

    streams = payload.get("streams") or []
    if not streams:
        return {}

    stream = streams[0]
    meta: Dict[str, Any] = {}
    for key in ("width", "height"):
        if key in stream:
            try:
                meta[key] = int(stream[key])
            except (TypeError, ValueError):
                pass
    if "duration" in stream:
        try:
            meta["duration"] = float(stream["duration"])
        except (TypeError, ValueError):
            pass
    return meta


def extract_ocr(path: Path, lang: str = "eng") -> str:
    if not command_exists("tesseract"):
        return ""

    result = run_cmd(["tesseract", str(path), "stdout", "--dpi", "300", "-l", lang], timeout=90)
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def extract_pdf_text(path: Path) -> str:
    if not command_exists("pdftotext"):
        return ""
    result = run_cmd(["pdftotext", "-layout", str(path), "-"], timeout=90)
    if result.returncode != 0:
        return ""
    text = (result.stdout or "").strip()
    return text[:25000]


def make_thumbnail_image(path: Path, output_dir: Path, *, max_size: int = 1024) -> Optional[Path]:
    if not command_exists("sips"):
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{path.stem}.jpg"
    result = run_cmd(["sips", "-Z", str(max_size), "--setProperty", "format", "jpeg", str(path), "--out", str(target)], timeout=30)
    if result.returncode != 0:
        return None
    return target


def should_skip_source_file(path: Path, source_index: Dict[str, Any]) -> bool:
    entry = source_index.get(str(path))
    if not isinstance(entry, dict):
        return False
    if entry.get("status") not in {"processed", "duplicate"}:
        return False

    try:
        stat = path.stat()
    except OSError:
        return False

    if entry.get("size_bytes") != stat.st_size:
        return False
    if entry.get("mtime_ns") != stat.st_mtime_ns:
        return False
    return True


def make_thumbnail_video(
    path: Path,
    output_dir: Path,
    *,
    seek: str = "00:00:01",
    size: int = 640,
) -> Optional[Path]:
    if not command_exists("ffmpeg"):
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{path.stem}.jpg"
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        seek,
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-vf",
        f"scale={size}:-1",
        "-q:v",
        "2",
        str(target),
    ]
    result = run_cmd(cmd, timeout=45)
    if result.returncode != 0:
        return None
    return target


def load_manifest(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": 2,
            "created_at": now_utc_iso(),
            "processed": {},
            "duplicates": {},
            "stats": {
                "runs": 0,
                "files_seen_total": 0,
                "images": 0,
                "videos": 0,
                "duplicates": 0,
                "errors": 0,
            },
        }

    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def write_manifest(
    path: Path,
    manifest: Dict[str, Any],
    manifest_backup_count: int = 0,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if manifest_backup_count > 0 and path.exists():
        backup_root = path.parent / ".manifest-backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        backup_name = f"{path.stem}.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        backup_path = backup_root / backup_name
        try:
            path.replace(backup_path)
        except OSError:
            logging.debug("Unable to move manifest backup %s -> %s", path, backup_path, exc_info=True)

        backups = sorted(backup_root.glob(f"{path.stem}.*.json"))
        if len(backups) > manifest_backup_count:
            for old in backups[: len(backups) - manifest_backup_count]:
                try:
                    old.unlink()
                except OSError:
                    logging.debug("Unable to remove old manifest backup %s", old, exc_info=True)

    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fp:
        json.dump(manifest, fp, indent=2, sort_keys=True)
    tmp.replace(path)


def discover_media_files(
    root: Path,
    *,
    out_root: Path,
    include_patterns: Iterable[str],
    exclude_patterns: Iterable[str],
    allowed_media_types: Set[str],
    min_size_bytes: int,
    max_size_bytes: int,
    follow_symlinks: bool,
) -> Iterable[Path]:
    source_root = root.resolve()
    output_root = out_root.resolve()
    include_patterns = list(include_patterns)
    exclude_patterns = list(exclude_patterns)

    for dirpath, dirnames, filenames in os.walk(source_root):
        dirpath_obj = Path(dirpath).resolve()
        dirnames[:] = [
            d for d in dirnames if not is_within_dir((dirpath_obj / d).resolve(), output_root)
        ]
        if is_within_dir(dirpath_obj, output_root):
            continue
        for filename in filenames:
            if filename.startswith("."):
                continue
            ext = Path(filename).suffix.lower()
            if ext in ALL_EXTS:
                media_type = media_type_for_ext(ext)
                if "all" not in allowed_media_types and media_type not in allowed_media_types:
                    continue
                file_path = Path(dirpath) / filename
                if file_path.is_symlink() and not follow_symlinks:
                    continue
                try:
                    size_bytes = file_path.stat().st_size
                except OSError:
                    continue
                if min_size_bytes > 0 and size_bytes < min_size_bytes:
                    continue
                if max_size_bytes > 0 and size_bytes > max_size_bytes:
                    continue
                rel = file_path.relative_to(source_root).as_posix()
                if include_patterns and not any(fnmatch.fnmatch(rel, pattern) for pattern in include_patterns):
                    continue
                if any(fnmatch.fnmatch(rel, pattern) for pattern in exclude_patterns):
                    continue
                yield file_path


def build_hash_index(manifest: Dict[str, Any]) -> Dict[str, str]:
    hash_index: Dict[str, str] = {}

    explicit_index = manifest.get("hash_index", {})
    if isinstance(explicit_index, dict):
        for digest, canonical in explicit_index.items():
            if isinstance(digest, str) and isinstance(canonical, str):
                hash_index[digest] = canonical

    processed = manifest.get("processed", {})
    if isinstance(processed, dict):
        for source_path, meta in processed.items():
            if not isinstance(source_path, str) or not isinstance(meta, (str, dict)):
                continue

            canonical = None
            file_hash = None

            if isinstance(meta, dict):
                canonical = meta.get("canonical_path")
                if isinstance(canonical, str):
                    file_hash = meta.get("sha256") if isinstance(meta.get("sha256"), str) else None

            elif isinstance(meta, str):
                canonical = meta

            if not canonical or not isinstance(canonical, str):
                continue

            if isinstance(file_hash, str) and len(file_hash) == 64:
                hash_index[file_hash] = canonical
                continue

            canonical_path = Path(canonical)
            if not canonical_path.exists():
                continue

            try:
                digest = sha256_for_file(canonical_path)
            except Exception:
                continue
            hash_index[digest] = canonical

    return hash_index


def bump_stat(manifest: Dict[str, Any], key: str, delta: int = 1) -> None:
    stats = manifest.setdefault("stats", {})
    stats[key] = stats.get(key, 0) + delta


@dataclass
class CaptureRecord:
    id: str
    source_path: str
    canonical_path: str
    media_type: str
    sha256: str
    size_bytes: int
    captured_at: str
    title: str
    dimensions: Dict[str, Any]
    duration: Optional[float]
    ocr_text: Optional[str]
    tags: List[str]
    notes: str
    status: str
    created_at: str
    thumbnail: Optional[str]


def process_file(
    path: Path,
    out_root: Path,
    *,
    do_ocr: bool,
    ocr_lang: str,
    make_thumbnail: bool,
    thumbnail_size: int,
    video_seek: str,
    do_copy: bool,
    manifest: Dict[str, Any],
    processed_hashes: Dict[str, str],
    post_hooks: List[str],
    post_hook_on: str,
    post_hook_timeout: int,
    post_hook_stop_on_failure: bool,
    post_hook_max_attempts: int,
    post_hook_retry_delay: float,
    post_hook_shell: bool,
    run_id: str,
    run_stats: Dict[str, int],
) -> Optional[CaptureRecord]:
    path = resolve_media_path(path)
    ext = path.suffix.lower()
    media_type = media_type_for_ext(ext)
    file_hash = sha256_for_file(path)
    existing = processed_hashes.get(file_hash)
    size_bytes = path.stat().st_size
    source_state = manifest.setdefault("source_index", {})

    captured_at = parse_capture_time(path)
    capture_date_dir = captured_at.strftime("%Y/%m")
    file_stem = captured_at.strftime("%Y%m%d_%H%M%S")

    canonical_dir = out_root / media_type / capture_date_dir
    canonical_dir.mkdir(parents=True, exist_ok=True)
    canonical_name = f"{file_stem}_{file_hash[:10]}{ext}"
    canonical_path = canonical_dir / canonical_name

    dimensions: Dict[str, Any] = {}
    duration = None
    if media_type == "image":
        dimensions = image_metadata(path)
    else:
        dimensions = video_metadata(path)
        if "duration" in dimensions:
            duration = dimensions.pop("duration")

    record_status = "processed"
    thumbnail = None
    notes = ""
    ocr = ""
    tags: List[str] = []

    if existing is not None:
        source_entry = {
            "size_bytes": size_bytes,
            "mtime_ns": path.stat().st_mtime_ns,
            "status": "duplicate",
            "sha256": file_hash,
            "canonical_path": existing,
            "seen_at": now_utc_iso(),
            "captured_at": captured_at.isoformat(),
        }
        source_state[str(path)] = source_entry
        manifest.setdefault("duplicates", {})[str(path)] = {
            "canonical_path": existing,
            "source_path": str(path),
            "sha256": file_hash,
            "size_bytes": size_bytes,
            "status": "duplicate",
            "seen_at": now_utc_iso(),
            "captured_at": captured_at.isoformat(),
        }
        record_status = "duplicate"
        bump_stat(manifest, "duplicates")
        notes = f"duplicate_of:{existing}"
        sidecar = {
            "id": file_hash[:12],
            "source_path": str(path),
            "status": "duplicate",
            "canonical_path": existing,
            "sha256": file_hash,
            "size_bytes": size_bytes,
            "captured_at": captured_at.isoformat(),
            "notes": notes,
            "run_id": run_id,
            "source_state": source_entry,
        }
        if post_hooks and post_hook_on in {"duplicates", "all"}:
            hook_results = execute_post_hooks(
                post_hooks,
                base_payload=sidecar,
                manifest=manifest,
                run_stats=run_stats,
                timeout=post_hook_timeout,
                stop_on_failure=post_hook_stop_on_failure,
                max_attempts=post_hook_max_attempts,
                retry_delay=post_hook_retry_delay,
                use_shell=post_hook_shell,
            )
            if hook_results:
                sidecar["post_hook_results"] = hook_results

        sidecar_path = out_root / f"{file_stem}_{file_hash[:10]}{ext}.json"
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

        return CaptureRecord(
            id=file_hash[:12],
            source_path=str(path),
            canonical_path=existing,
            media_type=media_type,
            sha256=file_hash,
            size_bytes=size_bytes,
            captured_at=captured_at.isoformat(),
            title="duplicate",
            dimensions={},
            duration=None,
            ocr_text=None,
            tags=[],
            notes=notes,
            status=record_status,
            created_at=now_utc_iso(),
            thumbnail=None,
        )

    else:
        if do_copy:
            shutil.copy2(path, canonical_path)
        else:
            shutil.move(path, canonical_path)

        if media_type == "image":
            if do_ocr:
                ocr = extract_ocr(canonical_path, ocr_lang)
            else:
                ocr = ""
            if make_thumbnail:
                thumb = make_thumbnail_image(
                    canonical_path,
                    out_root / "_thumbnails" / media_type / capture_date_dir,
                    max_size=thumbnail_size,
                )
                if thumb:
                    thumbnail = str(thumb.relative_to(out_root))
            dimensions = image_metadata(canonical_path)
        elif media_type == "document":
            if do_ocr:
                ocr = extract_ocr(canonical_path, ocr_lang)
                if not ocr:
                    ocr = extract_pdf_text(canonical_path)
            else:
                ocr = ""
            if make_thumbnail:
                thumb = make_thumbnail_image(
                    canonical_path,
                    out_root / "_thumbnails" / media_type / capture_date_dir,
                    max_size=thumbnail_size,
                )
                if thumb:
                    thumbnail = str(thumb.relative_to(out_root))
            dimensions = document_metadata(canonical_path)
        else:
            ocr = ""
            if make_thumbnail:
                thumb = make_thumbnail_video(
                    canonical_path,
                    out_root / "_thumbnails" / media_type / capture_date_dir,
                    seek=video_seek,
                    size=thumbnail_size,
                )
                if thumb:
                    thumbnail = str(thumb.relative_to(out_root))
            dimensions = video_metadata(canonical_path)
            if "duration" in dimensions:
                duration = dimensions.pop("duration")

        tags = extract_keywords(ocr)
        title = make_capture_title(ocr, path, captured_at)
        sidecar = {
            "schema_version": 2,
            "id": f"{file_hash[:12]}",
            "source_path": str(path),
            "canonical_path": str(canonical_path),
            "canonical_name": canonical_name,
            "media_type": media_type,
            "sha256": file_hash,
            "size_bytes": size_bytes,
            "captured_at": captured_at.isoformat(),
            "dimensions": dimensions,
            "duration_seconds": duration,
            "ocr": ocr,
            "tags": tags,
            "title": title,
            "thumbnail": thumbnail,
            "run_id": run_id,
            "source_state": {
                "size_bytes": size_bytes,
                "mtime_ns": path.stat().st_mtime_ns,
                "status": "processed",
                "sha256": file_hash,
                "canonical_path": str(canonical_path),
                "captured_at": captured_at.isoformat(),
            },
        }
        sidecar_path = out_root / f"{canonical_name}.json"
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
        manifest.setdefault("hash_index", {})[file_hash] = str(canonical_path)
        processed_hashes[file_hash] = str(canonical_path)
        manifest["processed"][str(path)] = {
            "canonical_path": str(canonical_path),
            "sha256": file_hash,
            "size_bytes": size_bytes,
            "status": "processed",
            "processed_at": now_utc_iso(),
        }
        source_state[str(path)] = {
            "size_bytes": size_bytes,
            "mtime_ns": path.stat().st_mtime_ns,
            "status": "processed",
            "sha256": file_hash,
            "canonical_path": str(canonical_path),
            "processed_at": now_utc_iso(),
        }
        if post_hooks and post_hook_on in {"processed", "all"}:
            hook_results = execute_post_hooks(
                post_hooks,
                base_payload=sidecar,
                manifest=manifest,
                run_stats=run_stats,
                timeout=post_hook_timeout,
                stop_on_failure=post_hook_stop_on_failure,
                max_attempts=post_hook_max_attempts,
                retry_delay=post_hook_retry_delay,
                use_shell=post_hook_shell,
            )
            if hook_results:
                sidecar["post_hook_results"] = hook_results

        if media_type == "image":
            bump_stat(manifest, "images")
        elif media_type == "video":
            bump_stat(manifest, "videos")
        else:
            bump_stat(manifest, "documents")
        return CaptureRecord(
            id=file_hash[:12],
            source_path=str(path),
            canonical_path=str(canonical_path),
            media_type=media_type,
            sha256=file_hash,
            size_bytes=size_bytes,
            captured_at=captured_at.isoformat(),
            title=title,
            dimensions=dimensions,
            duration=duration,
            ocr_text=ocr,
            tags=tags,
            notes=notes,
            status=record_status,
            created_at=now_utc_iso(),
            thumbnail=thumbnail,
        )


def keep_record_by_age(record: Dict[str, Any], cutoff: datetime) -> bool:
    created_at = parse_query_datetime(record.get("created_at", ""))
    if created_at is None:
        created_at = parse_query_datetime(record.get("processed_at", ""))
    if created_at is None:
        return True
    return created_at >= cutoff


def build_index(
    records: List[CaptureRecord],
    out_root: Path,
    *,
    retention_days: int = 0,
) -> Tuple[int, int]:
    merged: Dict[str, Dict[str, Any]] = {}
    for row in load_index_records(out_root):
        key = row.get("canonical_path") or row.get("source_path") or row.get("id")
        if key:
            merged[str(key)] = row

    for row in [asdict(r) for r in records if r is not None]:
        key = row.get("canonical_path") or row.get("source_path") or row.get("id")
        if key:
            merged[str(key)] = row

    rows = list(merged.values())
    if retention_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        before = len(rows)
        rows = [row for row in rows if keep_record_by_age(row, cutoff)]
        pruned = before - len(rows)
    else:
        pruned = 0

    rows_sorted = sorted(rows, key=lambda row: row.get("captured_at", ""), reverse=True)
    count = write_index_rows(out_root, rows_sorted)
    summary = {
        "generated_at": now_utc_iso(),
        "count": count,
        "images": sum(1 for r in rows if r["media_type"] == "image"),
        "videos": sum(1 for r in rows if r["media_type"] == "video"),
        "documents": sum(1 for r in rows if r["media_type"] == "document"),
        "duplicates": sum(1 for r in rows if r["status"] == "duplicate"),
    }
    (out_root / "index-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return count, pruned


def write_index_rows(
    out_root: Path,
    rows: List[Dict[str, Any]],
) -> int:
    rows = list(rows)
    rows.sort(key=lambda row: row.get("captured_at", ""), reverse=True)
    index_path = out_root / "index.jsonl"
    with index_path.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row))
            fp.write("\n")

    summary = {
        "generated_at": now_utc_iso(),
        "count": len(rows),
        "images": sum(1 for r in rows if r["media_type"] == "image"),
        "videos": sum(1 for r in rows if r["media_type"] == "video"),
        "documents": sum(1 for r in rows if r["media_type"] == "document"),
        "duplicates": sum(1 for r in rows if r["status"] == "duplicate"),
    }
    (out_root / "index-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return len(rows)


def run_repair_state(
    out_root: Path,
    manifest: Dict[str, Any],
    *,
    prune_orphans: bool = False,
) -> Dict[str, int]:
    records = load_index_records(out_root)
    kept_records: List[Dict[str, Any]] = []
    pruned_index = 0
    for row in records:
        canonical_path = row.get("canonical_path")
        if not isinstance(canonical_path, str):
            pruned_index += 1
            continue
        if not Path(canonical_path).exists():
            pruned_index += 1
            continue
        kept_records.append(row)

    kept_canonical = {
        Path(row["canonical_path"]).resolve().as_posix()
        for row in kept_records
        if isinstance(row.get("canonical_path"), str)
    }

    processed = manifest.get("processed")
    if not isinstance(processed, dict):
        processed = {}
    kept_processed: Dict[str, Dict[str, Any]] = {}
    pruned_processed = 0
    for source_path, meta in processed.items():
        if not isinstance(meta, dict):
            pruned_processed += 1
            continue
        canonical_path = meta.get("canonical_path")
        if not isinstance(canonical_path, str) or canonical_path not in kept_canonical:
            pruned_processed += 1
            continue
        kept_processed[source_path] = meta
    manifest["processed"] = kept_processed

    duplicates = manifest.get("duplicates")
    if not isinstance(duplicates, dict):
        duplicates = {}
    kept_duplicates: Dict[str, Dict[str, Any]] = {}
    pruned_duplicates = 0
    for source_path, meta in duplicates.items():
        if not isinstance(meta, dict):
            pruned_duplicates += 1
            continue
        canonical_path = meta.get("canonical_path")
        if not isinstance(canonical_path, str):
            pruned_duplicates += 1
            continue
        if canonical_path not in kept_canonical:
            pruned_duplicates += 1
            continue
        kept_duplicates[source_path] = meta
    manifest["duplicates"] = kept_duplicates

    source_index = manifest.get("source_index")
    if not isinstance(source_index, dict):
        source_index = {}
    kept_source_index: Dict[str, Dict[str, Any]] = {}
    pruned_source_index = 0
    for source_path, meta in source_index.items():
        if not isinstance(meta, dict):
            pruned_source_index += 1
            continue
        if not Path(source_path).exists() and meta.get("status") == "duplicate":
            # duplicates without surviving canonical are rarely useful for incremental skip and can be replayed safely.
            pruned_source_index += 1
            continue
        if meta.get("canonical_path") not in kept_canonical:
            pruned_source_index += 1
            continue
        kept_source_index[source_path] = meta
    manifest["source_index"] = kept_source_index

    hash_index = manifest.get("hash_index")
    if not isinstance(hash_index, dict):
        hash_index = {}
    kept_hash_index: Dict[str, str] = {}
    pruned_hash = 0
    for digest, canonical_path in hash_index.items():
        if not isinstance(canonical_path, str):
            pruned_hash += 1
            continue
        if Path(canonical_path).exists():
            kept_hash_index[digest] = canonical_path
        else:
            pruned_hash += 1
    manifest["hash_index"] = kept_hash_index
    manifest["repaired_at"] = now_utc_iso()

    prune_summary_orphans = prune_orphan_outputs(
        out_root,
        kept_canonical,
        dry_run=False,
        remove_thumbnails=True,
    ) if prune_orphans else {"sidecars": 0, "thumbnails": 0, "empty_dirs": 0}

    index_rows = write_index_rows(out_root, kept_records)
    return {
        "pruned_index_rows": pruned_index,
        "pruned_processed": pruned_processed,
        "pruned_duplicates": pruned_duplicates,
        "pruned_source_index": pruned_source_index,
        "pruned_hash_index": pruned_hash,
        "pruned_orphan_sidecars": prune_summary_orphans["sidecars"],
        "pruned_orphan_thumbnails": prune_summary_orphans["thumbnails"],
        "pruned_orphan_empty_dirs": prune_summary_orphans["empty_dirs"],
        "index_rows": index_rows,
    }


def prune_manifest_state(
    manifest: Dict[str, Any],
    out_root: Path,
    *,
    retention_days: int,
) -> Dict[str, int]:
    if retention_days <= 0:
        return {
            "pruned_processed": 0,
            "pruned_duplicates": 0,
            "pruned_hash_index": 0,
        }

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    processed = manifest.get("processed")
    if not isinstance(processed, dict):
        processed = {}
    kept_processed: Dict[str, Dict[str, Any]] = {}
    pruned_processed = 0
    for source_path, meta in list(processed.items()):
        if not isinstance(meta, dict):
            kept_processed[source_path] = {"source_path": source_path}
            continue
        processed_at = parse_query_datetime(meta.get("processed_at", ""))
        if processed_at is not None and processed_at < cutoff:
            pruned_processed += 1
            continue
        kept_processed[source_path] = meta
    manifest["processed"] = kept_processed

    duplicates = manifest.get("duplicates")
    if not isinstance(duplicates, dict):
        duplicates = {}
    kept_duplicates: Dict[str, Dict[str, Any]] = {}
    pruned_duplicates = 0
    for source_path, meta in list(duplicates.items()):
        if not isinstance(meta, dict):
            kept_duplicates[source_path] = {"source_path": source_path}
            continue
        seen_at = parse_query_datetime(meta.get("seen_at", ""))
        if seen_at is not None and seen_at < cutoff:
            pruned_duplicates += 1
            continue
        kept_duplicates[source_path] = meta
    manifest["duplicates"] = kept_duplicates

    kept_canonical: Set[str] = set()
    for meta in kept_processed.values():
        canonical_path = meta.get("canonical_path")
        if isinstance(canonical_path, str):
            kept_canonical.add(Path(canonical_path).resolve().as_posix())
    for meta in kept_duplicates.values():
        canonical_path = meta.get("canonical_path")
        if isinstance(canonical_path, str):
            kept_canonical.add(Path(canonical_path).resolve().as_posix())

    hash_index = manifest.get("hash_index")
    if not isinstance(hash_index, dict):
        hash_index = {}
    kept_hash_index: Dict[str, str] = {}
    pruned_hash_index = 0
    for digest, canonical_path in list(hash_index.items()):
        if not isinstance(digest, str) or not isinstance(canonical_path, str):
            continue
        if Path(canonical_path).resolve().as_posix() in kept_canonical:
            kept_hash_index[digest] = canonical_path
        else:
            pruned_hash_index += 1

    manifest["hash_index"] = kept_hash_index
    manifest["state_retention_days"] = retention_days
    manifest["state_retention_checked_at"] = now_utc_iso()

    return {
        "pruned_processed": pruned_processed,
        "pruned_duplicates": pruned_duplicates,
        "pruned_hash_index": pruned_hash_index,
    }


def load_index_records(out_root: Path) -> List[Dict[str, Any]]:
    index_path = out_root / "index.jsonl"
    if not index_path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with index_path.open("r", encoding="utf-8") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logging.warning("Skipping invalid index row: %s", exc)
    return rows


def cleanup_stale_raw_files(
    source_root: Path,
    *,
    manifest: Dict[str, Any],
    dry_run: bool,
    max_age_days: int,
) -> int:
    if max_age_days <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    processed = manifest.get("processed", {})
    if not isinstance(processed, dict):
        return 0

    removed = 0
    for source_path, meta in list(processed.items()):
        if not isinstance(meta, dict):
            continue
        if meta.get("status") != "processed":
            continue
        processed_at = parse_query_datetime(meta.get("processed_at"))
        if not processed_at:
            continue
        if processed_at > cutoff:
            continue

        path_obj = resolve_media_path(Path(source_path))
        try:
            path_obj.relative_to(source_root)
        except ValueError:
            continue
        if not path_obj.exists():
            continue

        if dry_run:
            logging.info("Would remove stale raw source: %s", path_obj)
            removed += 1
            continue

        try:
            path_obj.unlink()
            removed += 1
        except OSError as exc:
            logging.warning("Failed to remove stale raw source %s: %s", path_obj, exc)

    return removed


def record_matches_query(
    record: Dict[str, Any],
    *,
    query: Optional[str],
    media: str,
    status: str,
    since: Optional[datetime],
    until: Optional[datetime],
) -> bool:
    if media != "all" and record.get("media_type") != media:
        return False
    if status != "all" and record.get("status") != status:
        return False

    captured_at = parse_query_datetime(record.get("captured_at", "")) if record.get("captured_at") else None
    if since and captured_at and captured_at < since:
        return False
    if until and captured_at and captured_at > until:
        return False

    if query:
        ocr_text = str(record.get("ocr_text", "")) or str(record.get("ocr", ""))
        haystack = " ".join(
            [
                str(record.get("captured_at", "")),
                str(record.get("source_path", "")),
                str(record.get("canonical_path", "")),
                str(record.get("title", "")),
                ocr_text,
                " ".join(record.get("tags", []) or []),
            ]
        ).lower()
        if query.lower() not in haystack:
            return False

    return True


def run_query(out_root: Path, args: argparse.Namespace) -> int:
    records = load_index_records(out_root)
    if not records:
        logging.info("No index found at %s. Run process mode first.", out_root / "index.jsonl")
        if args.json_report or args.report:
            emit_report(
                {
                    "mode": "query",
                    "out": str(out_root),
                    "query": args.query,
                    "query_media": args.query_media,
                    "query_status": args.query_status,
                    "query_limit": args.query_limit,
                    "query_format": args.query_format,
                    "count": 0,
                    "matches": [],
                },
                json_report=args.json_report,
                report_path=args.report,
                report_format=args.json_report_format,
            )
        return 0

    since = parse_query_datetime(args.since)
    until = parse_query_datetime(args.until)

    matched = [
        r
        for r in records
        if record_matches_query(
            r,
            query=args.query,
            media=args.query_media,
            status=args.query_status,
            since=since,
            until=until,
        )
    ]

    matched.sort(key=lambda row: row.get("captured_at", ""), reverse=True)
    if args.query_limit > 0:
        matched = matched[: args.query_limit]

    if args.json_report or args.report:
        emit_report(
            {
                "mode": "query",
                "out": str(out_root),
                "query": args.query,
                "query_media": args.query_media,
                "query_status": args.query_status,
                "query_limit": args.query_limit,
                "query_format": args.query_format,
                "count": len(matched),
                "matches": matched,
                "matches_paths": [row.get("canonical_path", "") for row in matched],
            },
            json_report=args.json_report,
            report_path=args.report,
            report_format=args.json_report_format,
        )

    if args.json_report or args.report:
        # Structured output modes skip human row output.
        logging.info("Query matched %s records", len(matched))
        return len(matched)

    if args.query_format == "paths":
        for row in matched:
            print(row.get("canonical_path", ""))
    elif args.query_format == "csv":
        fieldnames = [
            "id",
            "captured_at",
            "status",
            "media_type",
            "title",
            "source_path",
            "canonical_path",
            "sha256",
            "size_bytes",
            "tags",
            "thumbnail",
        ]
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        writer.writeheader()
        for row in matched:
            normalized = {field: row.get(field, "") for field in fieldnames}
            if isinstance(normalized["tags"], list):
                normalized["tags"] = " ".join(normalized["tags"])
            writer.writerow(normalized)
    elif args.query_format == "jsonl":
        for row in matched:
            print(json.dumps(row, ensure_ascii=False))
    else:
        print(json.dumps({"count": len(matched), "matches": matched}, ensure_ascii=False))

    logging.info("Query matched %s records", len(matched))
    return len(matched)


def run_health_check(
    out_root: Path,
    manifest: Dict[str, Any],
) -> Dict[str, Any]:
    index_records = load_index_records(out_root)
    processed = manifest.get("processed", {})
    duplicates = manifest.get("duplicates", {})
    source_index = manifest.get("source_index", {})
    hash_index = manifest.get("hash_index", {})

    index_count = 0
    index_orphaned = 0
    index_missing_canonical = []
    for record in index_records:
        canonical_path = record.get("canonical_path")
        if not isinstance(canonical_path, str):
            index_orphaned += 1
            continue
        if Path(canonical_path).exists():
            index_count += 1
        else:
            index_orphaned += 1
            index_missing_canonical.append(canonical_path)

    processed_missing = 0
    if isinstance(processed, dict):
        for source_path, meta in processed.items():
            if not isinstance(meta, dict):
                continue
            canonical_path = meta.get("canonical_path")
            if not isinstance(canonical_path, str) or not Path(canonical_path).exists():
                processed_missing += 1

    duplicates_missing = 0
    if isinstance(duplicates, dict):
        for _, meta in duplicates.items():
            if not isinstance(meta, dict):
                continue
            canonical_path = meta.get("canonical_path")
            if not isinstance(canonical_path, str) or not Path(canonical_path).exists():
                duplicates_missing += 1

    source_entries = {}
    if isinstance(source_index, dict):
        source_entries = {
            source_path: meta
            for source_path, meta in source_index.items()
            if isinstance(meta, dict)
        }

    orphaned_sidecars = 0
    orphaned_thumbnails = 0
    canonical_set = {str(rec.get("canonical_path")) for rec in index_records if rec.get("canonical_path")}
    if canonical_set:
        for sidecar in out_root.glob("*.json"):
            if sidecar.name in {"manifest.json", "index-summary.json"}:
                continue
            if not sidecar.is_file():
                continue
            # Sidecar metadata lives at repository root and must map to canonical output.
            canonical_from_sidecar = ""
            try:
                sidecar_payload = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                sidecar_payload = None

            if isinstance(sidecar_payload, dict):
                path_value = sidecar_payload.get("canonical_path")
                if isinstance(path_value, str):
                    canonical_from_sidecar = path_value
            if canonical_from_sidecar and canonical_from_sidecar not in canonical_set:
                orphaned_sidecars += 1
            elif sidecar.stem not in {Path(p).stem for p in canonical_set}:
                orphaned_sidecars += 1

        for sidecar in (out_root / "_thumbnails").rglob("*.jpg"):
            if sidecar.is_file():
                canonical_stems = {Path(p).stem for p in canonical_set}
                if sidecar.stem not in canonical_stems:
                    orphaned_thumbnails += 1

    return {
        "status": "ok" if not any((index_orphaned, processed_missing, duplicates_missing, orphaned_sidecars, orphaned_thumbnails)) else "degraded",
        "index_rows": len(index_records),
        "index_orphaned": index_orphaned,
        "index_missing_canonical": index_missing_canonical[:20],
        "processed_missing": processed_missing,
        "duplicates_missing": duplicates_missing,
        "source_index_entries": len(source_entries),
        "source_index_missing": sum(
            1 for meta in source_entries.values()
            if isinstance(meta.get("canonical_path", ""), str) and not Path(meta.get("canonical_path", "")).exists()
        ),
        "orphaned_sidecars": orphaned_sidecars,
        "orphaned_thumbnails": orphaned_thumbnails,
        "hash_index_size": len(hash_index) if isinstance(hash_index, dict) else 0,
    }


def prune_orphan_outputs(
    out_root: Path,
    canonical_set: Set[str],
    *,
    dry_run: bool = False,
    remove_thumbnails: bool = True,
) -> Dict[str, int]:
    removed: Dict[str, int] = {
        "sidecars": 0,
        "thumbnails": 0,
        "empty_dirs": 0,
    }

    if not canonical_set:
        return removed

    canonical_resolved = {str(Path(path).resolve()) for path in canonical_set if isinstance(path, str)}
    canonical_stems = {Path(path).stem for path in canonical_resolved}

    for sidecar in out_root.glob("*.json"):
        if sidecar.name in {"manifest.json", "index-summary.json"}:
            continue
        if sidecar.name == "config.json":
            continue
        if sidecar.name.endswith(".backup.json"):
            continue
        if not sidecar.is_file():
            continue
        mapped = ""
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            mapped = payload.get("canonical_path", "")
        except (OSError, json.JSONDecodeError):
            pass
        if isinstance(mapped, str) and mapped.strip():
            if Path(mapped).resolve().as_posix() in canonical_resolved:
                continue
        if sidecar.stem in canonical_stems:
            continue
        removed["sidecars"] += 1
        if not dry_run:
            try:
                sidecar.unlink()
            except OSError as exc:
                logging.warning("Failed to remove orphan sidecar %s: %s", sidecar, exc)

    if remove_thumbnails:
        for thumb in (out_root / "_thumbnails").rglob("*.jpg"):
            if not thumb.is_file():
                continue
            if thumb.stem in canonical_stems:
                continue
            removed["thumbnails"] += 1
            if not dry_run:
                try:
                    thumb.unlink()
                except OSError as exc:
                    logging.warning("Failed to remove orphan thumbnail %s: %s", thumb, exc)

    if not dry_run:
        thumbnail_dir = out_root / "_thumbnails"
        if thumbnail_dir.exists():
            for directory in sorted(thumbnail_dir.rglob("*"), reverse=True):
                if directory.is_dir():
                    try:
                        if not any(directory.iterdir()):
                            directory.rmdir()
                            removed["empty_dirs"] += 1
                    except OSError:
                        pass
    return removed


def load_config_file(path: str) -> Dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise SystemExit(f"Config file not found: {config_path}")
    if not config_path.is_file():
        raise SystemExit(f"Config path is not a file: {config_path}")

    try:
        with config_path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Invalid config file {config_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise SystemExit(f"Config file must contain an object: {config_path}")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest, process, and enrich screen captures")
    parser.add_argument("--config", type=str, default="", help="Optional JSON config file")
    parser.add_argument("source", nargs="?", default="", help="Source folder containing screenshots/videos")
    parser.add_argument("--out", type=str, default=".capture-automation", help="Output root for processed assets")
    parser.add_argument("--copy", action="store_true", help="Copy instead of moving raw files")
    parser.add_argument("--no-ocr", action="store_true", help="Disable OCR")
    parser.add_argument("--no-thumbnails", action="store_true", help="Disable thumbnail generation")
    parser.add_argument("--thumbnail-size", type=int, default=1024, help="Max pixel dimension for image PDF thumbnails")
    parser.add_argument("--video-seek", type=str, default="00:00:01", help="Seek position used for video thumbnails")
    parser.add_argument("--ocr-lang", type=str, default="eng", help="Tesseract OCR language code")
    parser.add_argument("--media-types", type=str, default="all", help="Comma-separated media types to include: all,image,video,document")
    parser.add_argument("--min-size-bytes", type=int, default=0, help="Skip files smaller than this many bytes")
    parser.add_argument("--max-size-bytes", type=int, default=0, help="Skip files larger than this many bytes (0 = unlimited)")
    parser.add_argument("--follow-symlinks", action="store_true", help="Follow symlinks when scanning source tree")
    parser.add_argument("--watch", action="store_true", help="Watch source folder and process newly added files continuously")
    parser.add_argument("--interval", type=float, default=5.0, help="Watch interval in seconds")
    parser.add_argument("--watch-jitter", type=float, default=0.0, help="Randomized interval jitter as a fraction (0.0-1.0)")
    parser.add_argument("--watch-idle-threshold", type=float, default=0.0, help="Stop watch mode after this many seconds with no new work (0 = disabled)")
    parser.add_argument("--max-runs", type=int, default=0, help="Max watch iterations (0 = unlimited)")
    parser.add_argument("--cleanup-raw", action="store_true", help="Cleanup stale raw files in source folder when running with --copy")
    parser.add_argument(
        "--cleanup-raw-days",
        type=int,
        default=0,
        help="Remove copied source files older than this many days (requires --cleanup-raw and --copy)",
    )
    parser.add_argument(
        "--cleanup-state-days",
        type=int,
        default=0,
        help="Prune manifest/index state older than this many days",
    )
    parser.add_argument(
        "--post-hook",
        action="append",
        default=[],
        help="Hook command for each eligible record (repeat for pipelines). JSON payload via stdin.",
    )
    parser.add_argument(
        "--post-hook-on",
        type=str,
        choices=("processed", "duplicates", "all"),
        default="processed",
        help="Run hooks for processed records, duplicates, or both",
    )
    parser.add_argument(
        "--post-hook-timeout",
        type=int,
        default=60,
        help="Per-hook timeout in seconds",
    )
    parser.add_argument(
        "--post-hook-max-attempts",
        type=int,
        default=0,
        help="Retries per hook before failing the file",
    )
    parser.add_argument(
        "--post-hook-retry-delay",
        type=float,
        default=1.0,
        help="Delay in seconds between hook retry attempts",
    )
    parser.add_argument(
        "--post-hook-shell",
        action="store_true",
        help="Run hook commands through a shell",
    )
    parser.add_argument(
        "--post-hook-stop-on-failure",
        action="store_true",
        help="Fail the file when a post-hook fails",
    )
    parser.add_argument("--dry-run", action="store_true", help="List actions only")
    parser.add_argument("--query", type=str, default="", help="Search index.jsonl and print matches; e.g. --query 'keyword'")
    parser.add_argument("--query-media", type=str, choices=("all", "image", "video", "document"), default="all", help="Filter query by media type")
    parser.add_argument("--query-status", type=str, choices=("all", "processed", "duplicate"), default="all", help="Filter query by status")
    parser.add_argument("--query-limit", type=int, default=50, help="Max query results (0 = unlimited)")
    parser.add_argument("--query-format", type=str, choices=("json", "jsonl", "paths", "csv"), default="json", help="Query output format")
    parser.add_argument("--query-required-min", type=int, default=0, help="Fail if query returns fewer than this many records (query mode)")
    parser.add_argument("--since", type=str, default="", help="Only match captures at or after this date (YYYY-MM-DD or ISO)")
    parser.add_argument("--until", type=str, default="", help="Only match captures at or before this date (YYYY-MM-DD or ISO)")
    parser.add_argument("--include", action="append", default=[], help="Include glob pattern(s) under source tree. Repeatable")
    parser.add_argument("--exclude", action="append", default=[], help="Exclude glob pattern(s) under source tree. Repeatable")
    parser.add_argument("--max-files", type=int, default=0, help="Process at most this many files this run (0 = unlimited)")
    parser.add_argument("--json-report", action="store_true", help="Print machine-readable summary to stdout")
    parser.add_argument("--json-report-format", choices=("json", "csv", "jsonl"), default="json", help="Machine report format (default: json)")
    parser.add_argument("--repair", action="store_true", help="Rebuild manifest and index from existing processed outputs")
    parser.add_argument("--repair-orphan-assets", action="store_true", help="Prune orphaned sidecar and thumbnail files during repair")
    parser.add_argument("--verify", action="store_true", help="Run manifest/index consistency checks and exit")
    parser.add_argument(
        "--self-heal",
        action="store_true",
        help="Run verify and repair automatically when health checks fail",
    )
    parser.add_argument(
        "--self-heal-repair-orphans",
        action="store_true",
        help="Prune orphaned sidecars/thumbnails during self-heal repairs",
    )
    parser.add_argument("--report", type=str, default="", help="Write machine-readable report JSON to file")
    parser.add_argument("--event-log", type=str, default="", help="Append JSONL automation events to this file")
    parser.add_argument("--run-id", type=str, default="", help="Optional explicit run id to stamp into outputs")
    parser.add_argument("--check-source", action="store_true", help="Print source scan summary and exit")
    parser.add_argument("--fail-on-error", action="store_true", help="Exit non-zero if any processing errors occur")
    parser.add_argument("--max-errors", type=int, default=0, help="Fail when this many or more errors occur in a run")
    parser.add_argument("--require-new", type=int, default=0, help="Fail when fewer than this many new files are processed")
    parser.add_argument("--watch-heartbeat", type=str, default="", help="Write watchdog heartbeat JSON after each watch pass")
    parser.add_argument("--disable-lock", action="store_true", help="Disable run-lock protection")
    parser.add_argument("--lock-timeout", type=int, default=120, help="Seconds to wait for lock acquisition")
    parser.add_argument(
        "--lock-stale-seconds",
        type=int,
        default=7200,
        help="Overwrite stale lock after this many seconds",
    )
    parser.add_argument(
        "--manifest-backup-count",
        type=int,
        default=0,
        help="Keep this many historical manifest snapshots (0 = keep only current)",
    )
    parser.add_argument("--lock-path", type=str, default="", help="Custom lock file path")
    parser.add_argument("--verbose", action="store_true", help="Verbose logs")
    return parser


def parse_args() -> argparse.Namespace:
    # Parse config path first so we can apply it as defaults while preserving CLI overrides.
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config", type=str, default="")
    pre, _ = pre_parser.parse_known_args()

    parser = build_parser()
    if pre.config:
        config = load_config_file(pre.config)
        action_dest = {action.dest for action in parser._actions}
        for key, value in config.items():
            dest = str(key).replace("-", "_")
            if dest in action_dest and isinstance(dest, str):
                parser.set_defaults(**{dest: value})

    args = parser.parse_args()
    if not args.source:
        raise SystemExit("source argument is required (or set source in --config)")
    if isinstance(args.post_hook, str):
        args.post_hook = [args.post_hook]
    elif args.post_hook is None:
        args.post_hook = []
    return args


def normalize_post_hooks(raw: Any) -> List[str]:
    if isinstance(raw, str):
        raw = [raw]
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        return [item.strip() for item in raw if isinstance(item, str) and item.strip()]
    return []


def run_check_source(
    source_root: Path,
    out_root: Path,
    *,
    include_patterns: Iterable[str],
    exclude_patterns: Iterable[str],
    allowed_media_types: Set[str],
    min_size_bytes: int,
    max_size_bytes: int,
    follow_symlinks: bool,
) -> Dict[str, Any]:
    files = list(
        discover_media_files(
            source_root,
            out_root=out_root,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            allowed_media_types=allowed_media_types,
            min_size_bytes=min_size_bytes,
            max_size_bytes=max_size_bytes,
            follow_symlinks=follow_symlinks,
        )
    )

    counts: Dict[str, int] = {"all": len(files), "image": 0, "video": 0, "document": 0}
    for path in files:
        counts[media_type_for_ext(path.suffix.lower())] = counts.get(media_type_for_ext(path.suffix.lower()), 0) + 1

    return {
        "source_root": str(source_root),
        "discovered_files": len(files),
        "counts": counts,
        "filters": {
            "include_patterns": list(include_patterns),
            "exclude_patterns": list(exclude_patterns),
            "media_types": sorted(list(allowed_media_types)),
            "min_size_bytes": min_size_bytes,
            "max_size_bytes": max_size_bytes,
            "follow_symlinks": follow_symlinks,
        },
    }


def emit_report(
    payload: Dict[str, Any],
    *,
    json_report: bool,
    report_path: str,
    report_format: str = "json",
) -> None:
    def _jsonl_payload_rows(report_payload: Dict[str, Any]):
        if not isinstance(report_payload, dict):
            return
        meta = dict(report_payload)
        matches = meta.pop("matches", None)
        if matches is not None and isinstance(matches, list):
            if meta:
                yield meta
            for row in matches:
                if isinstance(row, dict):
                    yield row
            return
        if meta:
            yield meta

    if json_report:
        if report_format == "json":
            print(json.dumps(payload, ensure_ascii=False))
        elif report_format == "jsonl":
            if isinstance(payload, list):
                for row in payload:
                    print(json.dumps(row, ensure_ascii=False))
            elif isinstance(payload, dict):
                for row in _jsonl_payload_rows(payload):
                    print(json.dumps(row, ensure_ascii=False))
        else:
            rows = []
            if isinstance(payload, list):
                rows = payload
            elif isinstance(payload, dict):
                for key, value in payload.items():
                    rows.append({
                        "key": key,
                        "value": json.dumps(value, ensure_ascii=False) if not isinstance(value, (int, float, str, bool, type(None))) else value,
                    })

            if rows:
                output = []
                if rows:
                    fieldnames = sorted({key for row in rows for key in row.keys()})
                    import io
                    buffer = io.StringIO()
                    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                    output_text = buffer.getvalue()
                    print(output_text.rstrip("\n"))
    if report_path:
        report_file = Path(report_path)
        report_file.parent.mkdir(parents=True, exist_ok=True)
        if report_format == "json":
            report_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return
        if report_format == "jsonl":
            if isinstance(payload, list):
                text = "\n".join(json.dumps(row, ensure_ascii=False) for row in payload)
            elif isinstance(payload, dict):
                text = "\n".join(
                    json.dumps(row, ensure_ascii=False) for row in _jsonl_payload_rows(payload)
                )
            else:
                text = json.dumps(payload, ensure_ascii=False)
            report_file.write_text(f"{text}\n", encoding="utf-8")
            return

        rows = []
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            for key, value in payload.items():
                rows.append({
                    "key": key,
                    "value": json.dumps(value, ensure_ascii=False) if not isinstance(value, (int, float, str, bool, type(None))) else value,
                })
        if rows:
            if not rows:
                report_file.write_text("", encoding="utf-8")
                return
            fieldnames = sorted({field for row in rows for field in row.keys()})
            from io import StringIO

            csv_buffer = StringIO()
            writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            report_file.write_text(csv_buffer.getvalue(), encoding="utf-8")
            return
        report_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def log_event(
    *,
    event_log_path: str,
    payload: Dict[str, Any],
) -> None:
    if not event_log_path:
        return
    event = dict(payload)
    event["logged_at"] = now_utc_iso()
    path = Path(event_log_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(event, ensure_ascii=False))
        fp.write("\n")


def run_self_heal(
    *,
    out_root: Path,
    manifest: Dict[str, Any],
    run_id: str,
    source: str,
    event_log_path: str,
    prune_orphans: bool,
) -> Dict[str, Any]:
    pre_health = run_health_check(out_root, manifest)
    result: Dict[str, Any] = {
        "event": "self_heal",
        "run_id": run_id,
        "source": source,
        "out": str(out_root),
        "pre_health": pre_health,
    }

    if pre_health.get("status") == "ok":
        result["status"] = "ok"
        result["repair_applied"] = False
        log_event(event_log_path=event_log_path, payload=result)
        return result

    logging.warning("Self-heal triggered for run %s (run_id=%s)", source, run_id)
    repair_summary = run_repair_state(
        out_root=out_root,
        manifest=manifest,
        prune_orphans=prune_orphans,
    )
    manifest["updated_at"] = now_utc_iso()
    manifest["run_id"] = run_id
    post_health = run_health_check(out_root, manifest)
    result["status"] = post_health.get("status", "degraded")
    result["repair_applied"] = True
    result["repair_summary"] = repair_summary
    result["post_health"] = post_health
    log_event(event_log_path=event_log_path, payload=result)
    return result


def evaluate_run_exit(
    mode: str,
    run_stats: Dict[str, int],
    *,
    fail_on_error: bool,
    max_errors: int,
    require_new: int,
) -> int:
    if fail_on_error and run_stats.get("failed", 0) > 0:
        logging.error("Failing %s run because fail_on_error is enabled and errors were encountered", mode)
        return 2

    if max_errors > 0 and run_stats.get("failed", 0) >= max_errors:
        logging.error(
            "Failing %s run because failed=%s >= max_errors=%s",
            mode,
            run_stats.get("failed", 0),
            max_errors,
        )
        return 2

    if require_new > 0 and run_stats.get("new", 0) < require_new:
        logging.error(
            "Failing %s run because new=%s < require_new=%s",
            mode,
            run_stats.get("new", 0),
            require_new,
        )
        return 3

    return 0


def run_once(
    *,
    source_root: Path,
    out_root: Path,
    do_ocr: bool,
    make_thumbnail: bool,
    do_copy: bool,
    dry_run: bool,
    manifest: Dict[str, Any],
    post_hooks: List[str],
    post_hook_on: str,
    post_hook_timeout: int,
    post_hook_stop_on_failure: bool,
    post_hook_max_attempts: int,
    post_hook_retry_delay: float,
    post_hook_shell: bool,
    run_id: str,
    cleanup_raw: bool,
    cleanup_raw_days: int,
    cleanup_state_days: int,
    include_patterns: Iterable[str],
    exclude_patterns: Iterable[str],
    max_files: int,
    allowed_media_types: Set[str],
    min_size_bytes: int,
    max_size_bytes: int,
    follow_symlinks: bool,
    ocr_lang: str,
    thumbnail_size: int,
    video_seek: str,
) -> Dict[str, int]:
    all_files = list(
        discover_media_files(
            source_root,
            out_root=out_root,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            allowed_media_types=allowed_media_types,
            min_size_bytes=min_size_bytes,
            max_size_bytes=max_size_bytes,
            follow_symlinks=follow_symlinks,
        )
    )
    source_state = manifest.setdefault("source_index", {})
    candidate_files: List[Path] = []
    skipped = 0
    for p in sorted(all_files):
        if should_skip_source_file(p, source_state):
            skipped += 1
            continue
        candidate_files.append(p)
        if max_files > 0 and len(candidate_files) >= max_files:
            break

    stats = manifest.setdefault("stats", {})
    if "files_seen_total" not in stats and "total_files_seen" in stats:
        stats["files_seen_total"] = stats.get("total_files_seen", 0)
    stats["files_seen_total"] += len(all_files)
    stats["runs"] = stats.get("runs", 0) + 1

    run_stats = {
        "discovered": len(all_files),
        "candidate": len(candidate_files),
        "skipped": skipped,
        "new": 0,
        "duplicates": 0,
        "failed": 0,
        "post_hook_attempts": 0,
        "post_hook_success": 0,
        "post_hook_failures": 0,
        "removed_raw": 0,
        "index_rows": 0,
        "index_pruned": 0,
        "state_pruned_processed": 0,
        "state_pruned_duplicates": 0,
        "state_pruned_hash_index": 0,
    }

    if dry_run:
        print("Found files:")
        for p in candidate_files:
            print(p)
        if skipped:
            print(f"Skipped {skipped} files unchanged since last successful run")
        if max_files > 0 and len(candidate_files) >= max_files:
            print(f"Max file limit reached ({max_files}); remaining files unchanged.")
        print(f"Would process {len(candidate_files)} files")
        removed = 0
        if cleanup_raw and cleanup_raw_days > 0:
            removed = cleanup_stale_raw_files(
                source_root,
                manifest=manifest,
                dry_run=True,
                max_age_days=cleanup_raw_days,
            )
        if removed:
            logging.info("Would remove %s stale raw source files", removed)
        if cleanup_state_days > 0:
            logging.info("State retention would prune entries older than %s days", cleanup_state_days)
        return run_stats

    processed_hashes = build_hash_index(manifest)
    records: List[CaptureRecord] = []
    for path in candidate_files:
        resolved_path = resolve_media_path(path)
        if not resolved_path.exists():
            logging.warning("Skipping vanished source file: %s", path)
            run_stats["failed"] += 1
            errors = manifest.setdefault("errors", [])
            if isinstance(errors, list):
                errors.append({
                    "path": str(path),
                    "error": "source_missing",
                    "occurred_at": now_utc_iso(),
                })
            else:
                manifest["errors"] = [{
                    "path": str(path),
                    "error": "source_missing",
                    "occurred_at": now_utc_iso(),
                }]
            continue
        path = resolved_path
        try:
            record = process_file(
                path,
                out_root,
                do_ocr=do_ocr,
                ocr_lang=ocr_lang,
                make_thumbnail=make_thumbnail,
                thumbnail_size=thumbnail_size,
                video_seek=video_seek,
                do_copy=do_copy,
                manifest=manifest,
                processed_hashes=processed_hashes,
                post_hooks=post_hooks,
                post_hook_on=post_hook_on,
                post_hook_timeout=post_hook_timeout,
                post_hook_stop_on_failure=post_hook_stop_on_failure,
                post_hook_max_attempts=post_hook_max_attempts,
                post_hook_retry_delay=post_hook_retry_delay,
                post_hook_shell=post_hook_shell,
                run_id=run_id,
                run_stats=run_stats,
            )
            if record:
                records.append(record)
                if record.status == "duplicate":
                    run_stats["duplicates"] += 1
                elif record.status == "processed":
                    run_stats["new"] += 1
        except Exception as exc:  # pragma: no cover - broad catch to keep pipeline resilient
            logging.exception("Failed processing %s", path)
            bump_stat(manifest, "errors")
            run_stats["failed"] += 1
            errors = manifest.setdefault("errors", [])
            if isinstance(errors, list):
                errors.append({
                    "path": str(path),
                    "error": str(exc),
                    "occurred_at": now_utc_iso(),
                })
            else:
                manifest["errors"] = [{
                    "path": str(path),
                    "error": str(exc),
                    "occurred_at": now_utc_iso(),
                }]

    index_rows, index_pruned = build_index(records, out_root, retention_days=cleanup_state_days)
    run_stats["index_rows"] = index_rows
    run_stats["index_pruned"] = index_pruned

    prune_summary = prune_manifest_state(manifest, out_root, retention_days=cleanup_state_days)
    run_stats["state_pruned_processed"] = prune_summary["pruned_processed"]
    run_stats["state_pruned_duplicates"] = prune_summary["pruned_duplicates"]
    run_stats["state_pruned_hash_index"] = prune_summary["pruned_hash_index"]
    if do_copy and cleanup_raw and cleanup_raw_days > 0:
        removed = cleanup_stale_raw_files(
            source_root,
            manifest=manifest,
            dry_run=dry_run,
            max_age_days=cleanup_raw_days,
        )
        bump_stat(manifest, "raw_cleanup_deleted", removed)
        run_stats["removed_raw"] = removed
        if removed:
            logging.info("Removed %s stale raw source files", removed)
    bump_stat(manifest, "discovered", len(all_files))
    bump_stat(manifest, "new", run_stats["new"])
    bump_stat(manifest, "duplicates", run_stats["duplicates"])
    bump_stat(manifest, "errors", run_stats["failed"])
    manifest.setdefault("stats", {})["index_rows"] = run_stats["index_rows"]
    return run_stats


def main() -> None:
    args = parse_args()
    setup_logging(args.verbose)
    source_root = Path(args.source).expanduser().resolve()
    out_root = Path(args.out).expanduser().resolve()
    post_hooks = normalize_post_hooks(args.post_hook)
    post_hook_on = args.post_hook_on
    post_hook_max_attempts = max(0, args.post_hook_max_attempts)
    post_hook_retry_delay = max(0.0, args.post_hook_retry_delay)
    post_hook_shell = args.post_hook_shell
    do_ocr = not args.no_ocr
    make_thumbnail = not args.no_thumbnails
    do_copy = args.copy
    run_id = args.run_id.strip() if args.run_id else f"run-{int(time.time())}-{os.getpid()}"
    report_payload: Dict[str, Any]

    requested_media_types = [item.strip().lower() for item in str(args.media_types).split(",") if item.strip()]
    if not requested_media_types or "all" in requested_media_types:
        allowed_media_types: Set[str] = {"all", "image", "video", "document"}
    else:
        requested_set = set(requested_media_types)
        valid_types = {"image", "video", "document"}
        if not requested_set.issubset(valid_types):
            raise SystemExit(f"Invalid --media-types value(s): {sorted(requested_set - valid_types)}")
        allowed_media_types = requested_set

    if args.query:
        matched = run_query(out_root, args)
        if args.query_required_min > 0 and matched < args.query_required_min:
            raise SystemExit(1)
        return

    manifest_path = out_root / "manifest.json"
    lock_path = Path(args.lock_path).expanduser().resolve() if args.lock_path else manifest_path.with_suffix(".lock")

    def make_lock_context() -> Iterator[None]:
        if args.disable_lock:
            return noop_run_lock()
        return acquire_run_lock(
            lock_path,
            run_id=run_id,
            timeout_seconds=max(0, args.lock_timeout),
            stale_seconds=max(1, args.lock_stale_seconds),
        )

    with make_lock_context():
        if args.check_source:
            manifest = load_manifest(manifest_path)
            manifest.setdefault("stats", {})["check_runs"] = manifest.setdefault("stats", {}).get("check_runs", 0) + 1
            write_manifest(
                manifest_path,
                manifest,
                manifest_backup_count=args.manifest_backup_count,
            )
            summary = run_check_source(
                source_root,
                out_root,
                include_patterns=args.include,
                exclude_patterns=args.exclude,
                allowed_media_types=allowed_media_types,
                min_size_bytes=max(0, args.min_size_bytes),
                max_size_bytes=max(0, args.max_size_bytes),
                follow_symlinks=args.follow_symlinks,
            )
            report_payload = {
                "mode": "check-source",
                "source": str(source_root),
                "out": str(out_root),
                "summary": summary,
            }
            emit_report(
                report_payload,
                json_report=args.json_report,
                report_path=args.report,
                report_format=args.json_report_format,
            )
            if not args.json_report and not args.report:
                print(json.dumps(summary, ensure_ascii=False))
            log_event(
                event_log_path=args.event_log,
                payload={
                    "event": "check_source",
                    "run_id": run_id,
                    "source": str(source_root),
                    "out": str(out_root),
                    "summary": summary,
                },
            )
            return

        if args.verify:
            manifest = load_manifest(manifest_path)
            health = run_health_check(out_root, manifest)
            payload = {
                "mode": "verify",
                "source": str(source_root),
                "out": str(out_root),
                "health": health,
            }
            emit_report(
                payload,
                json_report=args.json_report,
                report_path=args.report,
                report_format=args.json_report_format,
            )
            if not args.json_report and not args.report:
                print(json.dumps(payload, ensure_ascii=False))
            log_event(
                event_log_path=args.event_log,
                payload={
                    "event": "verify",
                    "run_id": run_id,
                    "source": str(source_root),
                    "out": str(out_root),
                    "health": health,
                },
            )
            if health.get("status") != "ok":
                raise SystemExit(2)
            return

        if args.watch and args.dry_run:
            raise SystemExit("--dry-run cannot be used with --watch")

        if args.cleanup_raw and args.cleanup_raw_days <= 0:
            raise SystemExit("--cleanup-raw requires --cleanup-raw-days > 0")
        if args.cleanup_state_days < 0:
            raise SystemExit("--cleanup-state-days cannot be negative")
        if args.cleanup_raw and not args.copy:
            logging.warning("--cleanup-raw has effect only in --copy mode; it will be skipped.")

        manifest = load_manifest(manifest_path)
        manifest["run_id"] = run_id
        if manifest.get("schema_version", 1) < 2:
            manifest["schema_version"] = 2

        if args.repair:
            repair_summary = run_repair_state(
                out_root=out_root,
                manifest=manifest,
                prune_orphans=args.repair_orphan_assets,
            )
            manifest["updated_at"] = now_utc_iso()
            manifest["run_id"] = run_id
            write_manifest(
                manifest_path,
                manifest,
                manifest_backup_count=args.manifest_backup_count,
            )
            logging.info(
                "Repair complete: index_rows=%s pruned_processed=%s pruned_duplicates=%s pruned_source_index=%s pruned_hash_index=%s pruned_orphan_sidecars=%s pruned_orphan_thumbnails=%s",
                repair_summary["index_rows"],
                repair_summary["pruned_processed"],
                repair_summary["pruned_duplicates"],
                repair_summary["pruned_source_index"],
                repair_summary["pruned_hash_index"],
                repair_summary.get("pruned_orphan_sidecars"),
                repair_summary.get("pruned_orphan_thumbnails"),
            )
            emit_report(
                {"mode": "repair", "summary": repair_summary},
                json_report=args.json_report,
                report_path=args.report,
                report_format=args.json_report_format,
            )
            log_event(
                event_log_path=args.event_log,
                payload={
                    "event": "repair",
                    "run_id": run_id,
                    "source": str(source_root),
                    "out": str(out_root),
                    "summary": repair_summary,
                },
            )
            return

        if args.watch:
            interval = max(1.0, float(args.interval))
            jitter = max(0.0, min(1.0, float(args.watch_jitter)))
            idle_seconds = 0.0
            logging.info("Starting watch mode on %s (every %.1fs)", source_root, interval)
            runs = 0
            watch_exit_code = 0
            try:
                while True:
                    runs += 1
                    run_start = time.time()
                    run_stats = run_once(
                        source_root=source_root,
                        out_root=out_root,
                        do_ocr=do_ocr,
                        make_thumbnail=make_thumbnail,
                        do_copy=do_copy,
                        dry_run=False,
                        manifest=manifest,
                        post_hooks=post_hooks,
                        post_hook_on=post_hook_on,
                        post_hook_timeout=args.post_hook_timeout,
                        post_hook_stop_on_failure=args.post_hook_stop_on_failure,
                        post_hook_max_attempts=post_hook_max_attempts,
                        post_hook_retry_delay=post_hook_retry_delay,
                        post_hook_shell=post_hook_shell,
                        run_id=run_id,
                        cleanup_raw=args.cleanup_raw and do_copy,
                        cleanup_raw_days=args.cleanup_raw_days,
                        cleanup_state_days=args.cleanup_state_days,
                        include_patterns=args.include,
                        exclude_patterns=args.exclude,
                        max_files=args.max_files,
                        allowed_media_types=allowed_media_types,
                        min_size_bytes=max(0, args.min_size_bytes),
                        max_size_bytes=max(0, args.max_size_bytes),
                        follow_symlinks=args.follow_symlinks,
                        ocr_lang=args.ocr_lang,
                        thumbnail_size=max(1, args.thumbnail_size),
                        video_seek=args.video_seek,
                    )
                    if any(run_stats.get(k, 0) for k in ("new", "duplicates", "failed")):
                        logging.info(
                            "Watch pass %s: new=%s duplicates=%s failed=%s",
                            runs,
                            run_stats.get("new", 0),
                            run_stats.get("duplicates", 0),
                            run_stats.get("failed", 0),
                        )

                    if any(run_stats.get(k, 0) > 0 for k in ("new", "duplicates", "failed")):
                        idle_seconds = 0.0
                    else:
                        idle_seconds += interval

                    watch_exit_code = evaluate_run_exit(
                        "watch",
                        run_stats,
                        fail_on_error=args.fail_on_error,
                        max_errors=args.max_errors,
                        require_new=args.require_new,
                    )

                    if args.watch_heartbeat:
                        heartbeat_payload = {
                            "run": runs,
                            "source": str(source_root),
                            "out": str(out_root),
                            "updated_at": now_utc_iso(),
                            "idle_seconds": idle_seconds,
                            "stats": run_stats,
                        }
                        heartbeat_path = Path(args.watch_heartbeat).expanduser().resolve()
                        heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
                        heartbeat_path.write_text(json.dumps(heartbeat_payload, indent=2), encoding="utf-8")
                        log_event(
                            event_log_path=args.event_log,
                            payload={
                                "event": "watch_heartbeat",
                                "run_id": run_id,
                                "mode": "watch",
                                "run": runs,
                                "source": str(source_root),
                                "out": str(out_root),
                                "stats": run_stats,
                                "idle_seconds": idle_seconds,
                            },
                        )

                    emit_report(
                        {
                            "mode": "watch",
                            "run": runs,
                            "source": str(source_root),
                            "out": str(out_root),
                            "stats": run_stats,
                            "idle_seconds": idle_seconds,
                        },
                        json_report=args.json_report,
                        report_path=args.report,
                        report_format=args.json_report_format,
                    )

                    manifest["updated_at"] = now_utc_iso()
                    write_manifest(
                        manifest_path,
                        manifest,
                        manifest_backup_count=args.manifest_backup_count,
                    )
                    if args.self_heal:
                        self_heal = run_self_heal(
                            out_root=out_root,
                            manifest=manifest,
                            run_id=run_id,
                            source=str(source_root),
                            event_log_path=args.event_log,
                            prune_orphans=args.self_heal_repair_orphans,
                        )
                        if self_heal.get("status") != "ok":
                            watch_exit_code = 2
                    log_event(
                        event_log_path=args.event_log,
                        payload={
                            "event": "watch_pass",
                            "run_id": run_id,
                            "mode": "watch",
                            "run": runs,
                            "source": str(source_root),
                            "out": str(out_root),
                            "stats": run_stats,
                            "idle_seconds": idle_seconds,
                            "exit_code": watch_exit_code,
                            "duration_ms": int((time.time() - run_start) * 1000),
                        },
                    )

                    if watch_exit_code:
                        break
                    if args.max_runs and runs >= args.max_runs:
                        break
                    if args.watch_idle_threshold > 0 and idle_seconds >= args.watch_idle_threshold:
                        logging.info(
                            "Watch idle threshold reached (%.1fs); exiting.",
                            args.watch_idle_threshold,
                        )
                        break

                    elapsed = time.time() - run_start
                    sleep_for = max(0.0, interval - elapsed)
                    if jitter > 0:
                        sleep_for += random.uniform(-sleep_for * jitter, sleep_for * jitter)
                    if sleep_for < 0:
                        sleep_for = 0.0
                    time.sleep(sleep_for)
            except KeyboardInterrupt:
                logging.info("Watch stopped by user")
            if watch_exit_code:
                raise SystemExit(watch_exit_code)
        else:
            run_stats = run_once(
                source_root=source_root,
                out_root=out_root,
                do_ocr=do_ocr,
                make_thumbnail=make_thumbnail,
                do_copy=do_copy,
                dry_run=args.dry_run,
                manifest=manifest,
                post_hooks=post_hooks,
                post_hook_on=post_hook_on,
                post_hook_timeout=args.post_hook_timeout,
                post_hook_stop_on_failure=args.post_hook_stop_on_failure,
                post_hook_max_attempts=post_hook_max_attempts,
                post_hook_retry_delay=post_hook_retry_delay,
                post_hook_shell=post_hook_shell,
                run_id=run_id,
                cleanup_raw=args.cleanup_raw and do_copy,
                cleanup_raw_days=args.cleanup_raw_days,
                cleanup_state_days=args.cleanup_state_days,
                include_patterns=args.include,
                exclude_patterns=args.exclude,
                max_files=args.max_files,
                allowed_media_types=allowed_media_types,
                min_size_bytes=max(0, args.min_size_bytes),
                max_size_bytes=max(0, args.max_size_bytes),
                follow_symlinks=args.follow_symlinks,
                ocr_lang=args.ocr_lang,
                thumbnail_size=max(1, args.thumbnail_size),
                video_seek=args.video_seek,
            )
            manifest["updated_at"] = now_utc_iso()
            write_manifest(
                manifest_path,
                manifest,
                manifest_backup_count=args.manifest_backup_count,
            )
            exit_code = 0
            if args.self_heal:
                self_heal = run_self_heal(
                    out_root=out_root,
                    manifest=manifest,
                    run_id=run_id,
                    source=str(source_root),
                    event_log_path=args.event_log,
                    prune_orphans=args.self_heal_repair_orphans,
                )
                if self_heal.get("status") != "ok":
                    exit_code = 2
                    run_stats["self_heal_status"] = self_heal.get("status")
            log_event(
                event_log_path=args.event_log,
                payload={
                    "event": "run_once",
                    "run_id": run_id,
                    "mode": "once",
                    "source": str(source_root),
                    "out": str(out_root),
                    "stats": run_stats,
                    "exit_code": exit_code,
                },
            )

            emit_report(
                {
                    "mode": "once",
                    "source": str(source_root),
                    "out": str(out_root),
                    "stats": run_stats,
                },
                json_report=args.json_report,
                report_path=args.report,
                report_format=args.json_report_format,
            )
            watch_exit_code = evaluate_run_exit(
                "once",
                run_stats,
                fail_on_error=args.fail_on_error,
                max_errors=args.max_errors,
                require_new=args.require_new,
            )
            if not watch_exit_code:
                watch_exit_code = exit_code
            if watch_exit_code:
                raise SystemExit(watch_exit_code)

        stats = manifest.setdefault("stats", {})
        logging.info(
            "Done. New=%s duplicates=%s errors=%s",
            stats.get("new", 0),
            stats.get("duplicates", 0),
            stats.get("errors", 0),
        )


if __name__ == "__main__":
    main()
