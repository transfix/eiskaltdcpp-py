"""
Comprehensive tests for the eiskaltdcpp-py REST API.

Tests cover:
- Authentication (login, JWT validation, token expiry)
- User management (CRUD, RBAC)
- Hub management endpoints
- Chat endpoints
- Search endpoints
- Download queue endpoints
- Share management endpoints
- Settings endpoints
- Status/health endpoints
- Role-based access control (admin vs readonly)

All tests use a test FastAPI client with mocked DC client — no SWIG module
or C++ library required.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, PropertyMock

import pytest
from fastapi.testclient import TestClient

from eiskaltdcpp.api.app import create_app
from eiskaltdcpp.api.auth import AuthManager, UserStore
from eiskaltdcpp.api.models import UserRole


# ============================================================================
# Mock DC client
# ============================================================================

class MockDCClient:
    """
    Mock AsyncDCClient that simulates the DC client interface
    without requiring SWIG bindings.
    """

    def __init__(self) -> None:
        self.is_initialized = True
        self.version = "2.4.2-test"
        self._hubs: list[dict] = []
        self._users: dict[str, list[dict]] = {}
        self._chat_history: dict[str, list[str]] = {}
        self._search_results: list[dict] = []
        self._queue: list[dict] = []
        self._shares: list[dict] = []
        self._settings: dict[str, str] = {}
        self._share_size = 0
        self._shared_files = 0
        self._hashing_paused = False

    # Hub methods
    async def connect(self, url: str, encoding: str = "") -> None:
        self._hubs.append({"url": url, "name": url, "connected": True, "userCount": 0})

    async def disconnect(self, url: str) -> None:
        self._hubs = [h for h in self._hubs if h["url"] != url]

    def list_hubs(self) -> list:
        return [_DictObj(h) for h in self._hubs]

    def is_connected(self, url: str) -> bool:
        return any(h["url"] == url for h in self._hubs)

    # Chat methods
    def send_message(self, hub_url: str, message: str) -> None:
        self._chat_history.setdefault(hub_url, []).append(message)

    def send_pm(self, hub_url: str, nick: str, message: str) -> None:
        pass

    def get_chat_history(self, hub_url: str, max_lines: int = 100) -> list[str]:
        return self._chat_history.get(hub_url, [])[:max_lines]

    # User methods
    def get_users(self, hub_url: str) -> list:
        return [_DictObj(u) for u in self._users.get(hub_url, [])]

    # Search methods
    def search(self, query: str, file_type: int = 0, size_mode: int = 0,
               size: int = 0, hub_url: str = "") -> bool:
        return len(self._hubs) > 0

    def get_search_results(self, hub_url: str = "") -> list:
        return [_DictObj(r) for r in self._search_results]

    def clear_search_results(self, hub_url: str = "") -> None:
        self._search_results.clear()

    # Queue methods
    def download(self, directory: str, name: str, size: int, tth: str,
                 hub_url: str = "", nick: str = "") -> bool:
        self._queue.append({
            "target": f"{directory}/{name}",
            "size": size, "downloadedBytes": 0,
            "priority": 3, "tth": tth,
        })
        return True

    def download_magnet(self, magnet: str, download_dir: str = "") -> bool:
        self._queue.append({
            "target": f"{download_dir}/magnet-file",
            "size": 0, "downloadedBytes": 0,
            "priority": 3, "tth": "",
        })
        return True

    def remove_download(self, target: str) -> None:
        self._queue = [q for q in self._queue if q["target"] != target]

    def list_queue(self) -> list:
        return [_DictObj(q) for q in self._queue]

    def clear_queue(self) -> None:
        self._queue.clear()

    # Share methods
    def add_share(self, real_path: str, virtual_name: str) -> bool:
        self._shares.append({
            "realPath": real_path, "virtualName": virtual_name, "size": 0,
        })
        return True

    def remove_share(self, real_path: str) -> bool:
        before = len(self._shares)
        self._shares = [s for s in self._shares if s["realPath"] != real_path]
        return len(self._shares) < before

    def list_shares(self) -> list:
        return [_DictObj(s) for s in self._shares]

    def refresh_share(self) -> None:
        pass

    @property
    def share_size(self) -> int:
        return self._share_size

    @property
    def shared_files(self) -> int:
        return self._shared_files

    # Settings methods
    def get_setting(self, name: str) -> str:
        return self._settings.get(name, "")

    def set_setting(self, name: str, value: str) -> None:
        self._settings[name] = value

    def start_networking(self) -> None:
        pass

    # Transfer/hash methods
    @property
    def transfer_stats(self) -> Any:
        return _DictObj({
            "downloadSpeed": 1024, "uploadSpeed": 512,
            "downloaded": 1048576, "uploaded": 524288,
        })

    @property
    def hash_status(self) -> Any:
        return _DictObj({
            "currentFile": "/tmp/test.bin" if not self._hashing_paused else "",
            "filesLeft": 5, "bytesLeft": 1048576,
            "isPaused": self._hashing_paused,
        })

    def pause_hashing(self, pause: bool = True) -> None:
        self._hashing_paused = pause

    # Mock _sync_client for routes that access it directly
    @property
    def _sync_client(self) -> "MockDCClient":
        return self

    def set_priority(self, target: str, priority: int) -> None:
        for q in self._queue:
            if q["target"] == target:
                q["priority"] = priority

    def reload_config(self) -> None:
        pass


class _DictObj:
    """Wraps a dict to allow attribute access (mimics SWIG data objects)."""
    def __init__(self, d: dict):
        self.__dict__.update(d)

    def __str__(self):
        return str(self.__dict__)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_client() -> MockDCClient:
    """Create a mock DC client."""
    return MockDCClient()


@pytest.fixture
def user_store(tmp_path) -> UserStore:
    """Create a temporary user store."""
    return UserStore(persist_path=tmp_path / "users.json")


@pytest.fixture
def auth_manager(user_store) -> AuthManager:
    """Create an auth manager with known secret."""
    return AuthManager(
        user_store=user_store,
        secret_key="test-secret-key-for-unit-tests",
        token_expire_minutes=60,
    )


@pytest.fixture
def app(mock_client, auth_manager) -> TestClient:
    """Create test app with mock DC client and return TestClient."""
    application = create_app(
        auth_manager=auth_manager,
        dc_client=mock_client,
        admin_username="admin",
        admin_password="adminpass123",
    )
    return TestClient(application)


@pytest.fixture
def admin_token(app) -> str:
    """Get a valid admin JWT token."""
    resp = app.post("/api/auth/login", json={
        "username": "admin",
        "password": "adminpass123",
    })
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
def readonly_token(app, admin_token) -> str:
    """Create a readonly user and return its JWT token."""
    # Create readonly user
    resp = app.post(
        "/api/auth/users",
        json={"username": "viewer", "password": "viewerpass1", "role": "readonly"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201

    # Login as readonly
    resp = app.post("/api/auth/login", json={
        "username": "viewer",
        "password": "viewerpass1",
    })
    assert resp.status_code == 200
    return resp.json()["access_token"]


def auth_header(token: str) -> dict:
    """Build Authorization header."""
    return {"Authorization": f"Bearer {token}"}


# ============================================================================
# Auth tests
# ============================================================================

class TestAuthLogin:
    """Tests for POST /api/auth/login."""

    def test_login_success(self, app):
        resp = app.post("/api/auth/login", json={
            "username": "admin",
            "password": "adminpass123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["role"] == "admin"
        assert data["expires_in"] > 0

    def test_login_wrong_password(self, app):
        resp = app.post("/api/auth/login", json={
            "username": "admin",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, app):
        resp = app.post("/api/auth/login", json={
            "username": "nobody",
            "password": "whatever1",
        })
        assert resp.status_code == 401

    def test_login_empty_username(self, app):
        resp = app.post("/api/auth/login", json={
            "username": "",
            "password": "pass",
        })
        assert resp.status_code == 422  # validation error

    def test_login_missing_password(self, app):
        resp = app.post("/api/auth/login", json={
            "username": "admin",
        })
        assert resp.status_code == 422


class TestAuthMe:
    """Tests for GET /api/auth/me."""

    def test_get_me_admin(self, app, admin_token):
        resp = app.get("/api/auth/me", headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "admin"
        assert data["role"] == "admin"
        assert "created_at" in data

    def test_get_me_readonly(self, app, readonly_token):
        resp = app.get("/api/auth/me", headers=auth_header(readonly_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "viewer"
        assert data["role"] == "readonly"

    def test_get_me_no_token(self, app):
        resp = app.get("/api/auth/me")
        assert resp.status_code == 401

    def test_get_me_invalid_token(self, app):
        resp = app.get("/api/auth/me", headers=auth_header("invalid.jwt.token"))
        assert resp.status_code == 401

    def test_get_me_expired_token(self, app, auth_manager):
        """Test that expired tokens are rejected."""
        # Create a token that expired 1 hour ago
        from jose import jwt
        payload = {
            "sub": "admin",
            "role": "admin",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        }
        expired = jwt.encode(payload, auth_manager.secret_key, algorithm="HS256")
        resp = app.get("/api/auth/me", headers=auth_header(expired))
        assert resp.status_code == 401


# ============================================================================
# User management tests
# ============================================================================

class TestUserManagement:
    """Tests for user CRUD endpoints."""

    def test_create_user(self, app, admin_token):
        resp = app.post(
            "/api/auth/users",
            json={"username": "newuser", "password": "password123", "role": "readonly"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newuser"
        assert data["role"] == "readonly"

    def test_create_admin_user(self, app, admin_token):
        resp = app.post(
            "/api/auth/users",
            json={"username": "admin2", "password": "password123", "role": "admin"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "admin"

    def test_create_duplicate_user(self, app, admin_token):
        resp = app.post(
            "/api/auth/users",
            json={"username": "admin", "password": "password123"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 409

    def test_create_user_short_password(self, app, admin_token):
        resp = app.post(
            "/api/auth/users",
            json={"username": "short", "password": "abc"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    def test_create_user_readonly_denied(self, app, readonly_token):
        resp = app.post(
            "/api/auth/users",
            json={"username": "hacker", "password": "password123"},
            headers=auth_header(readonly_token),
        )
        assert resp.status_code == 403

    def test_list_users(self, app, admin_token):
        resp = app.get("/api/auth/users", headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any(u["username"] == "admin" for u in data["users"])

    def test_list_users_readonly_denied(self, app, readonly_token):
        resp = app.get("/api/auth/users", headers=auth_header(readonly_token))
        assert resp.status_code == 403

    def test_get_user(self, app, admin_token):
        resp = app.get("/api/auth/users/admin", headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["username"] == "admin"

    def test_get_user_not_found(self, app, admin_token):
        resp = app.get("/api/auth/users/nonexistent", headers=auth_header(admin_token))
        assert resp.status_code == 404

    def test_update_user_role(self, app, admin_token):
        # Create a user first
        app.post(
            "/api/auth/users",
            json={"username": "upgradeuser", "password": "password123", "role": "readonly"},
            headers=auth_header(admin_token),
        )
        # Upgrade to admin
        resp = app.put(
            "/api/auth/users/upgradeuser",
            json={"role": "admin"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    def test_update_user_password(self, app, admin_token):
        app.post(
            "/api/auth/users",
            json={"username": "pwuser", "password": "oldpassword1"},
            headers=auth_header(admin_token),
        )
        resp = app.put(
            "/api/auth/users/pwuser",
            json={"password": "newpassword1"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

        # Verify new password works
        resp = app.post("/api/auth/login", json={
            "username": "pwuser", "password": "newpassword1",
        })
        assert resp.status_code == 200

        # Verify old password doesn't work
        resp = app.post("/api/auth/login", json={
            "username": "pwuser", "password": "oldpassword1",
        })
        assert resp.status_code == 401

    def test_update_nonexistent_user(self, app, admin_token):
        resp = app.put(
            "/api/auth/users/nobody",
            json={"role": "admin"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404

    def test_delete_user(self, app, admin_token):
        app.post(
            "/api/auth/users",
            json={"username": "deleteme", "password": "password123"},
            headers=auth_header(admin_token),
        )
        resp = app.delete(
            "/api/auth/users/deleteme",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

        # Verify deleted
        resp = app.get(
            "/api/auth/users/deleteme",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404

    def test_delete_self_denied(self, app, admin_token):
        resp = app.delete(
            "/api/auth/users/admin",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_delete_nonexistent_user(self, app, admin_token):
        resp = app.delete(
            "/api/auth/users/nobody",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404

    def test_deleted_user_token_invalidated(self, app, admin_token):
        """After deleting a user, their existing token should stop working."""
        # Create and login
        app.post(
            "/api/auth/users",
            json={"username": "ephemeral", "password": "password123"},
            headers=auth_header(admin_token),
        )
        resp = app.post("/api/auth/login", json={
            "username": "ephemeral", "password": "password123",
        })
        ephemeral_token = resp.json()["access_token"]

        # Token works
        resp = app.get("/api/auth/me", headers=auth_header(ephemeral_token))
        assert resp.status_code == 200

        # Delete the user
        app.delete(
            "/api/auth/users/ephemeral",
            headers=auth_header(admin_token),
        )

        # Token should now fail
        resp = app.get("/api/auth/me", headers=auth_header(ephemeral_token))
        assert resp.status_code == 401


# ============================================================================
# Hub management tests
# ============================================================================

class TestHubEndpoints:
    """Tests for hub connection management."""

    def test_connect_hub(self, app, admin_token):
        resp = app.post(
            "/api/hubs/connect",
            json={"url": "dchub://test.example.com:411"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_connect_hub_readonly_denied(self, app, readonly_token):
        resp = app.post(
            "/api/hubs/connect",
            json={"url": "dchub://test.example.com:411"},
            headers=auth_header(readonly_token),
        )
        assert resp.status_code == 403

    def test_list_hubs(self, app, admin_token, readonly_token):
        # Connect a hub first
        app.post(
            "/api/hubs/connect",
            json={"url": "dchub://hub1.example.com:411"},
            headers=auth_header(admin_token),
        )

        # Readonly can list
        resp = app.get("/api/hubs", headers=auth_header(readonly_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any("hub1" in h["url"] for h in data["hubs"])

    def test_list_hubs_unauthenticated(self, app):
        resp = app.get("/api/hubs")
        assert resp.status_code == 401

    def test_disconnect_hub(self, app, admin_token):
        app.post(
            "/api/hubs/connect",
            json={"url": "dchub://disc.example.com:411"},
            headers=auth_header(admin_token),
        )
        resp = app.post(
            "/api/hubs/disconnect",
            json={"url": "dchub://disc.example.com:411"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    def test_list_hub_users(self, app, admin_token, mock_client):
        # Seed some users
        mock_client._users["dchub://hub1.example.com:411"] = [
            {"nick": "user1", "shareSize": 1024, "description": "test",
             "tag": "", "connection": "", "email": ""},
            {"nick": "user2", "shareSize": 2048, "description": "",
             "tag": "", "connection": "", "email": ""},
        ]
        resp = app.get(
            "/api/hubs/users",
            params={"hub_url": "dchub://hub1.example.com:411"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["users"][0]["nick"] == "user1"


# ============================================================================
# Chat tests
# ============================================================================

class TestChatEndpoints:
    """Tests for chat/messaging endpoints."""

    def test_send_message(self, app, admin_token):
        resp = app.post(
            "/api/chat/message",
            json={"hub_url": "dchub://hub.example.com:411", "message": "Hello!"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_send_message_readonly_denied(self, app, readonly_token):
        resp = app.post(
            "/api/chat/message",
            json={"hub_url": "dchub://hub.example.com:411", "message": "Hello!"},
            headers=auth_header(readonly_token),
        )
        assert resp.status_code == 403

    def test_send_pm(self, app, admin_token):
        resp = app.post(
            "/api/chat/pm",
            json={
                "hub_url": "dchub://hub.example.com:411",
                "nick": "user1",
                "message": "Hey there!",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    def test_get_chat_history(self, app, admin_token, mock_client, readonly_token):
        # Seed some history
        url = "dchub://hub.example.com:411"
        mock_client._chat_history[url] = [
            "<Alice> hello",
            "<Bob> hi there",
            "<Alice> how are you?",
        ]

        # Readonly can read history
        resp = app.get(
            "/api/chat/history",
            params={"hub_url": url, "max_lines": 2},
            headers=auth_header(readonly_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["hub_url"] == url
        assert len(data["messages"]) == 2

    def test_send_empty_message(self, app, admin_token):
        resp = app.post(
            "/api/chat/message",
            json={"hub_url": "dchub://hub.example.com:411", "message": ""},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422


# ============================================================================
# Search tests
# ============================================================================

class TestSearchEndpoints:
    """Tests for search endpoints."""

    def test_start_search(self, app, admin_token, mock_client):
        # Need a hub connected for search to succeed
        mock_client._hubs.append({"url": "dchub://hub.example.com:411",
                                   "name": "Test", "connected": True,
                                   "userCount": 10})
        resp = app.post(
            "/api/search",
            json={"query": "test file"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    def test_start_search_no_hubs(self, app, admin_token, mock_client):
        mock_client._hubs.clear()
        resp = app.post(
            "/api/search",
            json={"query": "test file"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_start_search_readonly_denied(self, app, readonly_token):
        resp = app.post(
            "/api/search",
            json={"query": "test"},
            headers=auth_header(readonly_token),
        )
        assert resp.status_code == 403

    def test_get_search_results(self, app, readonly_token, mock_client):
        mock_client._search_results = [
            {"hubUrl": "dchub://hub.example.com", "file": "test.txt",
             "size": 1024, "freeSlots": 3, "totalSlots": 5,
             "tth": "ABC123", "nick": "user1", "isDirectory": False},
        ]
        resp = app.get("/api/search/results", headers=auth_header(readonly_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["results"][0]["file"] == "test.txt"

    def test_clear_search_results(self, app, admin_token, mock_client):
        mock_client._search_results = [{"file": "x"}]
        resp = app.delete("/api/search/results", headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert len(mock_client._search_results) == 0

    def test_clear_search_results_readonly_denied(self, app, readonly_token):
        resp = app.delete("/api/search/results", headers=auth_header(readonly_token))
        assert resp.status_code == 403


# ============================================================================
# Queue tests
# ============================================================================

class TestQueueEndpoints:
    """Tests for download queue endpoints."""

    def test_add_to_queue(self, app, admin_token):
        resp = app.post(
            "/api/queue",
            json={
                "directory": "/downloads",
                "name": "test.bin",
                "size": 1048576,
                "tth": "ABCDEF1234567890",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    def test_add_magnet(self, app, admin_token):
        resp = app.post(
            "/api/queue/magnet",
            json={"magnet": "magnet:?xt=urn:tree:tiger:ABC&dn=test.bin&xl=1024"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    def test_add_to_queue_readonly_denied(self, app, readonly_token):
        resp = app.post(
            "/api/queue",
            json={
                "directory": "/downloads",
                "name": "test.bin",
                "size": 1024,
                "tth": "ABC",
            },
            headers=auth_header(readonly_token),
        )
        assert resp.status_code == 403

    def test_list_queue(self, app, admin_token, readonly_token):
        # Add something
        app.post(
            "/api/queue",
            json={
                "directory": "/downloads",
                "name": "queued.bin",
                "size": 2048,
                "tth": "TTH123",
            },
            headers=auth_header(admin_token),
        )
        # Readonly can list
        resp = app.get("/api/queue", headers=auth_header(readonly_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    def test_remove_from_queue(self, app, admin_token, mock_client):
        mock_client._queue.append({
            "target": "/downloads/removeme.bin",
            "size": 512, "downloadedBytes": 0,
            "priority": 3, "tth": "XYZ",
        })
        resp = app.delete(
            "/api/queue/%2Fdownloads%2Fremoveme.bin",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    def test_clear_queue(self, app, admin_token, mock_client):
        mock_client._queue.append({"target": "/a", "size": 1,
                                    "downloadedBytes": 0, "priority": 3, "tth": ""})
        resp = app.delete("/api/queue", headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert len(mock_client._queue) == 0

    def test_clear_queue_readonly_denied(self, app, readonly_token):
        resp = app.delete("/api/queue", headers=auth_header(readonly_token))
        assert resp.status_code == 403


# ============================================================================
# Share tests
# ============================================================================

class TestShareEndpoints:
    """Tests for share management endpoints."""

    def test_add_share(self, app, admin_token):
        resp = app.post(
            "/api/shares",
            json={"real_path": "/home/user/shared", "virtual_name": "MyFiles"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    def test_add_share_readonly_denied(self, app, readonly_token):
        resp = app.post(
            "/api/shares",
            json={"real_path": "/tmp/share", "virtual_name": "Tmp"},
            headers=auth_header(readonly_token),
        )
        assert resp.status_code == 403

    def test_list_shares(self, app, admin_token, readonly_token, mock_client):
        mock_client._shares = [
            {"realPath": "/home/shared", "virtualName": "Shared", "size": 1024},
        ]
        resp = app.get("/api/shares", headers=auth_header(readonly_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["shares"][0]["virtual_name"] == "Shared"

    def test_remove_share(self, app, admin_token, mock_client):
        mock_client._shares = [
            {"realPath": "/home/remove", "virtualName": "Remove", "size": 0},
        ]
        resp = app.delete(
            "/api/shares",
            params={"real_path": "/home/remove"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    def test_refresh_share(self, app, admin_token):
        resp = app.post("/api/shares/refresh", headers=auth_header(admin_token))
        assert resp.status_code == 200

    def test_refresh_share_readonly_denied(self, app, readonly_token):
        resp = app.post("/api/shares/refresh", headers=auth_header(readonly_token))
        assert resp.status_code == 403


# ============================================================================
# Settings tests
# ============================================================================

class TestSettingsEndpoints:
    """Tests for DC client settings endpoints."""

    def test_get_setting(self, app, readonly_token, mock_client):
        mock_client._settings["Nick"] = "TestBot"
        resp = app.get("/api/settings/Nick", headers=auth_header(readonly_token))
        assert resp.status_code == 200
        assert resp.json()["value"] == "TestBot"

    def test_set_setting(self, app, admin_token, mock_client):
        resp = app.put(
            "/api/settings/Nick",
            json={"name": "Nick", "value": "NewBot"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert mock_client._settings["Nick"] == "NewBot"

    def test_set_setting_readonly_denied(self, app, readonly_token):
        resp = app.put(
            "/api/settings/Nick",
            json={"name": "Nick", "value": "Hacked"},
            headers=auth_header(readonly_token),
        )
        assert resp.status_code == 403

    def test_batch_settings(self, app, admin_token, mock_client):
        resp = app.post(
            "/api/settings/batch",
            json={"settings": [
                {"name": "Nick", "value": "Bot1"},
                {"name": "Description", "value": "Test bot"},
            ]},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert mock_client._settings["Nick"] == "Bot1"
        assert mock_client._settings["Description"] == "Test bot"

    def test_reload_config(self, app, admin_token):
        resp = app.post("/api/settings/reload", headers=auth_header(admin_token))
        assert resp.status_code == 200

    def test_restart_networking(self, app, admin_token):
        resp = app.post("/api/settings/networking", headers=auth_header(admin_token))
        assert resp.status_code == 200


# ============================================================================
# Status tests
# ============================================================================

class TestStatusEndpoints:
    """Tests for status and health endpoints."""

    def test_health_check_no_auth(self, app):
        resp = app.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_system_status(self, app, readonly_token):
        resp = app.get("/api/status", headers=auth_header(readonly_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "2.4.2-test"
        assert data["initialized"] is True
        assert "uptime_seconds" in data

    def test_system_status_unauthenticated(self, app):
        resp = app.get("/api/status")
        assert resp.status_code == 401

    def test_transfer_stats(self, app, readonly_token):
        resp = app.get("/api/status/transfers", headers=auth_header(readonly_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["download_speed"] == 1024
        assert data["upload_speed"] == 512

    def test_hashing_status(self, app, readonly_token):
        resp = app.get("/api/status/hashing", headers=auth_header(readonly_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["files_left"] == 5
        assert data["is_paused"] is False

    def test_pause_hashing(self, app, admin_token, mock_client):
        resp = app.post(
            "/api/status/hashing/pause",
            params={"pause": True},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert mock_client._hashing_paused is True

    def test_pause_hashing_readonly_denied(self, app, readonly_token):
        resp = app.post(
            "/api/status/hashing/pause",
            headers=auth_header(readonly_token),
        )
        assert resp.status_code == 403

    def test_shutdown_admin(self, app, admin_token):
        """Admin can trigger shutdown (sends SIGTERM to self)."""
        import os
        import signal
        from unittest.mock import patch

        with patch("os.kill") as mock_kill:
            resp = app.post("/api/shutdown", headers=auth_header(admin_token))
            assert resp.status_code == 200
            assert resp.json()["message"] == "Shutdown initiated"
            mock_kill.assert_called_once_with(os.getpid(), signal.SIGTERM)

    def test_shutdown_readonly_denied(self, app, readonly_token):
        resp = app.post("/api/shutdown", headers=auth_header(readonly_token))
        assert resp.status_code == 403

    def test_shutdown_unauthenticated(self, app):
        resp = app.post("/api/shutdown")
        assert resp.status_code == 401


# ============================================================================
# RBAC comprehensive tests
# ============================================================================

class TestRoleBasedAccess:
    """
    Comprehensive role-based access control tests.
    Verifies that readonly users can only read, not write.
    """

    ADMIN_ONLY_ENDPOINTS = [
        ("POST", "/api/hubs/connect", {"url": "dchub://x"}),
        ("POST", "/api/hubs/disconnect", {"url": "dchub://x"}),
        ("POST", "/api/chat/message", {"hub_url": "x", "message": "y"}),
        ("POST", "/api/chat/pm", {"hub_url": "x", "nick": "n", "message": "y"}),
        ("POST", "/api/search", {"query": "test"}),
        ("DELETE", "/api/search/results", None),
        ("POST", "/api/queue", {"directory": "/d", "name": "f", "size": 1, "tth": "t"}),
        ("POST", "/api/queue/magnet", {"magnet": "magnet:?xt=urn:tree:tiger:X"}),
        ("DELETE", "/api/queue", None),
        ("POST", "/api/shares", {"real_path": "/p", "virtual_name": "v"}),
        ("POST", "/api/shares/refresh", None),
        ("POST", "/api/settings/batch", {"settings": []}),
        ("POST", "/api/settings/reload", None),
        ("POST", "/api/settings/networking", None),
        ("POST", "/api/status/hashing/pause", None),
        ("POST", "/api/shutdown", None),
        ("POST", "/api/auth/users", {"username": "x", "password": "password123", "role": "readonly"}),
        ("GET", "/api/auth/users", None),
    ]

    READONLY_ALLOWED_ENDPOINTS = [
        ("GET", "/api/hubs", None),
        ("GET", "/api/chat/history?hub_url=x", None),
        ("GET", "/api/search/results", None),
        ("GET", "/api/queue", None),
        ("GET", "/api/shares", None),
        ("GET", "/api/settings/Nick", None),
        ("GET", "/api/status", None),
        ("GET", "/api/status/transfers", None),
        ("GET", "/api/status/hashing", None),
        ("GET", "/api/auth/me", None),
    ]

    def test_readonly_blocked_from_admin_endpoints(self, app, readonly_token):
        """Readonly users should get 403 on all admin-only endpoints."""
        for method, path, body in self.ADMIN_ONLY_ENDPOINTS:
            kwargs = {"headers": auth_header(readonly_token)}
            if body:
                kwargs["json"] = body
            if method == "POST":
                resp = app.post(path, **kwargs)
            elif method == "DELETE":
                resp = app.delete(path, **kwargs)
            elif method == "PUT":
                resp = app.put(path, **kwargs)
            else:
                resp = app.get(path, **kwargs)

            assert resp.status_code == 403, (
                f"Expected 403 for readonly on {method} {path}, "
                f"got {resp.status_code}: {resp.text}"
            )

    def test_readonly_allowed_on_read_endpoints(self, app, readonly_token):
        """Readonly users should be able to access read-only endpoints."""
        for method, path, body in self.READONLY_ALLOWED_ENDPOINTS:
            kwargs = {"headers": auth_header(readonly_token)}
            if body:
                kwargs["json"] = body
            resp = app.get(path, **kwargs)
            assert resp.status_code in (200, 503), (
                f"Expected 200/503 for readonly on {method} {path}, "
                f"got {resp.status_code}: {resp.text}"
            )

    def test_unauthenticated_blocked(self, app):
        """All endpoints except /api/health and /api/auth/login require auth."""
        protected = [
            "/api/hubs", "/api/chat/history?hub_url=x",
            "/api/search/results", "/api/queue", "/api/shares",
            "/api/status", "/api/auth/me",
        ]
        for path in protected:
            resp = app.get(path)
            assert resp.status_code == 401, (
                f"Expected 401 for unauthenticated GET {path}, "
                f"got {resp.status_code}"
            )

    def test_public_endpoints_no_auth(self, app):
        """Health and login should work without auth."""
        resp = app.get("/api/health")
        assert resp.status_code == 200

        resp = app.post("/api/auth/login", json={
            "username": "admin", "password": "adminpass123",
        })
        assert resp.status_code == 200


# ============================================================================
# User store persistence tests
# ============================================================================

class TestUserStorePersistence:
    """Tests for user store JSON persistence."""

    def test_persist_and_reload(self, tmp_path):
        path = tmp_path / "users.json"

        # Create store and add users
        store1 = UserStore(persist_path=path)
        store1.create_user("alice", "password123", UserRole.admin)
        store1.create_user("bob", "password456", UserRole.readonly)

        # Create new store from same file
        store2 = UserStore(persist_path=path)
        assert store2.user_count() == 2
        assert store2.get_user("alice").role == UserRole.admin
        assert store2.get_user("bob").role == UserRole.readonly

    def test_authenticate_after_reload(self, tmp_path):
        path = tmp_path / "users.json"

        store1 = UserStore(persist_path=path)
        store1.create_user("charlie", "mypassword1", UserRole.readonly)

        store2 = UserStore(persist_path=path)
        user = store2.authenticate("charlie", "mypassword1")
        assert user is not None
        assert user.username == "charlie"

    def test_no_persist_path(self):
        """Store works without persistence (in-memory only)."""
        store = UserStore()
        store.create_user("temp", "password123", UserRole.admin)
        assert store.user_count() == 1


# ============================================================================
# Auth manager unit tests
# ============================================================================

class TestAuthManager:
    """Unit tests for AuthManager."""

    def test_create_and_verify_token(self, auth_manager, user_store):
        user_store.create_user("tokentest", "password1", UserRole.readonly)
        token, expires = auth_manager.create_token("tokentest", UserRole.readonly)

        payload = auth_manager.verify_token(token)
        assert payload is not None
        assert payload["sub"] == "tokentest"
        assert payload["role"] == "readonly"

    def test_verify_invalid_token(self, auth_manager):
        assert auth_manager.verify_token("not.a.valid.jwt") is None

    def test_verify_wrong_secret(self, auth_manager):
        from jose import jwt
        token = jwt.encode(
            {"sub": "admin", "role": "admin", "exp": 9999999999},
            "wrong-secret",
            algorithm="HS256",
        )
        assert auth_manager.verify_token(token) is None

    def test_login_returns_token(self, auth_manager, user_store):
        user_store.create_user("logintest", "password1", UserRole.admin)
        result = auth_manager.login("logintest", "password1")
        assert result is not None
        token, expires_in, role = result
        assert len(token) > 0
        assert expires_in > 0
        assert role == UserRole.admin

    def test_login_wrong_password(self, auth_manager, user_store):
        user_store.create_user("logintest2", "correct1!", UserRole.readonly)
        assert auth_manager.login("logintest2", "wrong") is None

    def test_login_nonexistent(self, auth_manager):
        assert auth_manager.login("nobody", "pass") is None

    def test_ensure_admin_creates_user(self, auth_manager, user_store):
        auth_manager.ensure_admin_exists("superadmin", "superpass1")
        user = user_store.get_user("superadmin")
        assert user is not None
        assert user.role == UserRole.admin

    def test_ensure_admin_upgrades_role(self, auth_manager, user_store):
        user_store.create_user("downgraded", "password1", UserRole.readonly)
        auth_manager.ensure_admin_exists("downgraded", "password1")
        user = user_store.get_user("downgraded")
        assert user.role == UserRole.admin


# ============================================================================
# No DC client (auth-only mode) tests
# ============================================================================

class TestNoDCClient:
    """Tests that the API works without a DC client (auth-only mode)."""

    @pytest.fixture
    def app_no_client(self, auth_manager):
        application = create_app(
            auth_manager=auth_manager,
            dc_client=None,
            admin_username="admin",
            admin_password="adminpass123",
        )
        return TestClient(application)

    def test_health_works(self, app_no_client):
        resp = app_no_client.get("/api/health")
        assert resp.status_code == 200

    def test_login_works(self, app_no_client):
        resp = app_no_client.post("/api/auth/login", json={
            "username": "admin", "password": "adminpass123",
        })
        assert resp.status_code == 200

    def test_hub_endpoints_return_503(self, app_no_client):
        resp = app_no_client.post("/api/auth/login", json={
            "username": "admin", "password": "adminpass123",
        })
        token = resp.json()["access_token"]

        resp = app_no_client.get("/api/hubs", headers=auth_header(token))
        assert resp.status_code == 503

    def test_status_returns_uninitialized(self, app_no_client):
        resp = app_no_client.post("/api/auth/login", json={
            "username": "admin", "password": "adminpass123",
        })
        token = resp.json()["access_token"]

        resp = app_no_client.get("/api/status", headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["initialized"] is False
