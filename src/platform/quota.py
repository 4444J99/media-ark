"""Per-user quota tracking for the platform HTTP/MCP surface.

The platform is local-first, but the hosted deployment needs to bound
what a single user can consume. This module tracks two resources per
user:

* **storage** — the on-disk size of the user's archive, in bytes.
* **monthly calls** — API requests and OCR invocations made within the
  current calendar month. The two are counted separately for
  reporting but share a single monthly budget (the second number in
  each tier below).

Two tiers ship by default:

============  ==========  ==============
tier          storage     monthly calls
============  ==========  ==============
free          5 GB        1,000
pro           100 GB      50,000
============  ==========  ==============

Usage is persisted as a small JSON document (one entry per user) so it
survives server restarts. ``QuotaStore`` is safe to share across the
threads of ``ThreadingHTTPServer``: every read-modify-write is guarded
by a lock and committed with an atomic file replace.

When a consume call would cross a limit, ``QuotaExceeded`` is raised
*before* anything is recorded. The HTTP layer maps that to a ``429``
response (see ``api_server``).
"""

from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Mirror the import-path shim used by config.py / api_server.py so the
# brand module resolves when this file is loaded as `src.platform.quota`.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from media_ark import BRAND_DATA_DIR, env_key  # noqa: E402

GB = 1024**3


@dataclass(frozen=True)
class QuotaTier:
    """Limits for a single subscription tier."""

    name: str
    storage_bytes: int
    monthly_calls: int


TIERS: Dict[str, QuotaTier] = {
    "free": QuotaTier(name="free", storage_bytes=5 * GB, monthly_calls=1_000),
    "pro": QuotaTier(name="pro", storage_bytes=100 * GB, monthly_calls=50_000),
}

DEFAULT_TIER = "free"


class QuotaExceeded(Exception):
    """Raised when a consume call would push a user past their tier limit.

    Carries enough structured context for the caller to build a useful
    ``429`` payload without re-deriving anything.
    """

    def __init__(
        self,
        *,
        user: str,
        tier: str,
        resource: str,
        limit: int,
        used: int,
        requested: int,
    ) -> None:
        self.user = user
        self.tier = tier
        self.resource = resource
        self.limit = limit
        self.used = used
        self.requested = requested
        super().__init__(
            f"{tier} tier {resource} quota exceeded for user {user!r}: "
            f"{used} used + {requested} requested > {limit} limit"
        )

    def to_payload(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": "quota_exceeded",
            "resource": self.resource,
            "tier": self.tier,
            "limit": self.limit,
            "used": self.used,
            "requested": self.requested,
            "message": str(self),
        }


def resolve_tier(name: Any) -> QuotaTier:
    """Return the tier for ``name``, falling back to the free tier.

    Unknown or empty tier names degrade to ``free`` rather than raising;
    a mistyped header should not hand a user the pro budget, and it
    should not fail the request outright either.
    """

    key = str(name or "").strip().lower()
    return TIERS.get(key, TIERS[DEFAULT_TIER])


def current_period(now: Optional[datetime] = None) -> str:
    """Return the ``YYYY-MM`` bucket used for the monthly call counter."""

    moment = now or datetime.now(timezone.utc)
    return f"{moment.year:04d}-{moment.month:02d}"


