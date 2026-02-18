"""
Authentication and user management for the eiskaltdcpp-py REST API.

Provides:
- Password hashing (bcrypt)
- JWT token generation and validation
- In-memory user store with persistence to JSON
- Role-based access control (admin / readonly)

The initial admin user is created from environment variables or CLI args.
Admin users can create/modify/delete other users via the API.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from eiskaltdcpp.api.models import UserInfo, UserRole

logger = logging.getLogger(__name__)


def _hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    pw_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    pw_bytes = password.encode("utf-8")
    hashed_bytes = hashed.encode("utf-8")
    return bcrypt.checkpw(pw_bytes, hashed_bytes)

# JWT defaults
DEFAULT_SECRET_KEY = secrets.token_urlsafe(64)
DEFAULT_ALGORITHM = "HS256"
DEFAULT_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours


class UserRecord:
    """Internal user record with hashed password."""

    __slots__ = ("username", "hashed_password", "role", "created_at", "last_login")

    def __init__(
        self,
        username: str,
        hashed_password: str,
        role: UserRole,
        created_at: Optional[datetime] = None,
        last_login: Optional[datetime] = None,
    ) -> None:
        self.username = username
        self.hashed_password = hashed_password
        self.role = role
        self.created_at = created_at or datetime.now(timezone.utc)
        self.last_login = last_login

    def to_info(self) -> UserInfo:
        """Convert to public UserInfo (no password)."""
        return UserInfo(
            username=self.username,
            role=self.role,
            created_at=self.created_at,
            last_login=self.last_login,
        )

    def to_dict(self) -> dict:
        """Serialize for JSON persistence."""
        return {
            "username": self.username,
            "hashed_password": self.hashed_password,
            "role": self.role.value,
            "created_at": self.created_at.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserRecord":
        """Deserialize from JSON."""
        return cls(
            username=data["username"],
            hashed_password=data["hashed_password"],
            role=UserRole(data["role"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_login=(
                datetime.fromisoformat(data["last_login"])
                if data.get("last_login")
                else None
            ),
        )


class UserStore:
    """
    Thread-safe in-memory user store with optional JSON file persistence.

    Users are stored in memory for fast lookups. If a ``persist_path``
    is set, changes are automatically written to disk.
    """

    def __init__(self, persist_path: Optional[str | Path] = None) -> None:
        self._users: dict[str, UserRecord] = {}
        self._lock = threading.Lock()
        self._persist_path = Path(persist_path) if persist_path else None

        # Load from disk if file exists
        if self._persist_path and self._persist_path.exists():
            self._load()

    def _load(self) -> None:
        """Load users from disk."""
        try:
            data = json.loads(self._persist_path.read_text())
            for entry in data.get("users", []):
                rec = UserRecord.from_dict(entry)
                self._users[rec.username] = rec
            logger.info("Loaded %d users from %s", len(self._users), self._persist_path)
        except Exception:
            logger.exception("Failed to load user store from %s", self._persist_path)

    def _save(self) -> None:
        """Persist users to disk (call while holding lock)."""
        if not self._persist_path:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"users": [u.to_dict() for u in self._users.values()]}
            self._persist_path.write_text(json.dumps(data, indent=2))
        except Exception:
            logger.exception("Failed to save user store to %s", self._persist_path)

    def create_user(
        self,
        username: str,
        password: str,
        role: UserRole = UserRole.readonly,
    ) -> UserRecord:
        """Create a new user. Raises ValueError if user already exists."""
        with self._lock:
            if username in self._users:
                raise ValueError(f"User '{username}' already exists")
            rec = UserRecord(
                username=username,
                hashed_password=_hash_password(password),
                role=role,
            )
            self._users[username] = rec
            self._save()
            return rec

    def get_user(self, username: str) -> Optional[UserRecord]:
        """Get a user by username."""
        with self._lock:
            return self._users.get(username)

    def list_users(self) -> list[UserRecord]:
        """List all users."""
        with self._lock:
            return list(self._users.values())

    def update_user(
        self,
        username: str,
        password: Optional[str] = None,
        role: Optional[UserRole] = None,
    ) -> UserRecord:
        """Update user password and/or role. Raises KeyError if not found."""
        with self._lock:
            rec = self._users.get(username)
            if rec is None:
                raise KeyError(f"User '{username}' not found")
            if password is not None:
                rec.hashed_password = _hash_password(password)
            if role is not None:
                rec.role = role
            self._save()
            return rec

    def delete_user(self, username: str) -> None:
        """Delete a user. Raises KeyError if not found."""
        with self._lock:
            if username not in self._users:
                raise KeyError(f"User '{username}' not found")
            del self._users[username]
            self._save()

    def authenticate(self, username: str, password: str) -> Optional[UserRecord]:
        """Verify credentials. Returns user record or None."""
        with self._lock:
            rec = self._users.get(username)
            if rec is None:
                return None
            if not _verify_password(password, rec.hashed_password):
                return None
            rec.last_login = datetime.now(timezone.utc)
            self._save()
            return rec

    def user_count(self) -> int:
        """Number of registered users."""
        with self._lock:
            return len(self._users)


class AuthManager:
    """
    JWT authentication manager.

    Handles token creation, validation, and ties into the UserStore
    for credential verification.
    """

    def __init__(
        self,
        user_store: UserStore,
        secret_key: Optional[str] = None,
        algorithm: str = DEFAULT_ALGORITHM,
        token_expire_minutes: int = DEFAULT_TOKEN_EXPIRE_MINUTES,
    ) -> None:
        self.user_store = user_store
        self.secret_key = secret_key or os.environ.get(
            "EISKALTDCPP_JWT_SECRET", DEFAULT_SECRET_KEY
        )
        self.algorithm = algorithm
        self.token_expire_minutes = token_expire_minutes

    def create_token(self, username: str, role: UserRole) -> tuple[str, int]:
        """
        Create a JWT access token.

        Returns:
            Tuple of (token_string, expires_in_seconds)
        """
        expires_delta = timedelta(minutes=self.token_expire_minutes)
        expire = datetime.now(timezone.utc) + expires_delta

        payload = {
            "sub": username,
            "role": role.value,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "jti": secrets.token_urlsafe(16),
        }
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return token, int(expires_delta.total_seconds())

    def verify_token(self, token: str) -> Optional[dict]:
        """
        Verify and decode a JWT token.

        Returns:
            Decoded payload dict, or None if invalid/expired.
        """
        try:
            payload = jwt.decode(
                token, self.secret_key, algorithms=[self.algorithm]
            )
            username: str = payload.get("sub")
            role: str = payload.get("role")
            if username is None or role is None:
                return None
            return payload
        except JWTError:
            return None

    def login(self, username: str, password: str) -> Optional[tuple[str, int, UserRole]]:
        """
        Authenticate and issue a token.

        Returns:
            Tuple of (token, expires_in, role) or None if auth fails.
        """
        user = self.user_store.authenticate(username, password)
        if user is None:
            return None
        token, expires_in = self.create_token(user.username, user.role)
        return token, expires_in, user.role

    def ensure_admin_exists(
        self,
        admin_username: Optional[str] = None,
        admin_password: Optional[str] = None,
    ) -> None:
        """
        Ensure at least one admin user exists.

        Checks environment variables if args not provided:
          - EISKALTDCPP_ADMIN_USER (default: "admin")
          - EISKALTDCPP_ADMIN_PASS (required)
        """
        username = admin_username or os.environ.get("EISKALTDCPP_ADMIN_USER", "admin")
        password = admin_password or os.environ.get("EISKALTDCPP_ADMIN_PASS")

        if not password:
            # Generate a random password and log it
            password = secrets.token_urlsafe(16)
            logger.warning(
                "No admin password configured. Generated random password for "
                "user '%s': %s  (set EISKALTDCPP_ADMIN_PASS to avoid this)",
                username, password,
            )

        existing = self.user_store.get_user(username)
        if existing is None:
            self.user_store.create_user(username, password, UserRole.admin)
            logger.info("Created admin user '%s'", username)
        elif existing.role != UserRole.admin:
            self.user_store.update_user(username, role=UserRole.admin)
            logger.info("Upgraded user '%s' to admin", username)
