"""Runtime bridge from HTTP/MCP surface to the existing capture CLI."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import (
    ActionResult,
    PlatformValidationError,
    RunOptions,
    coerce_int,
    default_out_dir,
    default_source_dir,
    normalize_optional_platform_path,
    normalize_platform_path,
    processor_script,
    validate_choice,
    validate_media_types,
    validate_query,
    validate_run_id,
)


def telemetry_report_path(options: RunOptions) -> Path:
    mode = options.mode.replace("_", "-")
    safe_mode = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in mode)
    run_id = options.run_id or f"api-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    return options.normalized_out() / "reports" / f"platform-{safe_mode}-{run_id}.json"


def ensure_telemetry_paths(options: RunOptions) -> None:
    if options.event_log is None:
        options.event_log = options.normalized_out() / "platform-events.jsonl"
    if options.report is None:
        options.report = telemetry_report_path(options)


def build_base_command(options: RunOptions) -> List[str]:
    source = options.normalized_source()
    out = options.normalized_out()
    run_id = options.run_id or f"api-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    if not options.run_id:
        options.run_id = run_id
    ensure_telemetry_paths(options)

    command = [
        sys.executable,
        str(processor_script()),
        str(source),
        "--out",
        str(out),
        "--json-report",
        "--run-id",
        run_id,
        "--media-types",
        options.media_types,
        "--max-files",
        str(int(options.max_files)),
        "--event-log",
        str(options.event_log),
        "--report",
        str(options.report),
    ]

    if options.copy:
        command.append("--copy")
    if options.no_ocr:
        command.append("--no-ocr")
    if options.no_thumbnails:
        command.append("--no-thumbnails")
    if options.min_size_bytes and options.min_size_bytes > 0:
        command += ["--min-size-bytes", str(options.min_size_bytes)]
    if options.max_size_bytes and options.max_size_bytes > 0:
        command += ["--max-size-bytes", str(options.max_size_bytes)]
    if options.dry_run:
        command.append("--dry-run")

    return command


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def parse_options(payload: Dict[str, Any], roots: Optional[List[Path]] = None) -> RunOptions:
    source = normalize_platform_path(
        payload.get("source"), default=default_source_dir(), field="source", roots=roots
    )
    out = normalize_platform_path(
        payload.get("out"), default=default_out_dir(), field="out", roots=roots
    )
    mode = validate_choice(
        str(payload.get("mode", "process")),
        field="mode",
        allowed={
            "check-source",
            "check_source",
            "process",
            "query",
            "repair",
            "run",
            "once",
            "verify",
        },
    )

    return RunOptions(
        source=source,
        out=out,
        mode=mode,
        copy=_coerce_bool(payload.get("copy")),
        media_types=validate_media_types(
            str(payload.get("media_types", payload.get("mediaTypes", "all")))
        ),
        min_size_bytes=coerce_int(
            payload.get("min_size_bytes", payload.get("minSizeBytes", 0)),
            field="min_size_bytes",
            default=0,
            minimum=0,
            maximum=10_000_000_000,
        ),
        max_size_bytes=coerce_int(
            payload.get("max_size_bytes", payload.get("maxSizeBytes", 0)),
            field="max_size_bytes",
            default=0,
            minimum=0,
            maximum=10_000_000_000,
        ),
        max_files=coerce_int(
            payload.get("max_files", payload.get("maxFiles", 0)),
            field="max_files",
            default=0,
            minimum=0,
            maximum=50_000,
        ),
        query=validate_query(payload.get("query", "")),
        query_media=validate_choice(
            str(payload.get("query_media", payload.get("queryMedia", "all"))),
            field="query_media",
            allowed={"all", "image", "video", "document"},
        ),
        query_status=validate_choice(
            str(payload.get("query_status", payload.get("queryStatus", "all"))),
            field="query_status",
            allowed={"all", "processed", "duplicate"},
        ),
        query_limit=coerce_int(
            payload.get("query_limit", payload.get("queryLimit", 50)),
            field="query_limit",
            default=50,
            minimum=0,
            maximum=1000,
        ),
        no_ocr=_coerce_bool(payload.get("no_ocr", payload.get("noOcr", False))),
        no_thumbnails=_coerce_bool(
            payload.get("no_thumbnails", payload.get("noThumbnails", False))
        ),
        run_id=validate_run_id(payload.get("run_id", payload.get("runId", ""))),
        timeout_sec=coerce_int(
            payload.get("timeout", payload.get("timeoutSec", 120)),
            field="timeout",
            default=120,
            minimum=1,
            maximum=600,
        ),
        dry_run=_coerce_bool(payload.get("dry_run", payload.get("dryRun", False))),
        event_log=normalize_optional_platform_path(
            payload.get("event_log", payload.get("eventLog")),
            field="event_log",
            roots=roots,
        ),
        report=normalize_optional_platform_path(
            payload.get("report", payload.get("reportPath")),
            field="report",
            roots=roots,
        ),
    )


def build_command_for_mode(options: RunOptions) -> List[str]:
    command = build_base_command(options)

    if options.mode in {"check-source", "check_source"}:
        command.append("--check-source")
        return command

    if options.mode in {"verify"}:
        command.append("--verify")
        return command

    if options.mode in {"repair"}:
        command.append("--repair")
        return command

    if options.mode in {"query"}:
        command += ["--query", options.query]
        if options.query_media:
            command += ["--query-media", options.query_media]
        if options.query_status:
            command += ["--query-status", options.query_status]
        if options.query_limit:
            command += ["--query-limit", str(options.query_limit)]
        return command

    if options.mode in {"process", "run", "once"}:
        return command

    raise ValueError(f"unsupported mode: {options.mode}")


def _safe_parse_json(payload: str) -> Any:
    lines = [line.strip() for line in str(payload).splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            return json.loads(line)
        except Exception:
            continue
    try:
        return json.loads(payload)
    except Exception:
        return {"text": payload}


def run_capture_action(
    payload: Dict[str, Any], roots: Optional[List[Path]] = None
) -> ActionResult:
    start = time.time()
    mode = str(payload.get("mode", "process"))
    run_id = str(payload.get("run_id", payload.get("runId", "")) or "")
    source = str(payload.get("source", ""))
    out = str(payload.get("out", ""))
    try:
        options = parse_options(payload, roots=roots)
        run_id = options.run_id or f"run-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        options.run_id = run_id
        command = build_command_for_mode(options)
        mode = options.mode
        source = str(options.normalized_source())
        out = str(options.normalized_out())
        process = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(1, options.timeout_sec),
        )
        stdout = process.stdout or ""
        stderr = process.stderr or ""
        parsed_payload: object = _safe_parse_json(stdout)
        duration_ms = int((time.time() - start) * 1000)
        return ActionResult(
            ok=(process.returncode == 0),
            run_id=run_id,
            mode=options.mode,
            duration_ms=duration_ms,
            return_code=process.returncode,
            payload=parsed_payload,
            stdout=stdout,
            stderr=stderr,
            source=source,
            out=out,
            event_log=str(options.event_log or ""),
            report=str(options.report or ""),
            error=None if process.returncode == 0 else "command_failed",
        )
    except PlatformValidationError as exc:
        duration_ms = int((time.time() - start) * 1000)
        return ActionResult(
            ok=False,
            run_id=run_id,
            mode=mode,
            duration_ms=duration_ms,
            return_code=2,
            payload={"error": "validation_error", "message": str(exc)},
            stdout="",
            stderr=str(exc),
            source=source,
            out=out,
            event_log="",
            report="",
            error="validation_error",
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.time() - start) * 1000)
        return ActionResult(
            ok=False,
            run_id=run_id,
            mode=options.mode,
            duration_ms=duration_ms,
            return_code=124,
            payload={"error": "timeout"},
            stdout=exc.stdout or "",
            stderr=str(exc),
            source=source,
            out=out,
            event_log=str(getattr(options, "event_log", "") or ""),
            report=str(getattr(options, "report", "") or ""),
            error="timeout",
        )
    except Exception as exc:  # pragma: no cover - integration safety
        duration_ms = int((time.time() - start) * 1000)
        return ActionResult(
            ok=False,
            run_id=run_id,
            mode=options.mode,
            duration_ms=duration_ms,
            return_code=1,
            payload={"error": str(exc)},
            stdout="",
            stderr=str(exc),
            source=source,
            out=out,
            event_log=str(getattr(options, "event_log", "") or ""),
            report=str(getattr(options, "report", "") or ""),
            error="runtime_error",
        )


def load_snapshot(out: Path) -> Dict[str, Any]:
    manifest_path = out.resolve() / "manifest.json"
    index_path = out.resolve() / "index.jsonl"
    pipeline_events_path = out.resolve() / "pipeline-events.jsonl"
    platform_events_path = out.resolve() / "platform-events.jsonl"
    reports_path = out.resolve() / "reports"
    report_files = sorted(reports_path.glob("*.json")) if reports_path.exists() else []
    result: Dict[str, Any] = {
        "manifest_exists": manifest_path.exists(),
        "index_exists": index_path.exists(),
        "events_exists": pipeline_events_path.exists() or platform_events_path.exists(),
        "pipeline_events_exists": pipeline_events_path.exists(),
        "platform_events_exists": platform_events_path.exists(),
        "reports_exists": reports_path.exists(),
        "report_count": len(report_files),
        "latest_report": str(report_files[-1]) if report_files else "",
        "manifest": None,
        "index_rows": 0,
    }

    if manifest_path.exists():
        try:
            result["manifest"] = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            result["manifest"] = {"error": "unreadable_manifest"}

    if index_path.exists():
        with index_path.open("r", encoding="utf-8") as handle:
            result["index_rows"] = sum(1 for _ in handle if _.strip())

    return result
