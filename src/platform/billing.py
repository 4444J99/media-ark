"""Subscription billing records and Stripe webhook application hooks."""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure the `media_ark` brand module is importable when this file is
# imported as `src.platform.billing` from the repository checkout.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from media_ark import BRAND_DATA_DIR, env_key  # noqa: E402


VALID_TIERS = {"free", "pro"}
TIER_QUOTAS = {
    "free": 1_000,
    "pro": 100_000,
}

_UNSET = object()


class BillingError(ValueError):
    """Raised when a subscription mutation or webhook payload is invalid."""

    error = "billing_error"


class BillingNotFoundError(BillingError):
    error = "subscription_not_found"


class BillingConflictError(BillingError):
    error = "subscription_conflict"


@dataclass(frozen=True)
class SubscriptionRecord:
    user_id: int
    tier: str
    stripe_customer_id: Optional[str]
    renewal: Optional[str]
    auto_renew: bool
    quota: int
    created_at: str
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "tier": self.tier,
            "stripe_customer_id": self.stripe_customer_id,
            "renewal": self.renewal,
            "auto_renew": self.auto_renew,
            "quota": self.quota,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def default_billing_db_path() -> Path:
    raw = os.environ.get(env_key("BILLING_DB"), "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / BRAND_DATA_DIR / "billing.db").resolve()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _chmod_private(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def coerce_user_id(value: Any) -> int:
    try:
        user_id = int(value)
    except (TypeError, ValueError) as exc:
        raise BillingError("user_id must be an integer") from exc
    if user_id <= 0:
        raise BillingError("user_id must be greater than 0")
    return user_id


def normalize_tier(value: Any) -> str:
    tier = str(value or "free").strip().lower()
    if tier not in VALID_TIERS:
        raise BillingError(f"tier must be one of: {', '.join(sorted(VALID_TIERS))}")
    return tier


def quota_for_tier(tier: Any) -> int:
    return TIER_QUOTAS[normalize_tier(tier)]


def default_auto_renew_for_tier(tier: Any) -> bool:
    return normalize_tier(tier) != "free"


def coerce_quota(value: Any, *, tier: Any = "free") -> int:
    if value in (None, ""):
        return quota_for_tier(tier)
    try:
        quota = int(value)
    except (TypeError, ValueError) as exc:
        raise BillingError("quota must be an integer") from exc
    if quota < 0:
        raise BillingError("quota must be >= 0")
    return quota


def normalize_stripe_customer_id(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    customer_id = str(value).strip()
    if not customer_id:
        return None
    if "\x00" in customer_id:
        raise BillingError("stripe_customer_id contains a null byte")
    if len(customer_id) > 255:
        raise BillingError("stripe_customer_id must be <= 255 characters")
    return customer_id


def normalize_renewal(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        renewal = value
        if renewal.tzinfo is None:
            renewal = renewal.replace(tzinfo=timezone.utc)
        return renewal.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    text = str(value).strip()
    if not text:
        return None
    if "\x00" in text:
        raise BillingError("renewal contains a null byte")
    if len(text) > 128:
        raise BillingError("renewal must be <= 128 characters")
    return text


def _stripe_timestamp_to_iso(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return normalize_renewal(value)
    return datetime.fromtimestamp(timestamp, timezone.utc).replace(
        microsecond=0
    ).isoformat()


class BillingStore:
    """SQLite-backed subscription record store.

    The billing DB is intentionally separate from the auth DB so hosted
    billing state can be moved or replicated without changing local user
    authentication records.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path or default_billing_db_path()).expanduser().resolve()
        self._schema_ready = False
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        _chmod_private(self.db_path.parent, 0o700)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        self._ensure_schema(connection)
        _chmod_private(self.db_path, 0o600)
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        if self._schema_ready:
            return
        with self._lock:
            if self._schema_ready:
                return
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    user_id INTEGER PRIMARY KEY,
                    tier TEXT NOT NULL,
                    stripe_customer_id TEXT UNIQUE,
                    renewal TEXT,
                    auto_renew INTEGER NOT NULL,
                    quota INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_subscriptions_tier
                    ON subscriptions(tier);
                CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_customer_id
                    ON subscriptions(stripe_customer_id);
                """
            )
            connection.commit()
            self._schema_ready = True

    def _record_from_row(self, row: sqlite3.Row) -> SubscriptionRecord:
        return SubscriptionRecord(
            user_id=int(row["user_id"]),
            tier=str(row["tier"]),
            stripe_customer_id=(
                str(row["stripe_customer_id"])
                if row["stripe_customer_id"] is not None
                else None
            ),
            renewal=str(row["renewal"]) if row["renewal"] is not None else None,
            auto_renew=bool(row["auto_renew"]),
            quota=int(row["quota"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def create(
        self,
        user_id: Any,
        *,
        tier: Any = "free",
        stripe_customer_id: Any = None,
        renewal: Any = None,
        auto_renew: Any = None,
        quota: Any = None,
    ) -> SubscriptionRecord:
        normalized_user_id = coerce_user_id(user_id)
        normalized_tier = normalize_tier(tier)
        normalized_quota = coerce_quota(quota, tier=normalized_tier)
        normalized_auto_renew = _coerce_bool(
            auto_renew, default=default_auto_renew_for_tier(normalized_tier)
        )
        now = _utc_now()

        with self._connection() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO subscriptions (
                        user_id, tier, stripe_customer_id, renewal, auto_renew,
                        quota, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_user_id,
                        normalized_tier,
                        normalize_stripe_customer_id(stripe_customer_id),
                        normalize_renewal(renewal),
                        1 if normalized_auto_renew else 0,
                        normalized_quota,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise BillingConflictError(
                    "subscription already exists or customer is already linked"
                ) from exc
        record = self.get(normalized_user_id)
        if record is None:
            raise BillingError("subscription create did not persist")
        return record

    def get(self, user_id: Any) -> Optional[SubscriptionRecord]:
        normalized_user_id = coerce_user_id(user_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM subscriptions WHERE user_id = ?",
                (normalized_user_id,),
            ).fetchone()
        return self._record_from_row(row) if row is not None else None

    def get_by_stripe_customer_id(
        self, stripe_customer_id: Any
    ) -> Optional[SubscriptionRecord]:
        customer_id = normalize_stripe_customer_id(stripe_customer_id)
        if customer_id is None:
            return None
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM subscriptions WHERE stripe_customer_id = ?",
                (customer_id,),
            ).fetchone()
        return self._record_from_row(row) if row is not None else None

    def list(self, *, limit: int = 100, offset: int = 0) -> List[SubscriptionRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM subscriptions
                ORDER BY user_id ASC
                LIMIT ? OFFSET ?
                """,
                (self._coerce_limit(limit), self._coerce_offset(offset)),
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def _coerce_limit(self, value: Any) -> int:
        try:
            limit = int(value)
        except (TypeError, ValueError) as exc:
            raise BillingError("limit must be an integer") from exc
        if limit < 0:
            raise BillingError("limit must be >= 0")
        return limit

    def _coerce_offset(self, value: Any) -> int:
        try:
            offset = int(value)
        except (TypeError, ValueError) as exc:
            raise BillingError("offset must be an integer") from exc
        if offset < 0:
            raise BillingError("offset must be >= 0")
        return offset

    def update(
        self,
        user_id: Any,
        *,
        tier: Any = _UNSET,
        stripe_customer_id: Any = _UNSET,
        renewal: Any = _UNSET,
        auto_renew: Any = _UNSET,
        quota: Any = _UNSET,
    ) -> SubscriptionRecord:
        normalized_user_id = coerce_user_id(user_id)
        current = self.get(normalized_user_id)
        if current is None:
            raise BillingNotFoundError("subscription not found")

        next_tier = current.tier if tier is _UNSET else normalize_tier(tier)
        next_quota = (
            quota_for_tier(next_tier)
            if quota is _UNSET and tier is not _UNSET
            else current.quota
            if quota is _UNSET
            else coerce_quota(quota, tier=next_tier)
        )
        values = {
            "tier": next_tier,
            "stripe_customer_id": current.stripe_customer_id
            if stripe_customer_id is _UNSET
            else normalize_stripe_customer_id(stripe_customer_id),
            "renewal": current.renewal
            if renewal is _UNSET
            else normalize_renewal(renewal),
            "auto_renew": current.auto_renew
            if auto_renew is _UNSET
            else _coerce_bool(auto_renew, default=current.auto_renew),
            "quota": next_quota,
            "updated_at": _utc_now(),
        }

        with self._connection() as connection:
            try:
                connection.execute(
                    """
                    UPDATE subscriptions
                    SET tier = ?,
                        stripe_customer_id = ?,
                        renewal = ?,
                        auto_renew = ?,
                        quota = ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        values["tier"],
                        values["stripe_customer_id"],
                        values["renewal"],
                        1 if values["auto_renew"] else 0,
                        values["quota"],
                        values["updated_at"],
                        normalized_user_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise BillingConflictError("customer is already linked") from exc

        record = self.get(normalized_user_id)
        if record is None:
            raise BillingNotFoundError("subscription not found")
        return record

    def delete(self, user_id: Any) -> bool:
        normalized_user_id = coerce_user_id(user_id)
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM subscriptions WHERE user_id = ?", (normalized_user_id,)
            )
        return cursor.rowcount > 0

    def upsert(
        self,
        user_id: Any,
        *,
        tier: Any = "free",
        stripe_customer_id: Any = None,
        renewal: Any = None,
        auto_renew: Any = None,
        quota: Any = None,
    ) -> SubscriptionRecord:
        normalized_user_id = coerce_user_id(user_id)
        current = self.get(normalized_user_id)
        if current is None:
            return self.create(
                normalized_user_id,
                tier=tier,
                stripe_customer_id=stripe_customer_id,
                renewal=renewal,
                auto_renew=auto_renew,
                quota=quota,
            )
        return self.update(
            normalized_user_id,
            tier=tier,
            stripe_customer_id=stripe_customer_id,
            renewal=renewal,
            auto_renew=auto_renew,
            quota=quota,
        )

    def apply_stripe_webhook(
        self, event: Mapping[str, Any]
    ) -> Optional[SubscriptionRecord]:
        update = stripe_webhook_update(event, self)
        if update is None:
            return None
        return self.upsert(**update)

    def create_subscription(self, user_id: Any, **kwargs: Any) -> SubscriptionRecord:
        return self.create(user_id, **kwargs)

    def get_subscription(self, user_id: Any) -> Optional[SubscriptionRecord]:
        return self.get(user_id)

    def update_subscription(self, user_id: Any, **kwargs: Any) -> SubscriptionRecord:
        return self.update(user_id, **kwargs)

    def delete_subscription(self, user_id: Any) -> bool:
        return self.delete(user_id)

    def list_subscriptions(self, **kwargs: Any) -> List[SubscriptionRecord]:
        return self.list(**kwargs)


SubscriptionStore = BillingStore


def _event_object(event: Mapping[str, Any]) -> Dict[str, Any]:
    return _as_dict(_as_dict(event.get("data")).get("object"))


def _metadata_sources(obj: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    metadata = obj.get("metadata")
    if isinstance(metadata, Mapping):
        yield metadata

    subscription_details = _as_dict(obj.get("subscription_details"))
    metadata = subscription_details.get("metadata")
    if isinstance(metadata, Mapping):
        yield metadata

    price = _as_dict(obj.get("price"))
    metadata = price.get("metadata")
    if isinstance(metadata, Mapping):
        yield metadata

    for item in _as_dict(obj.get("items")).get("data", []) or []:
        item_dict = _as_dict(item)
        metadata = item_dict.get("metadata")
        if isinstance(metadata, Mapping):
            yield metadata
        price = _as_dict(item_dict.get("price"))
        metadata = price.get("metadata")
        if isinstance(metadata, Mapping):
            yield metadata

    for line in _as_dict(obj.get("lines")).get("data", []) or []:
        line_dict = _as_dict(line)
        metadata = line_dict.get("metadata")
        if isinstance(metadata, Mapping):
            yield metadata
        price = _as_dict(line_dict.get("price"))
        metadata = price.get("metadata")
        if isinstance(metadata, Mapping):
            yield metadata


def _first_metadata_value(
    obj: Mapping[str, Any], keys: tuple[str, ...]
) -> Optional[Any]:
    for metadata in _metadata_sources(obj):
        for key in keys:
            value = metadata.get(key)
            if value not in (None, ""):
                return value
    return None


def _stripe_customer_id(obj: Mapping[str, Any]) -> Optional[str]:
    customer = obj.get("customer") or obj.get("customer_id") or obj.get(
        "stripe_customer_id"
    )
    if isinstance(customer, Mapping):
        customer = customer.get("id")
    return normalize_stripe_customer_id(customer)


def _stripe_user_id(obj: Mapping[str, Any]) -> Optional[int]:
    value = _first_metadata_value(
        obj, ("user_id", "media_ark_user_id", "mediaArkUserId")
    )
    if value in (None, ""):
        value = obj.get("client_reference_id")
    if value in (None, ""):
        return None
    return coerce_user_id(value)


def _stripe_tier(obj: Mapping[str, Any], *, default: str) -> str:
    value = _first_metadata_value(obj, ("tier", "media_ark_tier", "mediaArkTier"))
    if value in (None, ""):
        value = _stripe_tier_from_price_fields(obj)
    if value in (None, ""):
        value = default
    return normalize_tier(value)


def _stripe_tier_from_price_fields(obj: Mapping[str, Any]) -> Optional[str]:
    values: List[Any] = []
    price = _as_dict(obj.get("price"))
    values.extend([price.get("lookup_key"), price.get("nickname"), price.get("id")])

    for item in _as_dict(obj.get("items")).get("data", []) or []:
        item_price = _as_dict(_as_dict(item).get("price"))
        values.extend(
            [
                item_price.get("lookup_key"),
                item_price.get("nickname"),
                item_price.get("id"),
            ]
        )

    for line in _as_dict(obj.get("lines")).get("data", []) or []:
        line_price = _as_dict(_as_dict(line).get("price"))
        values.extend(
            [
                line_price.get("lookup_key"),
                line_price.get("nickname"),
                line_price.get("id"),
            ]
        )

    for value in values:
        normalized = str(value or "").strip().lower()
        if normalized == "pro" or "pro" in normalized:
            return "pro"
        if normalized == "free" or "free" in normalized:
            return "free"
    return None


def _stripe_quota(obj: Mapping[str, Any], *, tier: str) -> int:
    value = _first_metadata_value(
        obj, ("quota", "media_ark_quota", "mediaArkQuota")
    )
    return coerce_quota(value, tier=tier)


def _stripe_renewal(obj: Mapping[str, Any]) -> Optional[str]:
    for key in ("current_period_end", "renewal", "expires_at", "trial_end"):
        value = obj.get(key)
        if value not in (None, ""):
            return _stripe_timestamp_to_iso(value)

    for line in _as_dict(obj.get("lines")).get("data", []) or []:
        period = _as_dict(_as_dict(line).get("period"))
        value = period.get("end")
        if value not in (None, ""):
            return _stripe_timestamp_to_iso(value)

    return None


def _stripe_auto_renew(
    obj: Mapping[str, Any], *, event_type: str, default: bool
) -> bool:
    status = str(obj.get("status", "") or "").lower()
    if event_type in {"customer.subscription.deleted", "invoice.payment_failed"}:
        return False
    if status in {"canceled", "incomplete_expired", "unpaid"}:
        return False
    if "cancel_at_period_end" in obj:
        return not _coerce_bool(obj.get("cancel_at_period_end"), default=False)
    return default


def stripe_webhook_update(
    event: Mapping[str, Any], store: Optional[BillingStore] = None
) -> Optional[Dict[str, Any]]:
    """Translate a Stripe event payload into a subscription upsert.

    The hook expects Stripe metadata to contain `user_id` for new customers.
    Existing customers can be resolved by `stripe_customer_id` when a store is
    supplied. The function returns `None` for unsupported Stripe event types.
    """

    event_type = str(event.get("type", "") or "")
    obj = _event_object(event)
    if not event_type or not obj:
        raise BillingError("stripe webhook payload must include type and data.object")

    paid_events = {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "invoice.paid",
        "invoice.payment_succeeded",
    }
    downgrade_events = {
        "customer.subscription.deleted",
        "invoice.payment_failed",
    }
    if event_type not in paid_events | downgrade_events:
        return None

    customer_id = _stripe_customer_id(obj)
    existing = store.get_by_stripe_customer_id(customer_id) if store else None
    user_id = _stripe_user_id(obj) or (existing.user_id if existing else None)
    if user_id is None:
        raise BillingError("stripe webhook metadata must include user_id")

    if event_type in downgrade_events:
        tier = "free"
        auto_renew = False
    else:
        tier = _stripe_tier(obj, default=existing.tier if existing else "pro")
        auto_renew = _stripe_auto_renew(obj, event_type=event_type, default=True)

    return {
        "user_id": user_id,
        "tier": tier,
        "stripe_customer_id": customer_id
        if customer_id is not None
        else existing.stripe_customer_id
        if existing is not None
        else None,
        "renewal": _stripe_renewal(obj) or (existing.renewal if existing else None),
        "auto_renew": auto_renew,
        "quota": _stripe_quota(obj, tier=tier),
    }


def apply_stripe_webhook(
    event: Mapping[str, Any], store: Optional[BillingStore] = None
) -> Optional[SubscriptionRecord]:
    billing_store = store or BillingStore()
    return billing_store.apply_stripe_webhook(event)


__all__ = [
    "BillingConflictError",
    "BillingError",
    "BillingNotFoundError",
    "BillingStore",
    "SubscriptionRecord",
    "SubscriptionStore",
    "TIER_QUOTAS",
    "VALID_TIERS",
    "apply_stripe_webhook",
    "coerce_quota",
    "default_billing_db_path",
    "default_auto_renew_for_tier",
    "normalize_renewal",
    "normalize_stripe_customer_id",
    "normalize_tier",
    "quota_for_tier",
    "stripe_webhook_update",
]
