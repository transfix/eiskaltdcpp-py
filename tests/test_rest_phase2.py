"""
Tests for Phase 2 REST API routes.

Tests the new endpoint groups: favorites, throttle, connectivity,
crypto, logs, finished, ipfilter, adl.

Uses FastAPI TestClient with mocked DC client dependencies.
"""
from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from fastapi.testclient import TestClient

from eiskaltdcpp.api.app import create_app
from eiskaltdcpp.api.auth import AuthManager, UserStore


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def user_store(tmp_path):
    return UserStore(persist_path=tmp_path / "users.json")


@pytest.fixture
def auth_manager(user_store):
    return AuthManager(
        user_store=user_store,
        secret_key="test-api-secret-key",
        token_expire_minutes=60,
    )


def _make_mock_client():
    """Create a mock DC client with manager stubs."""
    client = MagicMock()
    client.is_initialized = True

    # FavoriteManager mock
    fm = MagicMock()
    fm.getFavoriteHubs.return_value = []
    fm.isFavoriteHub.return_value = False
    fm.getFavoriteDirs.return_value = []
    fm.addFavoriteDir.return_value = True
    fm.removeFavoriteDir.return_value = True
    client.favorites = fm

    # ThrottleManager mock
    tm = MagicMock()
    tm.getUpLimit.return_value = 0
    tm.getDownLimit.return_value = 0
    client.throttle = tm

    # SettingsManager mock
    sm = MagicMock()
    client.settings = sm

    # ConnectivityManager mock
    cm = MagicMock()
    cm.isRunning.return_value = False
    client.connectivity = cm

    # CryptoManager mock
    crypto = MagicMock()
    crypto.TLSOk.return_value = True
    crypto.loadCertificates.return_value = True
    client.crypto = crypto

    # LogManager mock
    lm = MagicMock()
    lm.getPath.return_value = "/var/log/dc/main.log"
    client.logs = lm

    # FinishedManager mock
    finished = MagicMock()
    client.finished = finished

    # IPFilter mock
    ipf = MagicMock()
    ipf.OK.return_value = True
    client.ip_filter = ipf

    # ADLSearchManager mock
    am = MagicMock()
    am.collection = []
    client.adl_search = am

    return client


@pytest.fixture
def mock_client():
    return _make_mock_client()


@pytest.fixture
def app(auth_manager, mock_client):
    application = create_app(
        auth_manager=auth_manager,
        dc_client=mock_client,
        admin_username="admin",
        admin_password="adminpass123",
    )
    return TestClient(application)


@pytest.fixture
def admin_token(app) -> str:
    resp = app.post("/api/auth/login", json={
        "username": "admin",
        "password": "adminpass123",
    })
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
def admin_headers(admin_token) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}


# ============================================================================
# Favorites routes
# ============================================================================

