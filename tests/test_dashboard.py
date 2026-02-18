"""
Tests for the web dashboard (dashboard.py).

Covers:
- Dashboard HTML response at /dashboard
- Catch-all route for SPA
- HTML content checks (Bulma CSS, login form, tabs, WebSocket JS)
- Content-Type header
"""
from __future__ import annotations

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
        secret_key="test-dash-secret",
        token_expire_minutes=60,
    )


@pytest.fixture
def app(auth_manager):
    application = create_app(
        auth_manager=auth_manager,
        dc_client=None,
        admin_username="admin",
        admin_password="adminpass123",
    )
    return TestClient(application)


# ============================================================================
# Dashboard endpoint tests
# ============================================================================

class TestDashboardEndpoint:
    """Tests for GET /dashboard."""

    def test_dashboard_returns_html(self, app):
        resp = app.get("/dashboard")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_dashboard_contains_html_structure(self, app):
        html = app.get("/dashboard").text
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_dashboard_has_title(self, app):
        html = app.get("/dashboard").text
        assert "<title>eiskaltdcpp-py Dashboard</title>" in html

    def test_dashboard_includes_bulma_css(self, app):
        html = app.get("/dashboard").text
        assert "bulma@0.9.4" in html

    def test_dashboard_includes_fontawesome(self, app):
        html = app.get("/dashboard").text
        assert "font-awesome" in html

    def test_dashboard_has_login_page(self, app):
        html = app.get("/dashboard").text
        assert 'id="login-page"' in html
        assert 'id="login-user"' in html
        assert 'id="login-pass"' in html
        assert "doLogin()" in html

    def test_dashboard_has_app_page(self, app):
        html = app.get("/dashboard").text
        assert 'id="app-page"' in html

    def test_dashboard_has_navigation_tabs(self, app):
        html = app.get("/dashboard").text
        for tab in ("dashboard", "hubs", "chat", "search", "queue", "shares", "settings"):
            assert f"showTab('{tab}')" in html

    def test_dashboard_has_stat_cards(self, app):
        html = app.get("/dashboard").text
        assert 'id="stat-hubs"' in html
        assert 'id="stat-share"' in html
        assert 'id="stat-queue"' in html
        assert 'id="stat-uptime"' in html

    def test_dashboard_has_theme_toggle(self, app):
        html = app.get("/dashboard").text
        assert "toggleTheme()" in html
        assert 'data-theme="dark"' in html

    def test_dashboard_has_websocket_code(self, app):
        html = app.get("/dashboard").text
        assert "connectWebSocket()" in html
        assert "/ws/events" in html
        assert "WebSocket" in html

    def test_dashboard_has_hub_management(self, app):
        html = app.get("/dashboard").text
        assert "connectHub()" in html
        assert "disconnectHub(" in html
        assert 'id="hub-url-input"' in html

    def test_dashboard_has_chat_section(self, app):
        html = app.get("/dashboard").text
        assert 'id="chat-log"' in html
        assert 'id="chat-input"' in html
        assert "sendChat()" in html

    def test_dashboard_has_search_section(self, app):
        html = app.get("/dashboard").text
        assert 'id="search-input"' in html
        assert "doSearch()" in html
        assert 'id="search-results-table"' in html

    def test_dashboard_has_queue_section(self, app):
        html = app.get("/dashboard").text
        assert 'id="queue-table"' in html
        assert "refreshQueue()" in html

    def test_dashboard_has_shares_section(self, app):
        html = app.get("/dashboard").text
        assert 'id="shares-table"' in html
        assert "addShare()" in html

    def test_dashboard_has_settings_section(self, app):
        html = app.get("/dashboard").text
        assert 'id="setting-name"' in html
        assert "getSetting()" in html
        assert "setSetting()" in html

    def test_dashboard_has_event_log(self, app):
        html = app.get("/dashboard").text
        assert 'id="event-log"' in html

    def test_dashboard_has_logout(self, app):
        html = app.get("/dashboard").text
        assert "doLogout()" in html

    def test_dashboard_has_css_variables(self, app):
        html = app.get("/dashboard").text
        assert "--dc-primary: #00d1b2" in html
        assert "--dc-dark-bg:" in html

    def test_dashboard_has_api_helper(self, app):
        """Dashboard JS should have an api() helper for REST calls."""
        html = app.get("/dashboard").text
        assert "async function api(" in html or "function api(" in html

    def test_dashboard_has_format_helpers(self, app):
        html = app.get("/dashboard").text
        assert "formatBytes(" in html
        assert "formatSpeed(" in html
        assert "formatUptime(" in html

    def test_dashboard_no_auth_required(self, app):
        """Dashboard page itself should not require auth (SPA handles it)."""
        resp = app.get("/dashboard")
        assert resp.status_code == 200


class TestDashboardCatchAll:
    """Tests for dashboard catch-all route."""

    def test_catchall_returns_html(self, app):
        resp = app.get("/dashboard/some/path")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_catchall_returns_same_spa(self, app):
        main = app.get("/dashboard").text
        catchall = app.get("/dashboard/hubs").text
        assert main == catchall

    def test_catchall_deep_path(self, app):
        resp = app.get("/dashboard/settings/advanced/network")
        assert resp.status_code == 200
        assert "eiskaltdcpp-py Dashboard" in resp.text
