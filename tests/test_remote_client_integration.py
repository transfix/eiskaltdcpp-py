"""
RemoteDCClient integration tests.

End-to-end tests that spin up a real FastAPI server (in-process via ASGI
transport) with a mock DC client behind it, then exercise every method of
``RemoteDCClient`` against that server — verifying full round-trip
behaviour through the HTTP/JSON layer.

These tests complement the unit tests in ``test_client.py`` by using
the actual API routes and auth flow rather than mocking httpx calls.

Run:
    PYTHONPATH=build/python pytest tests/test_remote_client_integration.py -v
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from eiskaltdcpp.api.app import create_app
from eiskaltdcpp.api.auth import AuthManager, UserStore
from eiskaltdcpp.api.client import (
    HashStatus,
    HubInfo,
    QueueItemInfo,
    RemoteDCClient,
    SearchResultInfo,
    ShareInfoData,
    TransferStats,
    UserInfo,
)

# ============================================================================
# Mock DC client — mirrors the one in test_client.py
# ============================================================================


class _Obj:
    """Dict → attribute-access wrapper."""

    def __init__(self, d: dict):
        self.__dict__.update(d)


class MockDCClient:
    """Minimal mock that satisfies all route handlers."""

    def __init__(self):
        self.is_initialized = True
        self.version = "2.4.2-integ"
        self._hubs: list[dict] = []
        self._users: dict[str, list[dict]] = {}
        self._chat_history: dict[str, list[str]] = {}
        self._search_results: list[dict] = []
        self._queue: list[dict] = []
        self._shares: list[dict] = []
        self._settings: dict[str, str] = {"Nick": "TestBot"}
        self._share_size = 2_000_000_000
        self._shared_files = 99
        self._hashing_paused = False

    # -- Hubs --
    async def connect(self, url, encoding=""):
        self._hubs.append({"url": url, "name": f"Hub-{url}",
                           "connected": True, "userCount": 3})

    async def disconnect(self, url):
        self._hubs = [h for h in self._hubs if h["url"] != url]

    def list_hubs(self):
        return [_Obj(h) for h in self._hubs]

    def is_connected(self, url):
        return any(h["url"] == url for h in self._hubs)

    # -- Chat --
    def send_message(self, hub_url, message):
        self._chat_history.setdefault(hub_url, []).append(message)

    def send_pm(self, hub_url, nick, message):
        pass

    def get_chat_history(self, hub_url, max_lines=100):
        return self._chat_history.get(hub_url, [])[:max_lines]

    def get_users(self, hub_url):
        return [_Obj(u) for u in self._users.get(hub_url, [])]

    # -- Search --
    def search(self, query, file_type=0, size_mode=0, size=0, hub_url=""):
        self._search_results.append({
            "hubUrl": hub_url or "test", "file": f"result-{query}.txt",
            "size": 12345, "freeSlots": 2, "totalSlots": 4,
            "tth": "AAAA", "nick": "Uploader", "isDirectory": False,
        })
        return True

    def get_search_results(self, hub_url=""):
        return [_Obj(r) for r in self._search_results]

    def clear_search_results(self, hub_url=""):
        self._search_results.clear()

    # -- Queue --
    def download(self, directory, name, size, tth, hub_url="", nick=""):
        self._queue.append({"target": f"{directory}/{name}", "size": size,
                            "downloadedBytes": 0, "priority": 3, "tth": tth})
        return True

    def download_magnet(self, magnet, download_dir=""):
        self._queue.append({"target": f"{download_dir}/magnet-dl",
                            "size": 0, "downloadedBytes": 0,
                            "priority": 3, "tth": ""})
        return True

    def remove_download(self, target):
        self._queue = [q for q in self._queue if q["target"] != target]

    def list_queue(self):
        return [_Obj(q) for q in self._queue]

    def clear_queue(self):
        self._queue.clear()

    def set_priority(self, target, priority):
        for q in self._queue:
            if q["target"] == target:
                q["priority"] = priority

    # -- Shares --
    def add_share(self, real_path, virtual_name):
        self._shares.append({"realPath": real_path,
                             "virtualName": virtual_name, "size": 0})
        return True

    def remove_share(self, real_path):
        before = len(self._shares)
        self._shares = [s for s in self._shares if s["realPath"] != real_path]
        return len(self._shares) < before

    def list_shares(self):
        return [_Obj(s) for s in self._shares]

    def refresh_share(self):
        pass

    @property
    def share_size(self):
        return self._share_size

    @property
    def shared_files(self):
        return self._shared_files

    # -- Settings --
    def get_setting(self, name):
        return self._settings.get(name, "")

    def set_setting(self, name, value):
        self._settings[name] = value

    def start_networking(self):
        pass

    def reload_config(self):
        pass

    # -- Transfers & Hashing --
    @property
    def transfer_stats(self):
        return _Obj({"downloadSpeed": 4096, "uploadSpeed": 2048,
                     "downloaded": 2097152, "uploaded": 1048576})

    @property
    def hash_status(self):
        return _Obj({"currentFile": "/data/video.mkv",
                     "filesLeft": 7, "bytesLeft": 5_000_000,
                     "isPaused": self._hashing_paused})

    def pause_hashing(self, pause=True):
        self._hashing_paused = pause

    @property
    def _sync_client(self):
        return self


# ============================================================================
# Fixtures
# ============================================================================

ADMIN_USER = "integadmin"
ADMIN_PASS = "integpass123"


@pytest.fixture
def mock_dc():
    return MockDCClient()


@pytest.fixture
def app(mock_dc, tmp_path):
    """Full FastAPI app with mock DC backend."""
    store = UserStore(persist_path=tmp_path / "users.json")
    auth = AuthManager(user_store=store, secret_key="integ-test-key",
                       token_expire_minutes=60)
    return create_app(
        auth_manager=auth,
        dc_client=mock_dc,
        admin_username=ADMIN_USER,
        admin_password=ADMIN_PASS,
    )


@pytest.fixture
def transport(app):
    return httpx.ASGITransport(app=app)


@pytest.fixture
async def client(transport) -> RemoteDCClient:
    """Authenticated RemoteDCClient talking to the in-process server."""
    c = RemoteDCClient("http://testserver",
                       username=ADMIN_USER, password=ADMIN_PASS)
    c._http = httpx.AsyncClient(transport=transport,
                                base_url="http://testserver")
    await c.login(ADMIN_USER, ADMIN_PASS)
    yield c
    await c.close()


@pytest.fixture
async def readonly_client(transport, client) -> RemoteDCClient:
    """A read-only client for RBAC tests."""
    # Use the admin client to create a readonly user
    await client.create_user("viewer", "viewerpass1", "readonly")

    c = RemoteDCClient("http://testserver",
                       username="viewer", password="viewerpass1")
    c._http = httpx.AsyncClient(transport=transport,
                                base_url="http://testserver")
    await c.login("viewer", "viewerpass1")
    yield c
    await c.close()


# ============================================================================
# Auth integration
# ============================================================================

class TestAuthIntegration:
    """Login, token usage, and user management round-trips."""

    async def test_login_returns_token(self, client):
        assert client._token is not None
        assert len(client._token) > 20

    async def test_login_bad_password_raises(self, transport):
        c = RemoteDCClient("http://testserver")
        c._http = httpx.AsyncClient(transport=transport,
                                    base_url="http://testserver")
        with pytest.raises(httpx.HTTPStatusError):
            await c.login(ADMIN_USER, "wrongwrong")
        await c.close()

    async def test_create_list_delete_user(self, client):
        await client.create_user("ephemeral", "ephemeral1", "readonly")
        users = await client.list_users()
        names = [u["username"] for u in users]
        assert "ephemeral" in names

        await client.delete_user("ephemeral")
        users = await client.list_users()
        names = [u["username"] for u in users]
        assert "ephemeral" not in names

    async def test_update_user_role(self, client):
        await client.create_user("upgrader", "upgrader123", "readonly")
        result = await client.update_user("upgrader", role="admin")
        assert result["role"] == "admin"
        await client.delete_user("upgrader")


# ============================================================================
# Hub operations
# ============================================================================

class TestHubIntegration:
    """Connect, disconnect, list hubs via RemoteDCClient."""

    async def test_connect_and_list(self, client, mock_dc):
        await client.connect("dchub://test-hub:411")
        hubs = await client.list_hubs_async()
        assert len(hubs) == 1
        assert isinstance(hubs[0], HubInfo)
        assert hubs[0].url == "dchub://test-hub:411"

    async def test_disconnect(self, client, mock_dc):
        await client.connect("dchub://temp:411")
        hubs = await client.list_hubs_async()
        assert len(hubs) == 1

        await client.disconnect("dchub://temp:411")
        hubs = await client.list_hubs_async()
        assert len(hubs) == 0

    async def test_is_connected(self, client, mock_dc):
        await client.connect("dchub://check:411")
        assert await client.is_connected_async("dchub://check:411")
        assert not await client.is_connected_async("dchub://nope:411")

    async def test_list_users_empty(self, client, mock_dc):
        await client.connect("dchub://empty:411")
        users = await client.get_users_async("dchub://empty:411")
        assert users == []

    async def test_list_users_populated(self, client, mock_dc):
        hub = "dchub://busy:411"
        await client.connect(hub)
        mock_dc._users[hub] = [
            {"nick": "Alice", "shareSize": 100, "description": "",
             "tag": "", "connection": "", "email": "", "hubUrl": hub},
            {"nick": "Bob", "shareSize": 200, "description": "",
             "tag": "", "connection": "", "email": "", "hubUrl": hub},
        ]
        users = await client.get_users_async(hub)
        assert len(users) == 2
        assert isinstance(users[0], UserInfo)
        nicks = {u.nick for u in users}
        assert nicks == {"Alice", "Bob"}


# ============================================================================
# Chat operations
# ============================================================================

class TestChatIntegration:
    """Send messages and retrieve history."""

    async def test_send_and_get_history(self, client, mock_dc):
        hub = "dchub://chat-hub:411"
        await client.connect(hub)
        await client.send_message_async(hub, "Hello world!")
        await client.send_message_async(hub, "Second message")

        history = await client.get_chat_history_async(hub)
        assert "Hello world!" in history
        assert "Second message" in history

    async def test_send_pm(self, client, mock_dc):
        hub = "dchub://pm-hub:411"
        await client.connect(hub)
        # Should not raise
        await client.send_pm_async(hub, "SomeUser", "Private hello")


# ============================================================================
# Search operations
# ============================================================================

class TestSearchIntegration:
    """Search, get results, clear results."""

    async def test_search_and_results(self, client, mock_dc):
        hub = "dchub://search:411"
        await client.connect(hub)

        ok = await client.search_async("test query")
        assert ok is True

        results = await client.get_search_results_async()
        assert len(results) >= 1
        assert isinstance(results[0], SearchResultInfo)
        assert "test query" in results[0].file

    async def test_clear_results(self, client, mock_dc):
        await client.connect("dchub://sr:411")
        await client.search_async("something")
        results = await client.get_search_results_async()
        assert len(results) > 0

        await client.clear_search_results_async()
        results = await client.get_search_results_async()
        assert len(results) == 0


# ============================================================================
# Queue operations
# ============================================================================

class TestQueueIntegration:
    """Download queue management round-trips."""

    async def test_download_and_list(self, client, mock_dc):
        ok = await client.download_async("/downloads", "file.bin",
                                         1024, "TTH123")
        assert ok is True

        queue = await client.list_queue_async()
        assert len(queue) == 1
        assert isinstance(queue[0], QueueItemInfo)
        assert "file.bin" in queue[0].target

    async def test_download_magnet(self, client, mock_dc):
        ok = await client.download_magnet_async(
            "magnet:?xt=urn:tree:tiger:ABCD&dn=test.bin", "/tmp")
        assert ok is True
        queue = await client.list_queue_async()
        assert len(queue) == 1

    async def test_remove_download(self, client, mock_dc):
        await client.download_async("/dl", "rm.bin", 100, "T1")
        queue = await client.list_queue_async()
        target = queue[0].target
        assert len(queue) == 1

        await client.remove_download_async(target)
        queue = await client.list_queue_async()
        assert len(queue) == 0

    async def test_clear_queue(self, client, mock_dc):
        await client.download_async("/dl", "a.bin", 100, "T1")
        await client.download_async("/dl", "b.bin", 200, "T2")
        queue = await client.list_queue_async()
        assert len(queue) == 2

        await client.clear_queue_async()
        queue = await client.list_queue_async()
        assert len(queue) == 0

    async def test_set_priority(self, client, mock_dc):
        await client.download_async("/dl", "prio.bin", 100, "T1")
        target = (await client.list_queue_async())[0].target
        # Should not raise
        await client.set_priority_async(target, 5)


# ============================================================================
# Share operations
# ============================================================================

class TestShareIntegration:
    """Share directory management round-trips."""

    async def test_add_and_list(self, client, mock_dc):
        ok = await client.add_share_async("/home/user/files", "MyFiles")
        assert ok is True

        shares = await client.list_shares_async()
        assert len(shares) == 1
        assert isinstance(shares[0], ShareInfoData)

    async def test_remove_share(self, client, mock_dc):
        await client.add_share_async("/tmp/share1", "Share1")
        await client.add_share_async("/tmp/share2", "Share2")
        shares = await client.list_shares_async()
        assert len(shares) == 2

        ok = await client.remove_share_async("/tmp/share1")
        assert ok is True
        shares = await client.list_shares_async()
        assert len(shares) == 1

    async def test_refresh_share(self, client):
        # Should not raise
        await client.refresh_share_async()

    async def test_get_share_size(self, client, mock_dc):
        size = await client.get_share_size()
        assert size == 2_000_000_000

    async def test_get_shared_files(self, client, mock_dc):
        count = await client.get_shared_files()
        assert count == 99


# ============================================================================
# Settings operations
# ============================================================================

class TestSettingsIntegration:
    """Get/set settings, reload, networking."""

    async def test_get_setting(self, client, mock_dc):
        val = await client.get_setting_async("Nick")
        assert val == "TestBot"

    async def test_set_setting(self, client, mock_dc):
        await client.set_setting_async("Nick", "NewBot")
        val = await client.get_setting_async("Nick")
        assert val == "NewBot"

    async def test_reload_config(self, client):
        await client.reload_config_async()  # should not raise

    async def test_start_networking(self, client):
        await client.start_networking_async()  # should not raise


# ============================================================================
# Transfer & hashing status
# ============================================================================

class TestTransfersIntegration:
    """Transfer stats and hashing status round-trips."""

    async def test_transfer_stats(self, client, mock_dc):
        stats = await client.get_transfer_stats()
        assert isinstance(stats, TransferStats)
        assert stats.download_speed == 4096 or stats.downloadSpeed == 4096

    async def test_hash_status(self, client, mock_dc):
        hs = await client.get_hash_status()
        assert isinstance(hs, HashStatus)
        assert hs.files_left == 7 or hs.filesLeft == 7

    async def test_pause_hashing(self, client, mock_dc):
        assert not mock_dc._hashing_paused
        await client.pause_hashing_async(True)
        assert mock_dc._hashing_paused
        await client.pause_hashing_async(False)
        assert not mock_dc._hashing_paused


# ============================================================================
# System status
# ============================================================================

class TestStatusIntegration:
    """Status and health endpoints."""

    async def test_get_status(self, client):
        status = await client.get_status()
        assert "version" in status

    async def test_health_check(self, client):
        ok = await client.health_check()
        assert ok is True


# ============================================================================
# RBAC — readonly client should be denied on write endpoints
# ============================================================================

class TestRBACIntegration:
    """Read-only users cannot call write endpoints."""

    async def test_readonly_can_list_hubs(self, readonly_client, mock_dc):
        hubs = await readonly_client.list_hubs_async()
        assert isinstance(hubs, list)

    async def test_readonly_cannot_connect(self, readonly_client):
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await readonly_client.connect("dchub://nope:411")
        assert exc_info.value.response.status_code == 403

    async def test_readonly_cannot_send_chat(self, readonly_client, mock_dc):
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await readonly_client.send_message_async("dchub://x:411", "hi")
        assert exc_info.value.response.status_code == 403

    async def test_readonly_can_get_status(self, readonly_client):
        status = await readonly_client.get_status()
        assert "version" in status

    async def test_readonly_cannot_create_users(self, readonly_client):
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await readonly_client.create_user("hacker", "hacker123", "admin")
        assert exc_info.value.response.status_code == 403


# ============================================================================
# Context manager
# ============================================================================

class TestContextManagerIntegration:
    """async with RemoteDCClient(...) usage."""

    async def test_context_manager_lifecycle(self, transport):
        """Verify context manager opens and closes cleanly."""
        c = RemoteDCClient("http://testserver",
                           username=ADMIN_USER,
                           password=ADMIN_PASS)
        # Inject ASGI transport before entering context manager
        c._http = httpx.AsyncClient(transport=transport,
                                    base_url="http://testserver")
        async with c:
            status = await c.get_status()
            assert "version" in status
        # After exit, client should be closed
        assert c._http is None or c._http.is_closed


# ============================================================================
# Event handler registration
# ============================================================================

class TestEventHandlersIntegration:
    """on() / off() handler registration."""

    async def test_on_and_off(self, client):
        called = []

        @client.on("chat_message")
        def handler(data):
            called.append(data)

        assert "chat_message" in client._handlers
        assert handler in client._handlers["chat_message"]

        client.off("chat_message", handler)
        assert handler not in client._handlers["chat_message"]


# ============================================================================
# Full workflow — multi-step scenario
# ============================================================================

class TestFullWorkflow:
    """End-to-end scenario: login → connect → chat → search → queue."""

    async def test_complete_workflow(self, client, mock_dc):
        hub = "dchub://workflow:411"

        # 1. Connect
        await client.connect(hub)
        hubs = await client.list_hubs_async()
        assert len(hubs) == 1

        # 2. Chat
        await client.send_message_async(hub, "Hello from integration test!")
        history = await client.get_chat_history_async(hub)
        assert len(history) == 1

        # 3. Search
        ok = await client.search_async("integration test file")
        assert ok is True
        results = await client.get_search_results_async()
        assert len(results) >= 1

        # 4. Queue a download
        ok = await client.download_async("/tmp/dl", "test.bin", 9999, "TTH0")
        assert ok is True
        queue = await client.list_queue_async()
        assert len(queue) == 1

        # 5. Add a share
        ok = await client.add_share_async("/data/shared", "Shared")
        assert ok is True

        # 6. Check status
        status = await client.get_status()
        assert status.get("initialized") is True

        # 7. Clean up
        await client.clear_queue_async()
        await client.clear_search_results_async()
        await client.disconnect(hub)

        hubs = await client.list_hubs_async()
        assert len(hubs) == 0
        queue = await client.list_queue_async()
        assert len(queue) == 0
