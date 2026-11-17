"""Encrypted cloud-sync scaffold for the 'pro' tier (S3 / Cloudflare R2).

This module is a *scaffold*: it wires up the shape of an encrypt-before-upload
sync path without ever talking to a real bucket on import or in tests. The
pieces are:

* :func:`encrypt_before_upload` / :func:`decrypt_after_download` — a stub
  symmetric envelope so payloads are encrypted on the client *before* they
  would leave the machine. The transform here is a clearly-labelled
  placeholder (a SHA-256 keystream XOR), NOT production-grade cryptography;
  swapping in a real AEAD (e.g. AES-GCM via ``cryptography``) is the intended
  follow-up and is isolated to this one function pair.
* :func:`make_s3_client` — lazily constructs a boto3 S3 client pointed at the
  configured endpoint (R2 uses an S3-compatible endpoint), so ``boto3`` stays
  an optional dependency that is only imported when a real upload is attempted.
* :class:`CloudSyncClient` — the gate. Every entry point checks
  :func:`platform.config.pro_enabled` and refuses to act otherwise. Uploads
  default to ``dry_run=True`` and build a plan instead of making a network
  call, so the default code path is inert.

Nothing here issues a bucket call unless a caller explicitly passes
``dry_run=False`` against a configured, credentialed, pro-enabled client.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .config import SyncConfig, load_sync_config, pro_enabled

# Envelope header for the stub format: a magic marker + format version. Lets
# decrypt reject foreign blobs and gives a real AEAD swap-in a version to bump.
_MAGIC = b"MASYNC"
_VERSION = 1
_NONCE_LEN = 16
_HEADER_LEN = len(_MAGIC) + 1 + _NONCE_LEN


class SyncError(RuntimeError):
    """Base class for cloud-sync scaffold failures."""


class SyncDisabledError(SyncError):
    """Raised when a sync operation is attempted without the 'pro' tier."""


class SyncConfigError(SyncError):
    """Raised when sync is requested but the backend is not fully configured."""


def derive_key(passphrase: str, *, salt: bytes = b"media-ark-sync") -> bytes:
    """Derive a 32-byte key from a passphrase (PBKDF2-HMAC-SHA256).

    Used by the stub envelope so callers can key encryption from a secret
    string. The KDF is real; the envelope it feeds is the placeholder.
    """
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 200_000)


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """Deterministic SHA-256 counter keystream. Placeholder, not secure."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def encrypt_before_upload(
    data: bytes, *, key: bytes, nonce: Optional[bytes] = None
) -> bytes:
    """Encrypt ``data`` into a self-describing envelope before it leaves the host.

    STUB: this performs a keystream XOR, which is a placeholder for a real
    authenticated cipher. It exists so the upload path is encrypt-by-default;
    do not rely on it for confidentiality. Returns ``magic | version | nonce |
    ciphertext``.
    """
    if not key:
        raise SyncConfigError("encryption key is required")
    if nonce is None:
        nonce = os.urandom(_NONCE_LEN)
    if len(nonce) != _NONCE_LEN:
        raise SyncConfigError(f"nonce must be {_NONCE_LEN} bytes")
    stream = _keystream(key, nonce, len(data))
    ciphertext = bytes(b ^ s for b, s in zip(data, stream))
    return _MAGIC + bytes([_VERSION]) + nonce + ciphertext


def decrypt_after_download(blob: bytes, *, key: bytes) -> bytes:
    """Inverse of :func:`encrypt_before_upload`. STUB, see that function."""
    if not key:
        raise SyncConfigError("encryption key is required")
    if len(blob) < _HEADER_LEN or not blob.startswith(_MAGIC):
        raise SyncError("not a media-ark sync envelope")
    version = blob[len(_MAGIC)]
    if version != _VERSION:
        raise SyncError(f"unsupported sync envelope version: {version}")
    nonce = blob[len(_MAGIC) + 1 : _HEADER_LEN]
    ciphertext = blob[_HEADER_LEN:]
    stream = _keystream(key, nonce, len(ciphertext))
    return bytes(b ^ s for b, s in zip(ciphertext, stream))


def build_object_key(config: SyncConfig, local_path: Path) -> str:
    """Build the remote object key for ``local_path`` under the configured prefix."""
    name = local_path.name
    prefix = config.prefix.strip("/")
    return f"{prefix}/{name}" if prefix else name