class TestFavoritesAPI:
    def test_list_favorite_hubs_empty(self, app, admin_headers):
        resp = app.get("/api/favorites/hubs", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["hubs"] == []

    def test_list_favorite_dirs_empty(self, app, admin_headers):
        resp = app.get("/api/favorites/dirs", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_add_favorite_dir(self, app, admin_headers, mock_client):
        resp = app.post("/api/favorites/dirs", json={
            "path": "/data/shares",
            "name": "MyShares",
        }, headers=admin_headers)
        assert resp.status_code == 200
        mock_client.favorites.addFavoriteDir.assert_called_once_with(
            "/data/shares", "MyShares"
        )

    def test_remove_favorite_dir(self, app, admin_headers, mock_client):
        resp = app.delete(
            "/api/favorites/dirs", params={"name": "MyShares"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        mock_client.favorites.removeFavoriteDir.assert_called_once_with("MyShares")

    def test_remove_favorite_dir_not_found(self, app, admin_headers, mock_client):
        mock_client.favorites.removeFavoriteDir.return_value = False
        resp = app.delete(
            "/api/favorites/dirs", params={"name": "NoSuchDir"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_unauthenticated_rejected(self, app):
        resp = app.get("/api/favorites/hubs")
        assert resp.status_code in (401, 403)


# ============================================================================
# Throttle routes
# ============================================================================

class TestThrottleAPI:
    def test_get_throttle(self, app, admin_headers):
        resp = app.get("/api/throttle", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["upload_limit"] == 0
        assert data["download_limit"] == 0

    def test_set_throttle(self, app, admin_headers, mock_client):
        resp = app.put("/api/throttle", json={
            "upload_limit": 512,
            "download_limit": 1024,
        }, headers=admin_headers)
        assert resp.status_code == 200

    def test_unauthenticated_rejected(self, app):
        resp = app.get("/api/throttle")
        assert resp.status_code in (401, 403)


# ============================================================================
# Connectivity routes
# ============================================================================

class TestConnectivityAPI:
    def test_get_status(self, app, admin_headers):
        resp = app.get("/api/connectivity/status", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False

    def test_detect_connection(self, app, admin_headers, mock_client):
        resp = app.post("/api/connectivity/detect", headers=admin_headers)
        assert resp.status_code == 200
        mock_client.connectivity.detectConnection.assert_called_once()

    def test_setup(self, app, admin_headers, mock_client):
        resp = app.post("/api/connectivity/setup", headers=admin_headers)
        assert resp.status_code == 200
        mock_client.connectivity.setup.assert_called_once_with(True)


# ============================================================================
# Crypto routes
# ============================================================================

class TestCryptoAPI:
    def test_get_status(self, app, admin_headers):
        resp = app.get("/api/crypto/status", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["tls_ok"] is True

    def test_generate_certificate(self, app, admin_headers, mock_client):
        resp = app.post("/api/crypto/certificate/generate", headers=admin_headers)
        assert resp.status_code == 200
        mock_client.crypto.generateCertificate.assert_called_once()

    def test_reload_certificates(self, app, admin_headers, mock_client):
        resp = app.post("/api/crypto/certificate/reload", headers=admin_headers)
        assert resp.status_code == 200
        mock_client.crypto.loadCertificates.assert_called_once()

    def test_reload_certificates_failure(self, app, admin_headers, mock_client):
        mock_client.crypto.loadCertificates.return_value = False
        resp = app.post("/api/crypto/certificate/reload", headers=admin_headers)
        assert resp.status_code == 500


# ============================================================================
# Logs routes
# ============================================================================

class TestLogsAPI:
    def test_get_log_path(self, app, admin_headers, mock_client):
        resp = app.get("/api/logs/path/0", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == "/var/log/dc/main.log"
        mock_client.logs.getPath.assert_called_once_with(0)


# ============================================================================
# Finished routes
# ============================================================================

class TestFinishedAPI:
    def test_clear_downloads(self, app, admin_headers, mock_client):
        resp = app.delete("/api/finished/downloads", headers=admin_headers)
        assert resp.status_code == 200
        mock_client.finished.removeAll.assert_called()

    def test_clear_uploads(self, app, admin_headers, mock_client):
        resp = app.delete("/api/finished/uploads", headers=admin_headers)
        assert resp.status_code == 200


# ============================================================================
# IP Filter routes
# ============================================================================

class TestIPFilterAPI:
    def test_check_ip_allowed(self, app, admin_headers, mock_client):
        resp = app.post("/api/ipfilter/check", json={
            "ip": "192.168.1.1",
            "direction": 0,
        }, headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ip"] == "192.168.1.1"
        assert data["allowed"] is True

    def test_check_ip_blocked(self, app, admin_headers, mock_client):
        mock_client.ip_filter.OK.return_value = False
        resp = app.post("/api/ipfilter/check", json={
            "ip": "10.0.0.1",
            "direction": 1,
        }, headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["allowed"] is False


# ============================================================================
# ADL Search routes
# ============================================================================

class TestADLSearchAPI:
    def test_list_empty(self, app, admin_headers):
        resp = app.get("/api/adl/searches", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["searches"] == []

    def test_delete_out_of_range(self, app, admin_headers):
        resp = app.delete("/api/adl/searches/99", headers=admin_headers)
        assert resp.status_code == 404
