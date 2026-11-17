"""Stripe Checkout and webhook helpers for platform billing."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

# Keep this module importable both as `src.platform.stripe_client` from the
# checkout tree and as `platform.stripe_client` after package installation.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from media_ark import env_key  # noqa: E402


DEFAULT_CHECKOUT_MODE = "subscription"
DEFAULT_WEBHOOK_TOLERANCE_SECONDS = 300
_TIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


class StripeClientError(Exception):
    """Base error for Stripe platform integration failures."""


class StripeConfigurationError(StripeClientError):
    """Raised when Stripe credentials or tier mappings are missing or invalid."""


class StripeCheckoutError(StripeClientError):
    """Raised when Stripe does not return a usable Checkout Session."""


class StripeWebhookSignatureError(StripeClientError):
    """Raised when a webhook signature is missing, stale, or invalid."""


class StripeWebhookPayloadError(StripeClientError):
    """Raised when a signature-valid webhook body is not valid JSON."""


def normalize_tier(tier: str) -> str:
    """Normalize and validate an external plan tier identifier."""

    normalized = str(tier or "").strip().lower()
    if not normalized:
        raise StripeConfigurationError("tier is required")
    if not _TIER_PATTERN.fullmatch(normalized):
        raise StripeConfigurationError(
            "tier may contain only letters, numbers, dot, underscore, colon, and dash"
        )
    return normalized


def _parse_price_id_mapping(raw: str) -> Dict[str, str]:
    text = raw.strip()
    if not text:
        return {}

    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StripeConfigurationError(
                f"{env_key('STRIPE_PRICE_IDS')} must be valid JSON"
            ) from exc
        if not isinstance(parsed, dict):
            raise StripeConfigurationError(
                f"{env_key('STRIPE_PRICE_IDS')} JSON must be an object"
            )
        items = parsed.items()
    else:
        pairs = []
        for item in re.split(r"[\n,;]+", text):
            part = item.strip()
            if not part:
                continue
            if "=" in part:
                key, value = part.split("=", 1)
            elif ":" in part:
                key, value = part.split(":", 1)
            else:
                raise StripeConfigurationError(
                    f"{env_key('STRIPE_PRICE_IDS')} entries must be tier=price_id"
                )
            pairs.append((key, value))
        items = pairs

    mapping: Dict[str, str] = {}
    for key, value in items:
        tier = normalize_tier(str(key))
        price_id = str(value or "").strip()
        if not price_id:
            raise StripeConfigurationError(f"price id for tier {tier!r} is required")
        mapping[tier] = price_id
    return mapping


def load_tier_price_ids(
    environ: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """Load tier-to-Stripe-price mappings from environment variables.

    Supported formats:
    - MEDIA_ARK_STRIPE_PRICE_IDS='{"pro":"price_..."}'
    - MEDIA_ARK_STRIPE_PRICE_IDS='pro=price_...,team=price_...'
    - MEDIA_ARK_STRIPE_PRICE_PRO='price_...'
    - MEDIA_ARK_STRIPE_PRICE_ID_PRO='price_...'
    - MEDIA_ARK_STRIPE_PRO_PRICE_ID='price_...'
    """

    env = os.environ if environ is None else environ
    mapping = _parse_price_id_mapping(env.get(env_key("STRIPE_PRICE_IDS"), ""))

    prefix_patterns = (
        (f"{env_key('STRIPE_PRICE_ID')}_", ""),
        (f"{env_key('STRIPE_PRICE')}_", ""),
        (f"{env_key('STRIPE')}_", "_PRICE_ID"),
    )
    for key, value in env.items():
        raw_value = str(value or "").strip()
        if not raw_value:
            continue
        for prefix, suffix in prefix_patterns:
            if not key.startswith(prefix):
                continue
            tier_part = key[len(prefix) :]
            if suffix:
                if not tier_part.endswith(suffix):
                    continue
                tier_part = tier_part[: -len(suffix)]
            if not tier_part:
                continue
            normalized = normalize_tier(tier_part.lower())
            mapping[normalized] = raw_value
            mapping.setdefault(normalized.replace("_", "-"), raw_value)
            break

    return mapping


def price_id_for_tier(
    tier: str,
    price_ids: Optional[Mapping[str, str]] = None,
) -> str:
    normalized = normalize_tier(tier)
    raw_mapping = load_tier_price_ids() if price_ids is None else dict(price_ids)
    mapping = {
        normalize_tier(key): str(value).strip() for key, value in raw_mapping.items()
    }
    price_id = mapping.get(normalized)
    if not price_id:
        configured = ", ".join(sorted(mapping)) or "none"
        raise StripeConfigurationError(
            f"no Stripe price id configured for tier {normalized!r}; configured tiers: {configured}"
        )
    return price_id


def _env_value(name: str, fallback_name: str = "") -> str:
    value = os.environ.get(name, "").strip()
    if value or not fallback_name:
        return value
    return os.environ.get(fallback_name, "").strip()


def _checkout_mode(mode: Optional[str]) -> str:
    selected = str(
        mode
        or _env_value(env_key("STRIPE_CHECKOUT_MODE"), "STRIPE_CHECKOUT_MODE")
        or DEFAULT_CHECKOUT_MODE
    ).strip().lower()
    if selected not in {"payment", "subscription"}:
        raise StripeConfigurationError("checkout mode must be payment or subscription")
    return selected


def build_checkout_session_params(
    tier: str,
    success_url: str,
    cancel_url: str,
    *,
    price_ids: Optional[Mapping[str, str]] = None,
    quantity: int = 1,
    mode: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    client_reference_id: str = "",
    customer_email: str = "",
    allow_promotion_codes: Optional[bool] = None,
    automatic_tax: Optional[bool] = None,
    extra_params: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the parameters used to create a Stripe Checkout Session."""

    normalized_tier = normalize_tier(tier)
    if not str(success_url or "").strip():
        raise StripeConfigurationError("success_url is required")
    if not str(cancel_url or "").strip():
        raise StripeConfigurationError("cancel_url is required")
    try:
        line_quantity = int(quantity)
    except (TypeError, ValueError) as exc:
        raise StripeConfigurationError("quantity must be an integer") from exc
    if line_quantity < 1:
        raise StripeConfigurationError("quantity must be >= 1")

    session_metadata = {"tier": normalized_tier}
    for key, value in (metadata or {}).items():
        if value is None:
            continue
        session_metadata[str(key)] = str(value)

    params: Dict[str, Any] = {
        "mode": _checkout_mode(mode),
        "success_url": str(success_url).strip(),
        "cancel_url": str(cancel_url).strip(),
        "line_items": [
            {
                "price": price_id_for_tier(normalized_tier, price_ids),
                "quantity": line_quantity,
            }
        ],
        "metadata": session_metadata,
    }
    if client_reference_id:
        params["client_reference_id"] = str(client_reference_id)
    if customer_email:
        params["customer_email"] = str(customer_email)
    if allow_promotion_codes is not None:
        params["allow_promotion_codes"] = bool(allow_promotion_codes)
    if automatic_tax is not None:
        params["automatic_tax"] = {"enabled": bool(automatic_tax)}
    if extra_params:
        params.update(dict(extra_params))
    return params


