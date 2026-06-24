"""Local user authentication for the platform HTTP API."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional, Tuple

# Ensure the `media_ark` brand module is importable when this file is
# imported as `src.platform.auth` from the repository checkout.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.append(str(_SRC))

from media_ark import BRAND_DATA_DIR, env_key  # noqa: E402


PASSWORD_ITERATIONS = 210_000
USERNAME_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{2,63}")


class AuthError(ValueError):
    """Raised when a registration or login request is invalid."""

    error = "auth_error"


class AuthConflictError(AuthError):
    error = "user_exists"


class AuthCredentialsError(AuthError):
    error = "invalid_credentials"


@dataclass(frozen=True)
class AuthUser:
    id: int
    username: str
    sandbox: Path


def default_users_db_path() -> Path:
    raw = os.environ.get(env_key("USERS_DB"), "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / BRAND_DATA_DIR / "users.db").resolve()


def default_user_sandbox_root() -> Path:
    raw = os.environ.get(env_key("USER_SANDBOX_ROOT"), "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / BRAND_DATA_DIR / "users").resolve()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _chmod_private(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass


def normalize_username(username: object) -> str:
    normalized = str(username or "").strip().lower()
    if not USERNAME_RE.fullmatch(normalized):
        raise AuthError(
            "username must be 3-64 characters using letters, numbers, dot, dash, or underscore"
        )
    return normalized


def validate_password(password: object) -> str:
    text = str(password or "")
    if len(text) < 8:
        raise AuthError("password must be at least 8 characters")
    if "\x00" in text:
        raise AuthError("password contains a null byte")
    return text


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return (
        f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return secrets.compare_digest(actual, expected)


def generate_api_key() -> str:
    return f"ma_{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


class AuthStore:
    """SQLite-backed local user store.

    Passwords use PBKDF2-HMAC-SHA256 and API keys are stored only as
    SHA-256 digests. API keys are high-entropy bearer secrets, so a
    deterministic digest keeps authentication lookup simple without
    storing the token itself.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        sandbox_root: Optional[Path] = None,
    ) -> None:
        self.db_path = Path(db_path or default_users_db_path()).expanduser().resolve()
        self.sandbox_root = Path(
            sandbox_root or default_user_sandbox_root()
        ).expanduser().resolve()
        self._schema_ready = False
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        _chmod_private(self.db_path.parent, 0o700)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
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
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    api_key_hash TEXT NOT NULL UNIQUE,
                    sandbox TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_users_api_key_hash
                    ON users(api_key_hash);
                """
            )
            connection.commit()
            self._schema_ready = True

    def _sandbox_for(self, username: str) -> Path:
        return (self.sandbox_root / username).resolve()

    def _ensure_sandbox(self, sandbox: Path) -> None:
        sandbox.mkdir(parents=True, exist_ok=True)
        (sandbox / "source").mkdir(parents=True, exist_ok=True)
        (sandbox / "out").mkdir(parents=True, exist_ok=True)
        _chmod_private(self.sandbox_root, 0o700)
        _chmod_private(sandbox, 0o700)

    def _user_from_row(self, row: sqlite3.Row) -> AuthUser:
        return AuthUser(
            id=int(row["id"]),
            username=str(row["username"]),
            sandbox=Path(str(row["sandbox"])).expanduser().resolve(),
        )

    def _new_api_key(self) -> Tuple[str, str]:
        api_key = generate_api_key()
        return api_key, hash_api_key(api_key)

    def register(self, username: object, password: object) -> Tuple[AuthUser, str]:
        normalized_username = normalize_username(username)
        normalized_password = validate_password(password)
        password_hash = hash_password(normalized_password)
        api_key, api_key_digest = self._new_api_key()
        sandbox = self._sandbox_for(normalized_username)
        now = _utc_now()

        with self._connection() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO users (
                        username, password_hash, api_key_hash, sandbox,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_username,
                        password_hash,
                        api_key_digest,
                        str(sandbox),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AuthConflictError("username already exists") from exc
            user = AuthUser(
                id=int(cursor.lastrowid),
                username=normalized_username,
                sandbox=sandbox,
            )
        self._ensure_sandbox(sandbox)
        return user, api_key

    def login(self, username: object, password: object) -> Tuple[AuthUser, str]:
        normalized_username = normalize_username(username)
        normalized_password = validate_password(password)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ?", (normalized_username,)
            ).fetchone()
            if row is None or not verify_password(
                normalized_password, str(row["password_hash"])
            ):
                raise AuthCredentialsError("invalid username or password")
            api_key, api_key_digest = self._new_api_key()
            now = _utc_now()
            connection.execute(
                """
                UPDATE users
                SET api_key_hash = ?, updated_at = ?
                WHERE id = ?
                """,
                (api_key_digest, now, int(row["id"])),
            )
            user = self._user_from_row(row)
        self._ensure_sandbox(user.sandbox)
        return user, api_key

    def authenticate_api_key(self, api_key: object) -> Optional[AuthUser]:
        token = str(api_key or "").strip()
        if not token or len(token) > 512:
            return None
        api_key_digest = hash_api_key(token)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE api_key_hash = ?", (api_key_digest,)
            ).fetchone()
        if row is None:
            return None
        user = self._user_from_row(row)
        self._ensure_sandbox(user.sandbox)
        return user

    def rotate_api_key(self, user_id: int) -> Tuple[AuthUser, str]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?", (int(user_id),)
            ).fetchone()
            if row is None:
                raise AuthCredentialsError("user not found")
            api_key, api_key_digest = self._new_api_key()
            now = _utc_now()
            connection.execute(
                """
                UPDATE users
                SET api_key_hash = ?, updated_at = ?
                WHERE id = ?
                """,
                (api_key_digest, now, int(user_id)),
            )
            user = self._user_from_row(row)
        self._ensure_sandbox(user.sandbox)
        return user, api_key
