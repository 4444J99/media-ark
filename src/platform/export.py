"""Archive export surface: CSV / ZIP / JSON renderings of a processed `out` dir.

This module turns a processed output directory (the same `out` tree the
capture pipeline writes — `manifest.json`, `index.jsonl`, and per-capture
sidecar JSON files) into a downloadable artifact in one of three formats:

    csv  — the flattened index (``index.jsonl``) as a spreadsheet.
    zip  — ``manifest.json`` plus every OCR sidecar, bundled.
    json — the full archive (manifest + index rows + summary) as one document.

Export is a **pro-tier** feature and is **ownership-checked**. The HTTP route
passes the caller's bearer token; :func:`build_export` resolves it to a
principal against the configured pro-token set (``MEDIA_ARK_PRO_TOKENS``) and,
when the archive's ``manifest.json`` records an ``owner``, requires the
principal to match. The functions here are pure (input dir + token in, bytes
out) so they can be unit-tested without standing up the server.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

# Ensure the `media_ark` brand module is importable when this module is
# imported as `src.platform.export`.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from media_ark import BRAND_NAME, env_key

# Formats the export surface knows how to render, mapped to the
# (content-type, file extension) used for the download response.
EXPORT_FORMATS: Dict[str, Tuple[str, str]] = {
    "csv": ("text/csv; charset=utf-8", "csv"),
    "zip": ("application/zip", "zip"),
    "json": ("application/json; charset=utf-8", "json"),
}

# Sidecar files that live in `out` but are not per-capture OCR sidecars.
_NON_SIDECAR_NAMES = {"manifest.json", "index-summary.json", "config.json"}

# Preferred CSV column order; any remaining keys are appended sorted so the
# header is stable regardless of which fields a given index row happens to
# carry.
_CSV_PREFERRED_COLUMNS = [
    "id",
    "status",
    "media_type",
    "title",
    "source_path",
    "canonical_path",
    "path",
    "sha256",
    "size_bytes",
    "captured_at",
    "created_at",
    "duration",
    "tags",
    "notes",
    "thumbnail",
    "ocr_text",
    "text",
    "ocr",
]


class ExportError(Exception):
    """An export request that should map to a specific HTTP status.

    ``status`` is the HTTP code, ``error`` a stable machine-readable slug, and
    the message is human-readable. The API route serializes these three fields
    into the same ``{"ok": false, "error", "message"}`` envelope the rest of
    the server uses.
    """

    def __init__(self, status: int, error: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.error = error
        self.message = message


def extract_request_token(headers: Optional[Mapping[str, str]], query: Mapping[str, Any]) -> str:
    """Pull the caller's pro-tier token from headers or query string.

    Accepts ``Authorization: Bearer <token>``, ``X-Api-Key: <token>``, or a
    ``token`` query parameter, in that order of precedence.
    """
    if headers is not None:
        authorization = str(headers.get("Authorization", "") or "")
        if authorization[:7].lower() == "bearer ":
            token = authorization[7:].strip()
            if token:
                return token
        api_key = str(headers.get("X-Api-Key", "") or "").strip()
        if api_key:
            return api_key
    token = query.get("token", "")
    return str(token).strip() if token else ""


def load_pro_tokens(env: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Parse the configured pro-tier tokens into a ``{token: principal}`` map.

    ``MEDIA_ARK_PRO_TOKENS`` is a comma/newline-separated list of entries. Each
    entry is either a bare ``token`` (principal defaults to the token) or
    ``token:principal``. An unset/empty value means no tokens are configured,
    so export is effectively disabled.
    """
    source = os.environ if env is None else env
    raw = str(source.get(env_key("PRO_TOKENS"), "") or "").strip()
    tokens: Dict[str, str] = {}
    if not raw:
        return tokens
    for item in re.split(r"[,\n]", raw):
        entry = item.strip()
        if not entry:
            continue
        if ":" in entry:
            token, principal = entry.split(":", 1)
            token, principal = token.strip(), principal.strip()
        else:
            token, principal = entry, entry
        if token:
            tokens[token] = principal or token
    return tokens


def authorize_pro(token: str, tokens: Mapping[str, str]) -> str:
    """Resolve ``token`` to its principal, or raise an :class:`ExportError`."""
    if not tokens:
        raise ExportError(
            403, "pro_tier_required", "export is a pro-tier feature and no pro tokens are configured"
        )
    if not token:
        raise ExportError(
            401,
            "missing_token",
            "export requires a pro-tier token (Authorization: Bearer <token>)",
        )
    principal = tokens.get(token)
    if principal is None:
        raise ExportError(403, "pro_tier_required", "the supplied token is not authorized for export")
    return principal


