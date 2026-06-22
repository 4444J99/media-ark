"""Configuration, validation, and typed options for the platform services."""

import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional

# Ensure the `media_ark` brand module is importable when this file is
# imported as `src.platform.config` (the brand module lives at the top
# of `src/`).
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.append(str(_SRC))

from media_ark import BRAND_DATA_DIR, BRAND_PYTHON_PKG, env_key  # noqa: E402


class PlatformValidationError(ValueError):
    """Raised when API/MCP input would cross the configured runtime boundary."""


_TRUTHY = {"1", "true", "yes", "on", "enabled"}


def env_truthy(suffix: str, *, default: bool = False) -> bool:
    """Return True when the ``MEDIA_ARK_<suffix>`` env var is set to a truthy value."""
    raw = os.environ.get(env_key(suffix))
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


def pro_enabled() -> bool:
    """Return True when the 'pro' feature tier is enabled via ``MEDIA_ARK_PRO``.

    Pro-only scaffolding (e.g. encrypted cloud sync in ``platform.sync``)
    must check this before doing any work. It is opt-in and defaults to off
    so the local-first pipeline never reaches the network unless asked.
    """
    return env_truthy("PRO")


@dataclass
class SyncConfig:
    """Connection settings for the encrypted cloud-sync backend (S3 / R2).

    All fields are read from ``MEDIA_ARK_SYNC_*`` env vars by
    :func:`load_sync_config`. Credentials are optional here so that
    planning/encryption can be exercised (and unit-tested) without ever
    holding real secrets or touching a bucket.
    """

    bucket: str = ""
    endpoint_url: str = ""
    region: str = "auto"
    prefix: str = ""
    access_key_id: str = ""
    secret_access_key: str = ""

    @property
    def is_configured(self) -> bool:
        """True when at least a destination bucket has been supplied."""
        return bool(self.bucket)

    @property
    def has_credentials(self) -> bool:
        return bool(self.access_key_id and self.secret_access_key)

    @property
    def provider(self) -> str:
        """Best-effort label for the backend, derived from the endpoint."""
        endpoint = self.endpoint_url.lower()
        if not endpoint:
            return "s3"
        if "r2.cloudflarestorage.com" in endpoint or "r2." in endpoint:
            return "r2"
        return "s3-compatible"


def load_sync_config() -> SyncConfig:
    """Build a :class:`SyncConfig` from the ``MEDIA_ARK_SYNC_*`` environment."""
    return SyncConfig(
        bucket=os.environ.get(env_key("SYNC_BUCKET"), "").strip(),
        endpoint_url=os.environ.get(env_key("SYNC_ENDPOINT"), "").strip(),
        region=os.environ.get(env_key("SYNC_REGION"), "auto").strip() or "auto",
        prefix=os.environ.get(env_key("SYNC_PREFIX"), "").strip(),
        access_key_id=os.environ.get(env_key("SYNC_ACCESS_KEY_ID"), "").strip(),
        secret_access_key=os.environ.get(env_key("SYNC_SECRET_ACCESS_KEY"), "").strip(),
    )


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def processor_script() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "src"
        / BRAND_PYTHON_PKG
        / "process_captures.py"
    )


def default_source_dir() -> Path:
    raw = os.environ.get(env_key("SOURCE"), "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return repo_root() / "data" / "captures" / "raw"


def default_out_dir() -> Path:
    raw = os.environ.get(env_key("OUT"), "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return repo_root() / BRAND_DATA_DIR


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
    raw = os.environ.get(env_key("ALLOWED_ROOTS"), "").strip()
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


def normalize_platform_path(
    value: Any,
    *,
    default: Path,
    field: str,
    roots: Optional[List[Path]] = None,
) -> Path:
    raw = str(value or default).strip()
    if not raw:
        raise PlatformValidationError(f"{field} path is required")
    if "\x00" in raw:
        raise PlatformValidationError(f"{field} path contains a null byte")
    path = Path(raw).expanduser().resolve()
    allowed = roots or allowed_roots()
    if not is_path_allowed(path, allowed):
        root_list = ", ".join(str(root) for root in allowed)
        raise PlatformValidationError(f"{field} path is outside allowed roots: {root_list}")
    return path


def normalize_optional_platform_path(
    value: Any,
    *,
    field: str,
    roots: Optional[List[Path]] = None,
) -> Optional[Path]:
    if value in (None, ""):
        return None
    return normalize_platform_path(value, default=repo_root(), field=field, roots=roots)


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
        raise PlatformValidationError(
            f"{field} must be one of: {', '.join(sorted(allowed_set))}"
        )
    return normalized


def validate_media_types(value: str) -> str:
    raw_items = [
        item.strip().lower() for item in str(value or "all").split(",") if item.strip()
    ]
    if not raw_items or "all" in raw_items:
        return "all"
    allowed = {"image", "video", "document"}
    requested = set(raw_items)
    invalid = requested - allowed
    if invalid:
        raise PlatformValidationError(
            f"media_types contains invalid values: {', '.join(sorted(invalid))}"
        )
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
        raise PlatformValidationError(
            "run_id may contain only letters, numbers, dot, underscore, colon, and dash"
        )
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
