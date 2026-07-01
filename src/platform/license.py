"""Offline verification of MONETA-signed Pro licences -- pure stdlib.

MONETA (the fleet's sovereign cash rail; limen ``moneta/``) mints Pro
licences by signing a JSON payload with an ECDSA P-256 key it alone holds.
media-ark verifies them against the matching *public* key, fully offline --
no payment processor, no network round-trip. This mirrors
``moneta/src/license.ts`` and its ``verify-helper.ts`` byte for byte:

    token   = base64url(JSON.stringify(payload)) + '.' + base64url(rawSig)
    payload = {sub?, tier, exp?, features?}          (exp = unix seconds)
    rawSig  = IEEE-P1363 r||s (64 bytes), ECDSA over the UTF-8 bytes of the
              base64url payload string, hash SHA-256
    pubkey  = a P-256 JWK  ({kty:'EC', crv:'P-256', x, y})

Verification is standard ECDSA over NIST P-256 (secp256r1), implemented with
only ``hashlib`` + integer arithmetic so media-ark keeps its zero-dependency
footprint. The tradeoff for a ~150-line curve is a codebase that installs
nothing -- deliberate: the CI never pip-installs the app, and the whole
engine is stdlib. The permanent home of the pubkey is the product build's
config (``MEDIA_ARK_LICENSE_PUBKEY``); the key is public and safe to embed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

# Mirror the import-path shim used by config.py / quota.py so the brand
# module resolves when this file is loaded as `src.platform.license`.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from media_ark import env_key  # noqa: E402

# --- NIST P-256 (secp256r1) domain parameters ------------------------------
_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFC
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
_G = (_GX, _GY)

# An affine point is (x, y); the point at infinity is None.
_Point = Optional[tuple]


def _b64url_decode(data: str) -> bytes:
    """Decode base64url without requiring padding (JWT / WebCrypto style)."""

    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _b64url_to_int(data: str) -> int:
    return int.from_bytes(_b64url_decode(data), "big")


def _point_add(p1: _Point, p2: _Point) -> _Point:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    # P + (-P) = O (same x, opposite y).
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    if p1 == p2:
        # Point doubling. y1 != 0 for every P-256 point (no order-2 points).
        slope = (3 * x1 * x1 + _A) * pow(2 * y1, -1, _P) % _P
    else:
        # Distinct points with the same x are inverses, caught above, so
        # x2 - x1 is invertible here.
        slope = (y2 - y1) * pow((x2 - x1) % _P, -1, _P) % _P
    x3 = (slope * slope - x1 - x2) % _P
    y3 = (slope * (x1 - x3) - y1) % _P
    return (x3, y3)


def _scalar_mult(k: int, point: _Point) -> _Point:
    """Double-and-add: k * point over P-256."""

    result: _Point = None
    addend = point
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return result


def _pubkey_point(jwk: Mapping[str, Any]) -> tuple:
    """Parse a P-256 JWK into an on-curve public point, or raise ValueError."""

    if not isinstance(jwk, Mapping):
        raise ValueError("public key must be a JWK object")
    if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
        raise ValueError("unsupported key: expected an EC P-256 JWK")
    try:
        x = _b64url_to_int(str(jwk["x"]))
        y = _b64url_to_int(str(jwk["y"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("malformed JWK coordinates") from exc
    # Reject a point that is not actually on the curve (y^2 == x^3 + ax + b).
    if (y * y - (x * x * x + _A * x + _B)) % _P != 0:
        raise ValueError("public key point is not on P-256")
    return (x, y)


def _ecdsa_verify(message: bytes, r: int, s: int, pub: tuple) -> bool:
    """Verify an ECDSA/SHA-256 signature (r, s) over ``message`` under P-256."""

    if not (1 <= r < _N and 1 <= s < _N):
        return False
    # P-256 field and hash are both 256 bits, so no left-truncation is needed.
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    w = pow(s, -1, _N)
    u1 = (e * w) % _N
    u2 = (r * w) % _N
    point = _point_add(_scalar_mult(u1, _G), _scalar_mult(u2, pub))
    if point is None:
        return False
    return (point[0] % _N) == r


@dataclass
class LicenseResult:
    """Outcome of verifying a MONETA licence -- mirrors verify-helper.ts."""

    valid: bool
    tier: Optional[str] = None
    reason: Optional[str] = None
    payload: Optional[dict] = None


def verify_license(
    token: Any, pubkey_jwk: Mapping[str, Any], *, now_s: int
) -> LicenseResult:
    """Verify a MONETA-signed licence fully offline.

    Returns a :class:`LicenseResult`. ``valid`` is True only for a
    signature that checks out against ``pubkey_jwk`` AND is unexpired AND
    grants the ``pro`` tier -- the exact acceptance rule the exporter's
    ``verifySignedLicense`` uses. ``reason`` is one of ``malformed``,
    ``bad-key``, ``bad-signature``, ``expired`` or ``not-pro``.
    """

    if not isinstance(token, str) or token.count(".") != 1:
        return LicenseResult(False, reason="malformed")
    payload_part, sig_part = token.split(".")
    if not payload_part or not sig_part:
        return LicenseResult(False, reason="malformed")

    try:
        payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
        raw_sig = _b64url_decode(sig_part)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return LicenseResult(False, reason="malformed")
    if not isinstance(payload, dict):
        return LicenseResult(False, reason="malformed")
    if len(raw_sig) != 64:
        return LicenseResult(False, reason="malformed", payload=payload)

    try:
        pub = _pubkey_point(pubkey_jwk)
    except ValueError:
        return LicenseResult(False, reason="bad-key", payload=payload)

    r = int.from_bytes(raw_sig[:32], "big")
    s = int.from_bytes(raw_sig[32:], "big")
    if not _ecdsa_verify(payload_part.encode("utf-8"), r, s, pub):
        return LicenseResult(False, reason="bad-signature", payload=payload)

    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and not isinstance(exp, bool) and exp < now_s:
        return LicenseResult(False, reason="expired", payload=payload)
    if payload.get("tier") != "pro":
        return LicenseResult(False, reason="not-pro", payload=payload)
    return LicenseResult(True, tier="pro", payload=payload)


def load_license_pubkey(
    env: Optional[Mapping[str, str]] = None,
) -> Optional[dict]:
    """The MONETA public key this build verifies against, or ``None``.

    Reads ``MEDIA_ARK_LICENSE_PUBKEY`` (a JWK JSON string) or, failing that,
    ``MEDIA_ARK_LICENSE_PUBKEY_FILE`` (a path to one). The key is public and
    safe to embed in the product build. Returns ``None`` when unconfigured,
    so ``/api/license`` can report that Pro upgrades are unavailable rather
    than crash.
    """

    import os

    source = env if env is not None else os.environ
    raw = str(source.get(env_key("LICENSE_PUBKEY"), "") or "").strip()
    if not raw:
        path = str(source.get(env_key("LICENSE_PUBKEY_FILE"), "") or "").strip()
        if path:
            try:
                raw = Path(path).expanduser().read_text(encoding="utf-8").strip()
            except OSError:
                return None
    if not raw:
        return None
    try:
        jwk = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return jwk if isinstance(jwk, dict) else None
