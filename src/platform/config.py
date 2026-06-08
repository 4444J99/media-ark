"""Configuration, validation, and typed options for the platform services."""

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional


class PlatformValidationError(ValueError):
    """Raised when API/MCP input would cross the configured runtime boundary."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def processor_script() -> Path:
    return Path(__file__).resolve().parents[2] / "src" / "capture_automation" / "process_captures.py"


def default_source_dir() -> Path:
    return repo_root() / "data" / "captures" / "raw"


def default_out_dir() -> Path:
    return repo_root() / ".capture-automation"


def _dedupe_paths(paths: Iterable[Path]) -> List[Path]:
    seen = set()
    result: List[Path] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        result.append(resolved)
    return result


def allowed_roots() -> List[Path]:
    raw = os.environ.get("CAPTURE_PLATFORM_ALLOWED_ROOTS", "").strip()
    if raw:
        configured = [Path(item) for item in raw.split(os.pathsep) if item.strip()]
        return _dedupe_paths(configured)
    return _dedupe_paths([repo_root(), Path(tempfile.gettempdir())])


def is_path_allowed(path: Path, roots: Optional[List[Path]] = None) -> bool:
    resolved = path.expanduser().resolve()
    for root in roots or allowed_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def normalize_platform_path(value: Any, *, default: Path, field: str) -> Path:
    raw = str(value or default).strip()
    if not raw:
        raise PlatformValidationError(f"{field} path is required")
    if "\x00" in raw:
        raise PlatformValidationError(f"{field} path contains a null byte")
    path = Path(raw).expanduser().resolve()
    if not is_path_allowed(path):
        roots = ", ".join(str(root) for root in allowed_roots())
        raise PlatformValidationError(f"{field} path is outside allowed roots: {roots}")
    return path


def normalize_optional_platform_path(value: Any, *, field: str) -> Optional[Path]:
    if value in (None, ""):
        return None
    return normalize_platform_path(value, default=repo_root(), field=field)


def coerce_int(
    value: Any,
    *,
    field: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value in (None, ""):
        number = default
    else:
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise PlatformValidationError(f"{field} must be an integer") from exc
    if number < minimum:
        raise PlatformValidationError(f"{field} must be >= {minimum}")
    if number > maximum:
        raise PlatformValidationError(f"{field} must be <= {maximum}")
    return number


def validate_choice(value: str, *, field: str, allowed: Iterable[str]) -> str:
    normalized = str(value).strip().lower()
    allowed_set = set(allowed)
    if normalized not in allowed_set:
        raise PlatformValidationError(f"{field} must be one of: {', '.join(sorted(allowed_set))}")
    return normalized


def validate_media_types(value: str) -> str:
    raw_items = [item.strip().lower() for item in str(value or "all").split(",") if item.strip()]
    if not raw_items or "all" in raw_items:
        return "all"
    allowed = {"image", "video", "document"}
    requested = set(raw_items)
    invalid = requested - allowed
    if invalid:
        raise PlatformValidationError(f"media_types contains invalid values: {', '.join(sorted(invalid))}")
    return ",".join(item for item in raw_items if item in allowed)


def validate_query(value: Any, *, field: str = "query", max_chars: int = 500) -> str:
    text = str(value or "")
    if len(text) > max_chars:
        raise PlatformValidationError(f"{field} must be <= {max_chars} characters")
    return text


def validate_run_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", text):
        raise PlatformValidationError("run_id may contain only letters, numbers, dot, underscore, colon, and dash")
    return text


@dataclass
class RunOptions:
    source: Path
    out: Path
    mode: str = "process"
    copy: bool = False
    media_types: str = "all"
    min_size_bytes: int = 0
    max_size_bytes: int = 0
    max_files: int = 0
    query: str = ""
    query_media: str = "all"
    query_status: str = "all"
    query_limit: int = 50
    no_ocr: bool = False
    no_thumbnails: bool = False
    run_id: str = ""
    timeout_sec: int = 120
    dry_run: bool = False
    event_log: Optional[Path] = None
    report: Optional[Path] = None

    def normalized_source(self) -> Path:
        return self.source.expanduser().resolve()

    def normalized_out(self) -> Path:
        return self.out.expanduser().resolve()


@dataclass
class ActionResult:
    ok: bool
    run_id: str
    mode: str
    duration_ms: int
    return_code: int
    payload: object
    stdout: str = ""
    stderr: str = ""
    source: str = ""
    out: str = ""
    error: Optional[str] = None
    event_log: str = ""
    report: str = ""