def quota_db_path() -> Path:
    """Location of the persisted usage document.

    Honours ``MEDIA_ARK_QUOTA_DB`` for explicit placement; otherwise it
    lives alongside the rest of the runtime data under ``BRAND_DATA_DIR``.
    """

    raw = os.environ.get(env_key("QUOTA_DB"), "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / BRAND_DATA_DIR / "quota.json"


def directory_size(path: Path) -> int:
    """Total size in bytes of every regular file under ``path``.

    Returns ``0`` if the path does not exist. Broken symlinks and files
    that vanish mid-walk are skipped rather than raising.
    """

    root = Path(path)
    if not root.exists():
        return 0
    total = 0
    for entry in root.rglob("*"):
        try:
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


@dataclass
class Usage:
    """A single user's recorded usage."""

    tier: str = DEFAULT_TIER
    period: str = ""
    api_calls: int = 0
    ocr_calls: int = 0
    storage_bytes: int = 0

    @property
    def total_calls(self) -> int:
        return self.api_calls + self.ocr_calls

    def roll_period(self, period: str) -> None:
        """Reset the monthly counters when ``period`` has advanced."""

        if self.period != period:
            self.period = period
            self.api_calls = 0
            self.ocr_calls = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Usage":
        return cls(
            tier=str(data.get("tier", DEFAULT_TIER)),
            period=str(data.get("period", "")),
            api_calls=int(data.get("api_calls", 0)),
            ocr_calls=int(data.get("ocr_calls", 0)),
            storage_bytes=int(data.get("storage_bytes", 0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "period": self.period,
            "api_calls": self.api_calls,
            "ocr_calls": self.ocr_calls,
            "storage_bytes": self.storage_bytes,
        }


class QuotaStore:
    """Thread-safe, file-backed per-user quota ledger."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else quota_db_path()
        self._lock = threading.Lock()

    # -- persistence ---------------------------------------------------

    def _load(self) -> Dict[str, Usage]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        users = raw.get("users", {}) if isinstance(raw, dict) else {}
        result: Dict[str, Usage] = {}
        for user_id, data in users.items():
            if isinstance(data, dict):
                result[str(user_id)] = Usage.from_dict(data)
        return result

    def _save(self, users: Dict[str, Usage]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"users": {uid: u.to_dict() for uid, u in users.items()}}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    # -- public API ----------------------------------------------------

    def get_usage(self, user_id: str, *, now: Optional[datetime] = None) -> Usage:
        """Snapshot of ``user_id``'s usage, with the period rolled forward."""

        period = current_period(now)
        with self._lock:
            users = self._load()
            usage = users.get(user_id, Usage())
            usage.roll_period(period)
            return usage

    def set_tier(self, user_id: str, tier: str) -> None:
        resolved = resolve_tier(tier).name
        with self._lock:
            users = self._load()
            usage = users.get(user_id, Usage())
            usage.tier = resolved
            users[user_id] = usage
            self._save(users)

    def consume(
        self,
        user_id: str,
        *,
        tier: Optional[str] = None,
        api_calls: int = 0,
        ocr_calls: int = 0,
        storage_bytes: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> Usage:
        """Atomically check limits and record usage for ``user_id``.

        ``api_calls`` and ``ocr_calls`` are increments. ``storage_bytes``,
        when provided, replaces the recorded storage figure (the archive
        size is an absolute measurement, not a delta).

        Raises :class:`QuotaExceeded` before persisting anything if the
        request would cross a limit. The ``tier`` argument, when given,
        is recorded and used for limit lookup; otherwise the user's
        previously stored tier (or the free default) applies.
        """

        period = current_period(now)
        with self._lock:
            users = self._load()
            usage = users.get(user_id, Usage())
            usage.roll_period(period)
            if tier is not None:
                usage.tier = resolve_tier(tier).name
            limits = resolve_tier(usage.tier)

            prospective_calls = usage.total_calls + api_calls + ocr_calls
            if prospective_calls > limits.monthly_calls:
                raise QuotaExceeded(
                    user=user_id,
                    tier=limits.name,
                    resource="calls",
                    limit=limits.monthly_calls,
                    used=usage.total_calls,
                    requested=api_calls + ocr_calls,
                )

            prospective_storage = (
                usage.storage_bytes if storage_bytes is None else storage_bytes
            )
            if prospective_storage > limits.storage_bytes:
                raise QuotaExceeded(
                    user=user_id,
                    tier=limits.name,
                    resource="storage",
                    limit=limits.storage_bytes,
                    used=usage.storage_bytes,
                    requested=max(0, prospective_storage - usage.storage_bytes),
                )

            usage.api_calls += api_calls
            usage.ocr_calls += ocr_calls
            if storage_bytes is not None:
                usage.storage_bytes = storage_bytes
            users[user_id] = usage
            self._save(users)
            return usage

    def update_storage(
        self, user_id: str, storage_bytes: int, *, now: Optional[datetime] = None
    ) -> Usage:
        """Record an observed archive size without consuming any calls.

        Unlike :meth:`consume`, this never raises on an over-limit value:
        it reflects what is already on disk so the *next* request can be
        rejected. The bound is enforced at consume time, not here.
        """

        period = current_period(now)
        with self._lock:
            users = self._load()
            usage = users.get(user_id, Usage())
            usage.roll_period(period)
            usage.storage_bytes = max(0, int(storage_bytes))
            users[user_id] = usage
            self._save(users)
            return usage
