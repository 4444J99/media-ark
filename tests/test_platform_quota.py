from __future__ import annotations

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
from datetime import datetime, timezone
from pathlib import Path

from src.platform.quota import (
    GB,
    TIERS,
    QuotaExceeded,
    QuotaStore,
    Usage,
    current_period,
    directory_size,
    resolve_tier,
)


class TestQuotaStore(unittest.TestCase):
    def _store(self, tmpdir: str) -> QuotaStore:
        return QuotaStore(Path(tmpdir) / "quota.json")

    def test_consume_increments_separate_counters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.consume("alice", api_calls=1)
            store.consume("alice", ocr_calls=2)
            usage = store.get_usage("alice")
            self.assertEqual(usage.api_calls, 1)
            self.assertEqual(usage.ocr_calls, 2)
            self.assertEqual(usage.total_calls, 3)

    def test_calls_limit_enforced_against_combined_total(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            limit = TIERS["free"].monthly_calls
            # Burn the budget with api calls, then a single extra call (api
            # or ocr) must trip — the limit covers the combined total.
            store.consume("bob", api_calls=limit)
            with self.assertRaises(QuotaExceeded) as ctx:
                store.consume("bob", ocr_calls=1)
            self.assertEqual(ctx.exception.resource, "calls")
            self.assertEqual(ctx.exception.limit, limit)
            # The rejected call was not recorded.
            self.assertEqual(store.get_usage("bob").total_calls, limit)

    def test_storage_limit_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            with self.assertRaises(QuotaExceeded) as ctx:
                store.consume("carol", storage_bytes=5 * GB + 1)
            self.assertEqual(ctx.exception.resource, "storage")
            # Nothing recorded after a rejected storage check.
            self.assertEqual(store.get_usage("carol").storage_bytes, 0)
            # Exactly at the limit is allowed.
            store.consume("carol", storage_bytes=5 * GB)
            self.assertEqual(store.get_usage("carol").storage_bytes, 5 * GB)

    def test_pro_tier_has_higher_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            # Would exceed free, fine on pro.
            store.consume("dave", tier="pro", api_calls=TIERS["free"].monthly_calls + 1)
            store.consume("dave", tier="pro", storage_bytes=100 * GB)
            usage = store.get_usage("dave")
            self.assertEqual(usage.tier, "pro")
            self.assertEqual(usage.api_calls, TIERS["free"].monthly_calls + 1)

    def test_unknown_tier_falls_back_to_free(self) -> None:
        self.assertEqual(resolve_tier("enterprise").name, "free")
        self.assertEqual(resolve_tier("").name, "free")
        self.assertEqual(resolve_tier(None).name, "free")
        self.assertEqual(resolve_tier("PRO").name, "pro")

    def test_monthly_counters_reset_across_periods(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            jan = datetime(2026, 1, 15, tzinfo=timezone.utc)
            feb = datetime(2026, 2, 1, tzinfo=timezone.utc)
            store.consume("erin", api_calls=900, storage_bytes=GB, now=jan)
            # New month resets calls but storage persists.
            usage = store.consume("erin", api_calls=1, now=feb)
            self.assertEqual(usage.api_calls, 1)
            self.assertEqual(usage.period, current_period(feb))
            self.assertEqual(usage.storage_bytes, GB)

    def test_update_storage_never_raises_over_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            # Reflecting an oversized archive must not raise...
            store.update_storage("frank", 6 * GB)
            self.assertEqual(store.get_usage("frank").storage_bytes, 6 * GB)
            # ...but the next consume that re-checks storage is rejected.
            with self.assertRaises(QuotaExceeded):
                store.consume("frank", api_calls=1, storage_bytes=6 * GB)

    def test_persistence_across_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "quota.json"
            QuotaStore(path).consume("gina", api_calls=5, storage_bytes=GB)
            reopened = QuotaStore(path)
            usage = reopened.get_usage("gina")
            self.assertEqual(usage.api_calls, 5)
            self.assertEqual(usage.storage_bytes, GB)

    def test_corrupt_db_is_treated_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "quota.json"
            path.write_text("{not json", encoding="utf-8")
            store = QuotaStore(path)
            usage = store.consume("hank", api_calls=1)
            self.assertEqual(usage.api_calls, 1)

    def test_exceeded_payload_shape(self) -> None:
        exc = QuotaExceeded(
            user="x", tier="free", resource="calls", limit=1000, used=1000, requested=1
        )
        payload = exc.to_payload()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "quota_exceeded")
        self.assertEqual(payload["resource"], "calls")
        self.assertEqual(payload["limit"], 1000)


class TestUsageAndHelpers(unittest.TestCase):
    def test_directory_size_sums_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.bin").write_bytes(b"x" * 100)
            sub = root / "sub"
            sub.mkdir()
            (sub / "b.bin").write_bytes(b"y" * 50)
            self.assertEqual(directory_size(root), 150)

    def test_directory_size_missing_path_is_zero(self) -> None:
        self.assertEqual(directory_size(Path("/nonexistent/quota/path")), 0)

    def test_usage_roundtrip(self) -> None:
        usage = Usage(tier="pro", period="2026-06", api_calls=3, ocr_calls=4, storage_bytes=9)
        self.assertEqual(Usage.from_dict(usage.to_dict()), usage)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_api(port: int, attempts: int = 30) -> None:
    # Probe the public root -- every /api/* route is behind the bearer gate
    # now, so an unauthenticated /api/status would 401 forever here.
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


class TestQuotaApiIntegration(unittest.TestCase):
    """Quota metering over HTTP against the authenticated identity.

    The quota subject is the AuthStore user (its integer id, stringified in
    the ledger) -- not a client-supplied ``X-User-*`` header. Tier likewise
    lives in the ledger; these tests pre-seed it, standing in for the MONETA
    licence grant that will set it in production.
    """

    def _server(self, root: Path):
        env = dict(os.environ)
        env["MEDIA_ARK_QUOTA_DB"] = str(root / "quota.json")
        env["MEDIA_ARK_USERS_DB"] = str(root / "users.db")
        env["MEDIA_ARK_USER_SANDBOX_ROOT"] = str(root / "sandboxes")
        port = _free_port()
        proc = subprocess.Popen(
            [sys.executable, "-m", "src.platform.api_server", "--host", "127.0.0.1", "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        return proc, port

    def _register(self, port: int, username: str = "quota-user") -> dict:
        status, body = _post(
            f"http://127.0.0.1:{port}/api/auth/register",
            {"username": username, "password": "correct horse battery"},
        )
        self.assertEqual(status, 201, body)
        return body

    def _seed_quota(
        self,
        quota_db: Path,
        user_id,
        *,
        tier: str,
        api_calls: int = 0,
        ocr_calls: int = 0,
        storage_bytes: int = 0,
    ) -> None:
        # The ledger reads fresh on every request, so seeding after the
        # server is up still takes effect on the next call.
        quota_db.write_text(
            json.dumps(
                {
                    "users": {
                        str(user_id): {
                            "tier": tier,
                            "period": current_period(),
                            "api_calls": api_calls,
                            "ocr_calls": ocr_calls,
                            "storage_bytes": storage_bytes,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

    def test_run_consumes_quota_and_429_when_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            quota_db = root / "quota.json"
            proc, port = self._server(root)
            try:
                _wait_for_api(port)
                auth = self._register(port)
                token = auth["api_key"]
                source = Path(auth["source"])
                out = Path(auth["out"])
                source.mkdir(parents=True, exist_ok=True)
                out.mkdir(parents=True, exist_ok=True)
                # This user is already at the free call limit -> next run 429s.
                self._seed_quota(
                    quota_db,
                    auth["user"]["id"],
                    tier="free",
                    api_calls=TIERS["free"].monthly_calls,
                )
                status, body = _post(
                    f"http://127.0.0.1:{port}/api/run",
                    {"action": "check-source", "source": str(source), "out": str(out)},
                    token,
                )
                self.assertEqual(status, 429, body)
                self.assertEqual(body["error"], "quota_exceeded")
                self.assertEqual(body["resource"], "calls")
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_run_records_usage_visible_via_quota_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            quota_db = root / "quota.json"
            proc, port = self._server(root)
            try:
                _wait_for_api(port)
                auth = self._register(port)
                token = auth["api_key"]
                source = Path(auth["source"])
                out = Path(auth["out"])
                source.mkdir(parents=True, exist_ok=True)
                out.mkdir(parents=True, exist_ok=True)
                # Pro is granted in the ledger (a MONETA licence would do this
                # in production), never asserted via a request header.
                self._seed_quota(quota_db, auth["user"]["id"], tier="pro")
                # OCR disabled -> 1 api call, 0 ocr calls.
                status, body = _post(
                    f"http://127.0.0.1:{port}/api/run",
                    {
                        "action": "process",
                        "source": str(source),
                        "out": str(out),
                        "no_ocr": True,
                    },
                    token,
                )
                self.assertTrue(body.get("ok"), body)

                qstatus, quota = _get(f"http://127.0.0.1:{port}/api/quota", token)
                self.assertEqual(qstatus, 200, quota)
                self.assertEqual(quota["tier"], "pro")
                self.assertEqual(quota["usage"]["api_calls"], 1)
                self.assertEqual(quota["usage"]["ocr_calls"], 0)
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_quota_read_does_not_consume_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            proc, port = self._server(root)
            try:
                _wait_for_api(port)
                auth = self._register(port)
                token = auth["api_key"]
                for _ in range(3):
                    _get(f"http://127.0.0.1:{port}/api/quota", token)
                _, quota = _get(f"http://127.0.0.1:{port}/api/quota", token)
                self.assertEqual(quota["usage"]["api_calls"], 0)
            finally:
                proc.terminate()
                proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