def _load_stripe_module(stripe_module: Any = None) -> Any:
    if stripe_module is not None:
        return stripe_module
    try:
        import stripe  # type: ignore
    except ImportError as exc:
        raise StripeConfigurationError(
            "stripe package is required to create live Checkout Sessions"
        ) from exc
    return stripe


def _nested_attr(root: Any, dotted_path: str) -> Any:
    current = root
    for part in dotted_path.split("."):
        current = getattr(current, part, None)
        if current is None:
            return None
    return current


def _create_session_with_stripe(
    stripe_module: Any,
    api_key: str,
    params: Mapping[str, Any],
) -> Any:
    if api_key and hasattr(stripe_module, "api_key"):
        stripe_module.api_key = api_key

    old_style_create = _nested_attr(stripe_module, "checkout.Session.create")
    if callable(old_style_create):
        return old_style_create(**dict(params))

    client_class = getattr(stripe_module, "StripeClient", None)
    if client_class is not None:
        client = client_class(api_key)
        for path in ("checkout.sessions.create", "v1.checkout.sessions.create"):
            create = _nested_attr(client, path)
            if callable(create):
                return create(**dict(params))

    raise StripeConfigurationError(
        "stripe package does not expose Checkout Session creation"
    )


def _session_value(session: Any, key: str) -> Any:
    if isinstance(session, Mapping):
        return session.get(key)
    return getattr(session, key, None)


def create_checkout_session(
    tier: str,
    success_url: str,
    cancel_url: str,
    *,
    price_ids: Optional[Mapping[str, str]] = None,
    quantity: int = 1,
    mode: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    client_reference_id: str = "",
    customer_email: str = "",
    allow_promotion_codes: Optional[bool] = None,
    automatic_tax: Optional[bool] = None,
    extra_params: Optional[Mapping[str, Any]] = None,
    api_key: str = "",
    stripe_module: Any = None,
) -> str:
    """Create a Stripe Checkout Session and return its hosted redirect URL."""

    resolved_api_key = (
        str(api_key or "").strip()
        or _env_value(env_key("STRIPE_SECRET_KEY"), "STRIPE_SECRET_KEY")
    )
    if not resolved_api_key and stripe_module is None:
        raise StripeConfigurationError(f"{env_key('STRIPE_SECRET_KEY')} is required")

    params = build_checkout_session_params(
        tier,
        success_url,
        cancel_url,
        price_ids=price_ids,
        quantity=quantity,
        mode=mode,
        metadata=metadata,
        client_reference_id=client_reference_id,
        customer_email=customer_email,
        allow_promotion_codes=allow_promotion_codes,
        automatic_tax=automatic_tax,
        extra_params=extra_params,
    )
    stripe = _load_stripe_module(stripe_module)
    session = _create_session_with_stripe(stripe, resolved_api_key, params)
    url = str(_session_value(session, "url") or "").strip()
    if not url:
        session_id = str(_session_value(session, "id") or "unknown")
        raise StripeCheckoutError(
            f"Stripe Checkout Session {session_id!r} did not include a redirect URL"
        )
    return url