def make_s3_client(config: SyncConfig) -> Any:
    """Lazily construct a boto3 S3 client for the configured S3/R2 endpoint.

    ``boto3`` is imported here, not at module load, so it stays optional. This
    is the only place that would establish a real connection; it is never
    called by the default (dry-run) path or by the unit tests.
    """
    if not config.is_configured:
        raise SyncConfigError("sync bucket is not configured")
    try:
        import boto3  # noqa: F401  (optional dependency, imported on demand)
    except ImportError as exc:  # pragma: no cover - depends on optional dep
        raise SyncConfigError(
            "boto3 is required for cloud sync; install the 'pro' extra"
        ) from exc

    kwargs: Dict[str, Any] = {"region_name": config.region}
    if config.endpoint_url:
        kwargs["endpoint_url"] = config.endpoint_url
    if config.has_credentials:
        kwargs["aws_access_key_id"] = config.access_key_id
        kwargs["aws_secret_access_key"] = config.secret_access_key
    return boto3.client("s3", **kwargs)  # pragma: no cover - needs network/creds


@dataclass
class SyncPlan:
    """A description of an upload that has not (yet) happened."""

    bucket: str
    object_key: str
    plaintext_bytes: int
    encrypted_bytes: int
    provider: str
    uploaded: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "bucket": self.bucket,
            "object_key": self.object_key,
            "plaintext_bytes": self.plaintext_bytes,
            "encrypted_bytes": self.encrypted_bytes,
            "provider": self.provider,
            "uploaded": self.uploaded,
        }


class CloudSyncClient:
    """Pro-gated client that encrypts before uploading to S3/R2.

    Construction and every operation require the 'pro' tier to be enabled. The
    boto3 client is built lazily and only when a non-dry-run upload runs.
    """

    def __init__(
        self, config: Optional[SyncConfig] = None, *, key: Optional[bytes] = None
    ) -> None:
        if not pro_enabled():
            raise SyncDisabledError(
                "cloud sync is a 'pro' feature; set MEDIA_ARK_PRO=1 to enable"
            )
        self.config = config or load_sync_config()
        self._key = key
        self._client: Any = None

    def _resolved_key(self, key: Optional[bytes]) -> bytes:
        resolved = key or self._key
        if not resolved:
            raise SyncConfigError("an encryption key is required to sync")
        return resolved

    def plan_upload(
        self, local_path: Path, *, data: Optional[bytes] = None, key: Optional[bytes] = None
    ) -> SyncPlan:
        """Encrypt and build an upload plan without making any network call."""
        if not self.config.is_configured:
            raise SyncConfigError("sync bucket is not configured")
        resolved_key = self._resolved_key(key)
        payload = data if data is not None else local_path.read_bytes()
        encrypted = encrypt_before_upload(payload, key=resolved_key)
        return SyncPlan(
            bucket=self.config.bucket,
            object_key=build_object_key(self.config, local_path),
            plaintext_bytes=len(payload),
            encrypted_bytes=len(encrypted),
            provider=self.config.provider,
        )

    def upload(
        self,
        local_path: Path,
        *,
        data: Optional[bytes] = None,
        key: Optional[bytes] = None,
        dry_run: bool = True,
    ) -> SyncPlan:
        """Encrypt and upload ``local_path``. Defaults to a dry run (no call).

        With ``dry_run=True`` (the default) this returns the plan and never
        touches the network. With ``dry_run=False`` it requires credentials,
        lazily builds the boto3 client, and performs a real ``put_object``.
        """
        plan = self.plan_upload(local_path, data=data, key=key)
        if dry_run:
            return plan
        if not self.config.has_credentials:
            raise SyncConfigError("credentials are required for a real upload")
        resolved_key = self._resolved_key(key)
        payload = data if data is not None else local_path.read_bytes()
        encrypted = encrypt_before_upload(payload, key=resolved_key)
        client = self._client or make_s3_client(self.config)
        self._client = client
        client.put_object(  # pragma: no cover - needs network/creds
            Bucket=self.config.bucket, Key=plan.object_key, Body=encrypted
        )
        plan.uploaded = True
        return plan


def sync_status(config: Optional[SyncConfig] = None) -> Dict[str, Any]:
    """Return a read-only summary of cloud-sync state, safe to expose anywhere.

    Never includes secrets and never connects. Used to surface sync state on
    the platform status endpoint.
    """
    cfg = config or load_sync_config()
    return {
        "enabled": pro_enabled(),
        "configured": cfg.is_configured,
        "has_credentials": cfg.has_credentials,
        "bucket": cfg.bucket,
        "endpoint": cfg.endpoint_url,
        "provider": cfg.provider,
    }
