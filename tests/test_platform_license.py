"""Tests for offline MONETA licence verification (src/platform/license.py).

The vectors below were minted with Node WebCrypto (ECDSA P-256 / SHA-256)
in MONETA's exact token format -- base64url(JSON payload).base64url(raw r||s).
Verifying them here with a *different* implementation (pure-stdlib Python)
proves the cross-language interop: a licence MONETA signs is one media-ark
accepts, and nothing else is. Regenerate with the generator in the Phase-2
notes if MONETA's format ever changes -- a drift should break these tests.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from src.platform.license import (
    LicenseResult,
    load_license_pubkey,
    verify_license,
)

# --- static vectors (minted by MONETA-format Node WebCrypto) ----------------
PUBKEY = {
    "kty": "EC",
    "crv": "P-256",
    "x": "Kq6v66ZijZz9ZtwTJOIOLJZ8aXnUTb-1vLztXFWKqCU",
    "y": "3mMe7J8O-srtKKEuQzOhydY0Fj0R7ufy623noOUuvxQ",
}
ATTACKER_PUBKEY = {
    "kty": "EC",
    "crv": "P-256",
    "x": "sJciAO8n1TIjfR2Iz55PvGwZVujeYYUvL_5dP5Gvw3c",
    "y": "eS2cBsR26gKAViAavsuRfuVeRrNtpXi9hVRPYMmux4M",
}
NOW = 1782000000  # fixed reference instant the vectors were minted against
PRO_PERPETUAL = "eyJ0aWVyIjoicHJvIiwic3ViIjoiYnV5ZXJAZXhhbXBsZS5jb20ifQ.dPXQQGuEyithvp7xd7AYnl2X0HtZjP0ly9f5_2F62wuhXZgk_QJrUkoO0RbPVdWDktAkSpLkyySwHZMmGAi_ng"  # noqa: E501
PRO_FUTURE = "eyJ0aWVyIjoicHJvIiwic3ViIjoiYnV5ZXJAZXhhbXBsZS5jb20iLCJleHAiOjE4MTM1MzYwMDB9.x7o24VB2x9ystrfnn9cDH7wFhp75g75BZKzaX3_T_mqKvPGpThZPzOVPJcTAKaX8nECoD7sfZF_OneLBVrIpug"  # noqa: E501
PRO_EXPIRED = "eyJ0aWVyIjoicHJvIiwic3ViIjoiYnV5ZXJAZXhhbXBsZS5jb20iLCJleHAiOjE3ODE5OTk5OTB9.WOUGd1Z94Yy7JKz89BTyr36-8WtGKcbn4qx5SB11DeJD7dz5LEvDzH500mqO6jVdEXnY8bXxEIgyW8xzUT5rWQ"  # noqa: E501
FREE = "eyJ0aWVyIjoiZnJlZSJ9.BujuMcs1eta6owuw40-oksKaNul62Xwm0ABNkORw_frqDk2F8tpOD0k9Nb68aF4lY1tqBkiQEoxhg3dH7N5QoA"  # noqa: E501


class TestLicenseVerify(unittest.TestCase):
    def test_valid_pro_perpetual(self) -> None:
        result = verify_license(PRO_PERPETUAL, PUBKEY, now_s=NOW)
        self.assertTrue(result.valid)
        self.assertEqual(result.tier, "pro")
        self.assertEqual(result.payload["sub"], "buyer@example.com")

    def test_valid_pro_with_future_expiry(self) -> None:
        self.assertTrue(verify_license(PRO_FUTURE, PUBKEY, now_s=NOW).valid)

    def test_perpetual_never_expires(self) -> None:
        far = NOW + 100 * 365 * 86400
        self.assertTrue(verify_license(PRO_PERPETUAL, PUBKEY, now_s=far).valid)

    def test_future_licence_expires_after_its_exp(self) -> None:
        # PRO_FUTURE carries exp = NOW + 1yr; a moment past it must reject.
        result = verify_license(PRO_FUTURE, PUBKEY, now_s=NOW + 400 * 86400)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "expired")

    def test_expired_is_rejected(self) -> None:
        result = verify_license(PRO_EXPIRED, PUBKEY, now_s=NOW)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "expired")

    def test_free_tier_is_not_pro(self) -> None:
        result = verify_license(FREE, PUBKEY, now_s=NOW)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "not-pro")

    def test_wrong_key_fails_signature(self) -> None:
        result = verify_license(PRO_PERPETUAL, ATTACKER_PUBKEY, now_s=NOW)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "bad-signature")

    def test_tampered_signature_fails(self) -> None:
        payload_part, sig = PRO_PERPETUAL.split(".")
        flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
        result = verify_license(f"{payload_part}.{flipped}", PUBKEY, now_s=NOW)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "bad-signature")

    def test_forged_payload_reusing_signature_fails(self) -> None:
        # Take a real signature and staple it to an attacker-chosen "pro"
        # payload. The signature covers the payload bytes, so this must fail.
        _, sig = PRO_PERPETUAL.split(".")
        forged_payload = (
            base64.urlsafe_b64encode(
                json.dumps({"tier": "pro", "sub": "attacker"}).encode("utf-8")
            )
            .rstrip(b"=")
            .decode("ascii")
        )
        result = verify_license(f"{forged_payload}.{sig}", PUBKEY, now_s=NOW)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "bad-signature")

    def test_malformed_tokens(self) -> None:
        for bad in ["", "no-dot", "a.b.c", ".", "onlypayload.", ".onlysig"]:
            with self.subTest(token=bad):
                self.assertFalse(verify_license(bad, PUBKEY, now_s=NOW).valid)
        self.assertEqual(verify_license("x", PUBKEY, now_s=NOW).reason, "malformed")

    def test_non_string_token(self) -> None:
        self.assertFalse(verify_license(None, PUBKEY, now_s=NOW).valid)
        self.assertFalse(verify_license(123, PUBKEY, now_s=NOW).valid)

    def test_bad_key_shape(self) -> None:
        result = verify_license(PRO_PERPETUAL, {"kty": "RSA"}, now_s=NOW)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "bad-key")

    def test_off_curve_key_rejected(self) -> None:
        off = dict(PUBKEY, y="AAAA")  # y no longer satisfies the curve equation
        result = verify_license(PRO_PERPETUAL, off, now_s=NOW)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "bad-key")

    def test_returns_license_result(self) -> None:
        self.assertIsInstance(verify_license(FREE, PUBKEY, now_s=NOW), LicenseResult)


class TestLoadLicensePubkey(unittest.TestCase):
    def test_from_env_json(self) -> None:
        env = {"MEDIA_ARK_LICENSE_PUBKEY": json.dumps(PUBKEY)}
        self.assertEqual(load_license_pubkey(env), PUBKEY)

    def test_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "pub.jwk"
            path.write_text(json.dumps(PUBKEY), encoding="utf-8")
            env = {"MEDIA_ARK_LICENSE_PUBKEY_FILE": str(path)}
            self.assertEqual(load_license_pubkey(env), PUBKEY)

    def test_unconfigured_is_none(self) -> None:
        self.assertIsNone(load_license_pubkey({}))

    def test_garbage_is_none(self) -> None:
        self.assertIsNone(load_license_pubkey({"MEDIA_ARK_LICENSE_PUBKEY": "{not json"}))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_api(port: int, attempts: int = 30) -> None:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise AssertionError("api did not become ready")


def _auth_headers(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _post(url: str, payload: dict, token: str | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", **_auth_headers(token)},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, (json.loads(body) if body else {})


def _get(url: str, token: str | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(url, headers=_auth_headers(token))
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, (json.loads(body) if body else {})


class TestLicenseApiIntegration(unittest.TestCase):
    """POST /api/license upgrades the authenticated user's tier to pro."""

    def _server(self, root: Path, *, with_pubkey: bool):
        env = dict(os.environ)
        env["MEDIA_ARK_QUOTA_DB"] = str(root / "quota.json")
        env["MEDIA_ARK_USERS_DB"] = str(root / "users.db")
        env["MEDIA_ARK_USER_SANDBOX_ROOT"] = str(root / "sandboxes")
        if with_pubkey:
            env["MEDIA_ARK_LICENSE_PUBKEY"] = json.dumps(PUBKEY)
        else:
            env.pop("MEDIA_ARK_LICENSE_PUBKEY", None)
        port = _free_port()
        proc = subprocess.Popen(
            [sys.executable, "-m", "src.platform.api_server", "--host", "127.0.0.1", "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        return proc, port

    def _register(self, port: int) -> dict:
        status, body = _post(
            f"http://127.0.0.1:{port}/api/auth/register",
            {"username": "licensee", "password": "correct horse battery"},
        )
        self.assertEqual(status, 201, body)
        return body

    def test_valid_pro_licence_upgrades_tier(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            proc, port = self._server(Path(tmpdir), with_pubkey=True)
            try:
                _wait_for_api(port)
                token = self._register(port)["api_key"]
                status, body = _post(
                    f"http://127.0.0.1:{port}/api/license",
                    {"license": PRO_PERPETUAL},
                    token,
                )
                self.assertEqual(status, 200, body)
                self.assertTrue(body["ok"])
                self.assertEqual(body["tier"], "pro")
                # The upgrade is durable and visible on the quota meter.
                _, quota = _get(f"http://127.0.0.1:{port}/api/quota", token)
                self.assertEqual(quota["tier"], "pro")
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_free_licence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            proc, port = self._server(Path(tmpdir), with_pubkey=True)
            try:
                _wait_for_api(port)
                token = self._register(port)["api_key"]
                status, body = _post(
                    f"http://127.0.0.1:{port}/api/license", {"license": FREE}, token
                )
                self.assertEqual(status, 400, body)
                self.assertEqual(body["error"], "invalid_license")
                self.assertEqual(body["reason"], "not-pro")
                _, quota = _get(f"http://127.0.0.1:{port}/api/quota", token)
                self.assertEqual(quota["tier"], "free")
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_license_requires_bearer_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            proc, port = self._server(Path(tmpdir), with_pubkey=True)
            try:
                _wait_for_api(port)
                status, body = _post(
                    f"http://127.0.0.1:{port}/api/license", {"license": PRO_PERPETUAL}
                )
                self.assertEqual(status, 401, body)
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_unconfigured_build_reports_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            proc, port = self._server(Path(tmpdir), with_pubkey=False)
            try:
                _wait_for_api(port)
                token = self._register(port)["api_key"]
                status, body = _post(
                    f"http://127.0.0.1:{port}/api/license",
                    {"license": PRO_PERPETUAL},
                    token,
                )
                self.assertEqual(status, 503, body)
                self.assertEqual(body["error"], "license_verification_unavailable")
            finally:
                proc.terminate()
                proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