def _coerce_payload_bytes(payload: bytes | bytearray | memoryview | str) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, bytearray):
        return bytes(payload)
    if isinstance(payload, memoryview):
        return payload.tobytes()
    return str(payload).encode("utf-8")


def _parse_signature_header(signature_header: str) -> tuple[int, list[str]]:
    if not signature_header:
        raise StripeWebhookSignatureError("Stripe-Signature header is required")

    timestamp = ""
    signatures: list[str] = []
    for item in signature_header.split(","):
        key, separator, value = item.strip().partition("=")
        if not separator:
            continue
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if not timestamp:
        raise StripeWebhookSignatureError("Stripe-Signature header is missing t")
    if not signatures:
        raise StripeWebhookSignatureError("Stripe-Signature header is missing v1")
    try:
        parsed_timestamp = int(timestamp)
    except ValueError as exc:
        raise StripeWebhookSignatureError(
            "Stripe-Signature timestamp must be an integer"
        ) from exc
    return parsed_timestamp, signatures


def verify_webhook_signature(
    payload: bytes | bytearray | memoryview | str,
    signature_header: str,
    endpoint_secret: str = "",
    *,
    tolerance_seconds: Optional[int] = DEFAULT_WEBHOOK_TOLERANCE_SECONDS,
    now: Optional[float] = None,
) -> bool:
    """Validate a Stripe webhook signature header for the exact raw payload."""

    secret = str(endpoint_secret or "").strip() or _env_value(
        env_key("STRIPE_WEBHOOK_SECRET"), "STRIPE_WEBHOOK_SECRET"
    )
    if not secret:
        raise StripeConfigurationError(f"{env_key('STRIPE_WEBHOOK_SECRET')} is required")

    payload_bytes = _coerce_payload_bytes(payload)
    timestamp, signatures = _parse_signature_header(signature_header)
    current_time = time.time() if now is None else float(now)
    if tolerance_seconds is not None:
        tolerance = int(tolerance_seconds)
        if tolerance < 0:
            raise StripeConfigurationError("tolerance_seconds must be >= 0")
        if abs(current_time - timestamp) > tolerance:
            raise StripeWebhookSignatureError("Stripe-Signature timestamp is stale")

    signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
    expected = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    if not any(hmac.compare_digest(expected, signature) for signature in signatures):
        raise StripeWebhookSignatureError("Stripe-Signature v1 does not match payload")
    return True


def receive_webhook(
    payload: bytes | bytearray | memoryview | str,
    signature_header: str,
    endpoint_secret: str = "",
    *,
    tolerance_seconds: Optional[int] = DEFAULT_WEBHOOK_TOLERANCE_SECONDS,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Validate a Stripe webhook signature and return the parsed event payload."""

    payload_bytes = _coerce_payload_bytes(payload)
    verify_webhook_signature(
        payload_bytes,
        signature_header,
        endpoint_secret,
        tolerance_seconds=tolerance_seconds,
        now=now,
    )
    try:
        event = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StripeWebhookPayloadError("webhook payload must be valid JSON") from exc
    if not isinstance(event, dict):
        raise StripeWebhookPayloadError("webhook payload must be a JSON object")
    return event


@dataclass
class StripeWebhookReceiver:
    """Small callable receiver that validates Stripe signatures before dispatch."""

    endpoint_secret: str = ""
    tolerance_seconds: Optional[int] = DEFAULT_WEBHOOK_TOLERANCE_SECONDS
    handlers: Mapping[str, Callable[[Mapping[str, Any]], Any]] = field(
        default_factory=dict
    )
    clock: Callable[[], float] = time.time

    def receive(
        self,
        payload: bytes | bytearray | memoryview | str,
        signature_header: str,
    ) -> Dict[str, Any]:
        event = receive_webhook(
            payload,
            signature_header,
            self.endpoint_secret,
            tolerance_seconds=self.tolerance_seconds,
            now=self.clock(),
        )
        event_type = str(event.get("type", ""))
        handler = self.handlers.get(event_type)
        if handler is not None:
            handler(event)
        return event


__all__ = [
    "DEFAULT_CHECKOUT_MODE",
    "DEFAULT_WEBHOOK_TOLERANCE_SECONDS",
    "StripeCheckoutError",
    "StripeClientError",
    "StripeConfigurationError",
    "StripeWebhookPayloadError",
    "StripeWebhookReceiver",
    "StripeWebhookSignatureError",
    "build_checkout_session_params",
    "create_checkout_session",
    "load_tier_price_ids",
    "normalize_tier",
    "price_id_for_tier",
    "receive_webhook",
    "verify_webhook_signature",
]