def check_ownership(principal: str, manifest: Optional[Mapping[str, Any]]) -> None:
    """Require ``principal`` to own the archive, when ownership is recorded.

    An archive declares ownership via the ``owner`` field of its manifest. An
    archive with no recorded owner is treated as unowned and exportable by any
    authorized pro caller.
    """
    owner = manifest.get("owner") if isinstance(manifest, Mapping) else None
    if owner in (None, ""):
        return
    if str(owner) != str(principal):
        raise ExportError(403, "ownership_denied", "you are not the owner of this archive")


def _read_manifest(out: Path) -> Optional[Dict[str, Any]]:
    manifest_path = out / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _load_index_rows(out: Path) -> List[Dict[str, Any]]:
    index_path = out / "index.jsonl"
    rows: List[Dict[str, Any]] = []
    if not index_path.exists():
        return rows
    with index_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _load_index_summary(out: Path) -> Optional[Dict[str, Any]]:
    summary_path = out / "index-summary.json"
    if not summary_path.exists():
        return None
    try:
        loaded = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _iter_ocr_sidecars(out: Path):
    """Yield per-capture sidecar JSON files (everything but pipeline files)."""
    for sidecar in sorted(out.glob("*.json")):
        if sidecar.name in _NON_SIDECAR_NAMES:
            continue
        if sidecar.name.endswith(".backup.json"):
            continue
        if sidecar.is_file():
            yield sidecar


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def render_csv(rows: List[Dict[str, Any]]) -> bytes:
    """Flatten index rows into CSV bytes with a stable column ordering."""
    all_keys = set()
    for row in rows:
        all_keys.update(row.keys())
    columns = [key for key in _CSV_PREFERRED_COLUMNS if key in all_keys]
    columns += sorted(all_keys.difference(columns))

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_csv_cell(row.get(column)) for column in columns])
    return buffer.getvalue().encode("utf-8")


def render_zip(out: Path, manifest: Optional[Dict[str, Any]]) -> bytes:
    """Bundle ``manifest.json`` and every OCR sidecar into a zip archive."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest or {}, indent=2, sort_keys=True),
        )
        for sidecar in _iter_ocr_sidecars(out):
            try:
                archive.writestr(f"sidecars/{sidecar.name}", sidecar.read_bytes())
            except OSError:
                continue
    return buffer.getvalue()


def render_json(
    out: Path,
    manifest: Optional[Dict[str, Any]],
    rows: List[Dict[str, Any]],
) -> bytes:
    """Assemble the full archive (manifest + index + summary) as one document."""
    sidecar_count = sum(1 for _ in _iter_ocr_sidecars(out))
    document = {
        "format": "json",
        "owner": (manifest or {}).get("owner"),
        "manifest": manifest or {},
        "index": rows,
        "index_summary": _load_index_summary(out) or {},
        "counts": {"index_rows": len(rows), "sidecars": sidecar_count},
    }
    return json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")


def export_filename(fmt: str, extension: str) -> str:
    return f"{BRAND_NAME}-export.{extension}"


def build_export(
    fmt: str,
    out: Path,
    *,
    token: str,
    env: Optional[Mapping[str, str]] = None,
) -> Tuple[bytes, str, str]:
    """Authorize and render an export, returning ``(content, content_type, filename)``.

    Raises :class:`ExportError` for an unknown format, a caller that is not on
    the pro tier, or a caller that does not own the archive.
    """
    normalized = str(fmt or "").strip().lower()
    spec = EXPORT_FORMATS.get(normalized)
    if spec is None:
        raise ExportError(
            404,
            "unknown_format",
            f"unknown export format '{fmt}'; expected one of: "
            + ", ".join(sorted(EXPORT_FORMATS)),
        )
    content_type, extension = spec

    principal = authorize_pro(token, load_pro_tokens(env))
    manifest = _read_manifest(out)
    check_ownership(principal, manifest)

    if normalized == "csv":
        content = render_csv(_load_index_rows(out))
    elif normalized == "zip":
        content = render_zip(out, manifest)
    else:
        content = render_json(out, manifest, _load_index_rows(out))

    return content, content_type, export_filename(normalized, extension)
