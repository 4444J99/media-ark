from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.platform.auth import (
    AuthConflictError,
    AuthCredentialsError,
    AuthStore,
    hash_password,
    verify_password,
)


class TestPlatformAuth(unittest.TestCase):
    def test_register_login_authenticate_and_rotate_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = AuthStore(root / "users.db", root / "sandboxes")

            user, api_key = store.register("Alice_1", "correct horse battery")
            self.assertEqual(user.username, "alice_1")
            self.assertTrue((user.sandbox / "source").is_dir())
            self.assertTrue((user.sandbox / "out").is_dir())
            self.assertEqual(store.authenticate_api_key(api_key), user)
            self.assertIsNone(store.authenticate_api_key("bad-token"))

            logged_in, login_key = store.login("alice_1", "correct horse battery")
            self.assertEqual(logged_in, user)
            self.assertNotEqual(login_key, api_key)
            self.assertIsNone(store.authenticate_api_key(api_key))
            self.assertEqual(store.authenticate_api_key(login_key), user)

            rotated, rotated_key = store.rotate_api_key(user.id)
            self.assertEqual(rotated, user)
            self.assertNotEqual(rotated_key, login_key)
            self.assertIsNone(store.authenticate_api_key(login_key))
            self.assertEqual(store.authenticate_api_key(rotated_key), user)

    def test_register_rejects_duplicates_and_bad_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = AuthStore(root / "users.db", root / "sandboxes")
            store.register("local-user", "correct horse battery")

            with self.assertRaises(AuthConflictError):
                store.register("local-user", "correct horse battery")

            with self.assertRaises(AuthCredentialsError):
                store.login("local-user", "wrong password")

    def test_password_hashes_are_salted_and_verifiable(self) -> None:
        password = "correct horse battery"
        first = hash_password(password)
        second = hash_password(password)

        self.assertNotEqual(first, second)
        self.assertTrue(verify_password(password, first))
        self.assertFalse(verify_password("wrong password", first))
