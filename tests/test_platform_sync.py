from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from src.platform.config import SyncConfig, load_sync_config, pro_enabled
from src.platform.sync import (
    CloudSyncClient,
    SyncConfigError,
    SyncDisabledError,
    SyncError,
    build_object_key,
    decrypt_after_download,
    derive_key,
    encrypt_before_upload,
    sync_status,
)


# A populated config used for plan/encrypt paths. No real bucket exists; the
# tests below only ever build plans (dry runs), never a network call.
_CONFIG = SyncConfig(
    bucket="ark-backups",
    endpoint_url="https://acct.r2.cloudflarestorage.com",
    prefix="captures/",
)


def _pro_env(**extra: str) -> dict:
    env = {"MEDIA_ARK_PRO": "1"}
    env.update(extra)
    return env


class TestEncryptStub(unittest.TestCase):
    def test_envelope_roundtrips_and_hides_plaintext(self) -> None:
        key = derive_key("correct horse battery staple")
        plaintext = b"top-secret capture bytes \x00\xff"
        blob = encrypt_before_upload(plaintext, key=key)

        self.assertNotEqual(blob, plaintext)
        self.assertNotIn(plaintext, blob)
        self.assertTrue(blob.startswith(b"MASYNC"))
        self.assertEqual(decrypt_after_download(blob, key=key), plaintext)

    def test_fixed_nonce_is_deterministic(self) -> None:
        key = derive_key("k")
        nonce = b"0123456789abcdef"
        first = encrypt_before_upload(b"abc", key=key, nonce=nonce)
        second = encrypt_before_upload(b"abc", key=key, nonce=nonce)
        self.assertEqual(first, second)

    def test_random_nonce_varies_ciphertext(self) -> None:
        key = derive_key("k")
        self.assertNotEqual(
            encrypt_before_upload(b"abc", key=key),
            encrypt_before_upload(b"abc", key=key),
        )

    def test_wrong_key_fails_to_recover_plaintext(self) -> None:
        blob = encrypt_before_upload(b"secret", key=derive_key("right"))
        self.assertNotEqual(decrypt_after_download(blob, key=derive_key("wrong")), b"secret")

    def test_encrypt_requires_key(self) -> None:
        with self.assertRaises(SyncConfigError):
            encrypt_before_upload(b"x", key=b"")

    def test_decrypt_rejects_foreign_blob(self) -> None:
        with self.assertRaises(SyncError):
            decrypt_after_download(b"not-an-envelope", key=derive_key("k"))


class TestProGate(unittest.TestCase):
    def test_disabled_by_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(pro_enabled())
            with self.assertRaises(SyncDisabledError):
                CloudSyncClient(_CONFIG)

    def test_enabled_via_env(self) -> None:
        with mock.patch.dict(os.environ, _pro_env(), clear=True):
            self.assertTrue(pro_enabled())
            client = CloudSyncClient(_CONFIG, key=derive_key("k"))
            self.assertIsInstance(client, CloudSyncClient)


class TestObjectKey(unittest.TestCase):
    def test_prefix_applied_and_normalized(self) -> None:
        self.assertEqual(
            build_object_key(_CONFIG, Path("/tmp/shot.png")), "captures/shot.png"
        )

    def test_no_prefix(self) -> None:
        cfg = SyncConfig(bucket="b")
        self.assertEqual(build_object_key(cfg, Path("/tmp/a.jpg")), "a.jpg")


class TestPlanAndUpload(unittest.TestCase):
    def test_plan_upload_makes_no_network_call(self) -> None:
        with mock.patch.dict(os.environ, _pro_env(), clear=True):
            client = CloudSyncClient(_CONFIG, key=derive_key("k"))
            # boto3 must never be reached for a plan.
            with mock.patch("src.platform.sync.make_s3_client") as fake_client:
                plan = client.plan_upload(Path("frame.png"), data=b"hello world")
                fake_client.assert_not_called()

        self.assertEqual(plan.bucket, "ark-backups")
        self.assertEqual(plan.object_key, "captures/frame.png")
        self.assertEqual(plan.plaintext_bytes, len(b"hello world"))
        self.assertGreater(plan.encrypted_bytes, plan.plaintext_bytes)
        self.assertEqual(plan.provider, "r2")
        self.assertFalse(plan.uploaded)

    def test_upload_dry_run_is_inert(self) -> None:
        with mock.patch.dict(os.environ, _pro_env(), clear=True):
            client = CloudSyncClient(_CONFIG, key=derive_key("k"))
            with mock.patch("src.platform.sync.make_s3_client") as fake_client:
                plan = client.upload(Path("frame.png"), data=b"data")
                fake_client.assert_not_called()
        self.assertFalse(plan.uploaded)

    def test_real_upload_requires_credentials(self) -> None:
        with mock.patch.dict(os.environ, _pro_env(), clear=True):
            client = CloudSyncClient(_CONFIG, key=derive_key("k"))
            with self.assertRaises(SyncConfigError):
                client.upload(Path("frame.png"), data=b"data", dry_run=False)

    def test_plan_requires_configured_bucket(self) -> None:
        with mock.patch.dict(os.environ, _pro_env(), clear=True):
            client = CloudSyncClient(SyncConfig(), key=derive_key("k"))
            with self.assertRaises(SyncConfigError):
                client.plan_upload(Path("frame.png"), data=b"x")


class TestSyncConfigAndStatus(unittest.TestCase):
    def test_load_sync_config_from_env(self) -> None:
        env = _pro_env(
            MEDIA_ARK_SYNC_BUCKET="my-bucket",
            MEDIA_ARK_SYNC_ENDPOINT="https://x.r2.cloudflarestorage.com",
            MEDIA_ARK_SYNC_PREFIX="archive",
            MEDIA_ARK_SYNC_ACCESS_KEY_ID="AK",
            MEDIA_ARK_SYNC_SECRET_ACCESS_KEY="SK",
        )
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = load_sync_config()
        self.assertEqual(cfg.bucket, "my-bucket")
        self.assertEqual(cfg.prefix, "archive")
        self.assertTrue(cfg.is_configured)
        self.assertTrue(cfg.has_credentials)
        self.assertEqual(cfg.provider, "r2")

    def test_sync_status_hides_secrets_and_reports_state(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            status = sync_status(_CONFIG)
        self.assertFalse(status["enabled"])
        self.assertTrue(status["configured"])
        self.assertEqual(status["bucket"], "ark-backups")
        self.assertNotIn("secret_access_key", status)
        self.assertNotIn("access_key_id", status)


if __name__ == "__main__":
    unittest.main()
