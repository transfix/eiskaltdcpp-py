"""
Tests for the remote DC client wrapper (client.py).

Covers:
- Data classes (HubInfo, UserInfo, SearchResultInfo, etc.)
- RemoteDCClient lifecycle (login, close, context manager)
- All async API methods via a live in-process test server
- Sync method stubs raise TypeError
- RemoteEventStream data class
- Event handler registration (on/off)
- User management helpers
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from eiskaltdcpp.api.app import create_app
from eiskaltdcpp.api.auth import AuthManager, UserStore
from eiskaltdcpp.api.client import (
    HashStatus,
    HubInfo,
    QueueItemInfo,
    RemoteDCClient,
    RemoteEventStream,
    SearchResultInfo,
    ShareInfoData,
    TransferStats,
    UserInfo,
)
from eiskaltdcpp.api.models import UserRole


# ============================================================================
# Helpers
# ============================================================================

class _DictObj:
    """Wraps a dict to allow attribute access."""
    def __init__(self, d: dict):
        self.__dict__.update(d)


class MockDCClient:
    """Full mock DC client for the test server."""

    def __init__(self):
        self.is_initialized = True
        self.version = "2.4.2-test"
        self._hubs: list[dict] = []
        self._users: dict[str, list[dict]] = {}
        self._chat_history: dict[str, list[str]] = {}
        self._search_results: list[dict] = []
        self._queue: list[dict] = []
        self._shares: list[dict] = []
        self._settings: dict[str, str] = {"Nick": "TestUser"}
        self._share_size = 1073741824  # 1 GB
        self._shared_files = 42
        self._hashing_paused = False

    async def connect(self, url, encoding=""):
        self._hubs.append({"url": url, "name": f"Hub-{url}",
                           "connected": True, "userCount": 5})

    async def disconnect(self, url):
        self._hubs = [h for h in self._hubs if h["url"] != url]

    def list_hubs(self):
        return [_DictObj(h) for h in self._hubs]

    def is_connected(self, url):
        return any(h["url"] == url for h in self._hubs)

    def send_message(self, hub_url, message):
        self._chat_history.setdefault(hub_url, []).append(message)

    def send_pm(self, hub_url, nick, message):
        pass

    def get_chat_history(self, hub_url, max_lines=100):
        return self._chat_history.get(hub_url, [])[:max_lines]

    def get_users(self, hub_url):
        return [_DictObj(u) for u in self._users.get(hub_url, [])]

    def search(self, query, file_type=0, size_mode=0, size=0, hub_url=""):
        return len(self._hubs) > 0

    def get_search_results(self, hub_url=""):
        return [_DictObj(r) for r in self._search_results]

    def clear_search_results(self, hub_url=""):
        self._search_results.clear()

    def download(self, directory, name, size, tth, hub_url="", nick=""):
        self._queue.append({"target": f"{directory}/{name}", "size": size,
                            "downloadedBytes": 0, "priority": 3, "tth": tth})
        return True

    def download_magnet(self, magnet, download_dir=""):
        self._queue.append({"target": f"{download_dir}/magnet-file",
                            "size": 0, "downloadedBytes": 0,
                            "priority": 3, "tth": ""})
        return True

    def remove_download(self, target):
        self._queue = [q for q in self._queue if q["target"] != target]

    def list_queue(self):
        return [_DictObj(q) for q in self._queue]

    def clear_queue(self):
        self._queue.clear()

    def set_priority(self, target, priority):
        for q in self._queue:
            if q["target"] == target:
                q["priority"] = priority

    def add_share(self, real_path, virtual_name):
        self._shares.append({"realPath": real_path, "virtualName": virtual_name, "size": 0})
        return True

    def remove_share(self, real_path):
        before = len(self._shares)
        self._shares = [s for s in self._shares if s["realPath"] != real_path]
        return len(self._shares) < before

    def list_shares(self):
        return [_DictObj(s) for s in self._shares]

    def refresh_share(self):
        pass

    @property
    def share_size(self):
        return self._share_size

    @property
    def shared_files(self):
        return self._shared_files

    def get_setting(self, name):
        return self._settings.get(name, "")

    def set_setting(self, name, value):
        self._settings[name] = value

    def start_networking(self):
        pass

    def reload_config(self):
        pass

    @property
    def transfer_stats(self):
        return _DictObj({"downloadSpeed": 2048, "uploadSpeed": 1024,
                         "downloaded": 1048576, "uploaded": 524288})

    @property
    def hash_status(self):
        return _DictObj({"currentFile": "/tmp/test.bin",
                         "filesLeft": 3, "bytesLeft": 999999,
                         "isPaused": self._hashing_paused})

    def pause_hashing(self, pause=True):
        self._hashing_paused = pause

    @property
    def _sync_client(self):
        return self


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_dc():
    return MockDCClient()


@pytest.fixture
def test_app(mock_dc, tmp_path):
    """Create a FastAPI app with mock DC client."""
    store = UserStore(persist_path=tmp_path / "users.json")
    auth = AuthManager(user_store=store, secret_key="client-test-secret",
                       token_expire_minutes=60)
    return create_app(
        auth_manager=auth,
        dc_client=mock_dc,
        admin_username="admin",
        admin_password="adminpass123",
    )


@pytest.fixture
def transport(test_app):
    """Create an ASGI transport for httpx testing."""
    return httpx.ASGITransport(app=test_app)


@pytest.fixture
async def client(transport):
    """Create a RemoteDCClient connected to the test server."""
    c = RemoteDCClient(
        "http://testserver",
        username="admin",
        password="adminpass123",
    )
    # Override the httpx client to use ASGI transport
    c._http = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    await c.login("admin", "adminpass123")
    yield c
    await c.close()


# ============================================================================
# Data class tests
# ============================================================================

class TestHubInfo:
    def test_basic_creation(self):
        h = HubInfo(url="dchub://test:411", name="TestHub",
                    connected=True, user_count=5)
        assert h.url == "dchub://test:411"
        assert h.name == "TestHub"
        assert h.connected is True
        assert h.user_count == 5
        assert h.userCount == 5  # alias

    def test_defaults(self):
        h = HubInfo(url="x")
        assert h.name == ""
        assert h.connected is False
        assert h.user_count == 0


class TestUserInfo:
    def test_basic_creation(self):
        u = UserInfo(nick="Bob", share_size=1024, description="Hello")
        assert u.nick == "Bob"
        assert u.share_size == 1024
        assert u.shareSize == 1024  # alias
        assert u.description == "Hello"

    def test_defaults(self):
        u = UserInfo(nick="x")
        assert u.share_size == 0
        assert u.tag == ""
        assert u.hub_url == ""


class TestSearchResultInfo:
    def test_full_creation(self):
        sr = SearchResultInfo(
            hub_url="hub", file="/path/file.mp3",
            size=1048576, free_slots=3, total_slots=5,
            tth="ABCDEF", nick="user1", is_directory=False,
        )
        assert sr.file == "/path/file.mp3"
        assert sr.freeSlots == 3
        assert sr.totalSlots == 5
        assert sr.isDirectory is False


class TestQueueItemInfo:
    def test_creation(self):
        q = QueueItemInfo(target="/tmp/file.txt", size=1000,
                          downloaded=500, priority=3, tth="TTH123")
        assert q.target == "/tmp/file.txt"
        assert q.downloadedBytes == 500
        assert q.tth == "TTH123"


class TestShareInfoData:
    def test_creation(self):
        s = ShareInfoData(real_path="/data/shared",
                          virtual_name="Shared", size=9999)
        assert s.realPath == "/data/shared"
        assert s.virtualName == "Shared"
        assert s.size == 9999


class TestTransferStats:
    def test_creation(self):
        t = TransferStats(download_speed=100, upload_speed=50,
                          downloaded=999, uploaded=500)
        assert t.downloadSpeed == 100
        assert t.uploadSpeed == 50


class TestHashStatus:
    def test_creation(self):
        h = HashStatus(current_file="/tmp/f.bin", files_left=3,
                       bytes_left=1024, is_paused=True)
        assert h.currentFile == "/tmp/f.bin"
        assert h.filesLeft == 3
        assert h.isPaused is True


# ============================================================================
# RemoteEventStream tests
# ============================================================================

class TestRemoteEventStream:
    def test_initial_state(self):
        stream = RemoteEventStream("ws://test/ws", "token123", "events")
        assert stream._ws_url == "ws://test/ws"
        assert stream._token == "token123"
        assert stream._channels == "events"
        assert stream._ws is None
        assert stream._closed is False

    def test_aiter_returns_self(self):
        stream = RemoteEventStream("ws://test/ws", "tok")
        assert stream.__aiter__() is stream

    @pytest.mark.asyncio
    async def test_close_sets_closed(self):
        stream = RemoteEventStream("ws://test/ws", "tok")
        await stream.close()
        assert stream._closed is True

    @pytest.mark.asyncio
    async def test_anext_after_close_stops(self):
        stream = RemoteEventStream("ws://test/ws", "tok")
        await stream.close()
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()


# ============================================================================
# RemoteDCClient unit tests (no server)
# ============================================================================

class TestRemoteDCClientUnit:
    """Unit tests for RemoteDCClient without a running server."""

    def test_initial_state(self):
        c = RemoteDCClient("http://localhost:8080")
        assert c._base_url == "http://localhost:8080"
        assert c._token is None
        assert c.is_initialized is False
        assert c.version == "unknown"

    def test_base_url_trailing_slash_stripped(self):
        c = RemoteDCClient("http://localhost:8080/")
        assert c._base_url == "http://localhost:8080"

    def test_token_injection(self):
        c = RemoteDCClient("http://x", token="pre-set-token")
        assert c._token == "pre-set-token"

    def test_headers_with_token(self):
        c = RemoteDCClient("http://x", token="tok123")
        assert c._headers() == {"Authorization": "Bearer tok123"}

    def test_headers_without_token(self):
        c = RemoteDCClient("http://x")
        assert c._headers() == {}

    def test_events_returns_stream(self):
        c = RemoteDCClient("http://localhost:8080", token="t")
        stream = c.events("chat,search")
        assert isinstance(stream, RemoteEventStream)
        assert stream._channels == "chat,search"
        assert "ws://localhost:8080" in stream._ws_url

    def test_events_https_to_wss(self):
        c = RemoteDCClient("https://secure.host", token="t")
        stream = c.events()
        assert stream._ws_url.startswith("wss://")


class TestSyncMethodsRaiseTypeError:
    """All sync facade methods should raise TypeError with hint."""

    def test_list_hubs(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError, match="list_hubs_async"):
            c.list_hubs()

    def test_is_connected(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.is_connected("url")

    def test_send_message(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.send_message("url", "msg")

    def test_send_pm(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.send_pm("url", "nick", "msg")

    def test_get_chat_history(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.get_chat_history("url")

    def test_get_users(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.get_users("url")

    def test_search(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.search("query")

    def test_get_search_results(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.get_search_results()

    def test_clear_search_results(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.clear_search_results()

    def test_download(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.download("dir", "name", 0, "tth")

    def test_download_magnet(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.download_magnet("magnet:?xt=urn:tree:tiger:ABC")

    def test_remove_download(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.remove_download("target")

    def test_list_queue(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.list_queue()

    def test_clear_queue(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.clear_queue()

    def test_set_priority(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.set_priority("target", 3)

    def test_add_share(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.add_share("/path", "Name")

    def test_remove_share(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.remove_share("/path")

    def test_list_shares(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.list_shares()

    def test_refresh_share(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.refresh_share()

    def test_get_setting(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.get_setting("Nick")

    def test_set_setting(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.set_setting("Nick", "value")

    def test_reload_config(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.reload_config()

    def test_start_networking(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.start_networking()

    def test_pause_hashing(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            c.pause_hashing()

    def test_share_size_property(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            _ = c.share_size

    def test_shared_files_property(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            _ = c.shared_files

    def test_transfer_stats_property(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            _ = c.transfer_stats

    def test_hash_status_property(self):
        c = RemoteDCClient("http://x", token="t")
        with pytest.raises(TypeError):
            _ = c.hash_status


class TestEventHandlers:
    """Tests for event handler registration."""

    def test_on_decorator(self):
        c = RemoteDCClient("http://x")
        @c.on("chat_message")
        def handler(data):
            pass
        assert handler in c._handlers["chat_message"]

    def test_on_function(self):
        c = RemoteDCClient("http://x")
        def handler(data):
            pass
        c.on("hub_connected", handler)
        assert handler in c._handlers["hub_connected"]

    def test_off(self):
        c = RemoteDCClient("http://x")
        def handler(data):
            pass
        c.on("chat_message", handler)
        c.off("chat_message", handler)
        assert handler not in c._handlers.get("chat_message", [])

    def test_off_nonexistent_safe(self):
        c = RemoteDCClient("http://x")
        def handler(data):
            pass
        # Should not raise
        c.off("nonexistent_event", handler)


# ============================================================================
# RemoteDCClient integration tests (against test server)
# ============================================================================

class TestRemoteDCClientLogin:
    """Tests for login flow."""

    @pytest.mark.asyncio
    async def test_login_success(self, transport):
        c = RemoteDCClient("http://testserver")
        c._http = httpx.AsyncClient(transport=transport, base_url="http://testserver")
        token = await c.login("admin", "adminpass123")
        assert token
        assert c._token == token
        await c.close()

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, transport):
        c = RemoteDCClient("http://testserver")
        c._http = httpx.AsyncClient(transport=transport, base_url="http://testserver")
        with pytest.raises(httpx.HTTPStatusError):
            await c.login("admin", "wrongpassword")
        await c.close()

    @pytest.mark.asyncio
    async def test_context_manager_auto_login(self, transport):
        c = RemoteDCClient("http://testserver",
                           username="admin", password="adminpass123")
        c._http = httpx.AsyncClient(transport=transport, base_url="http://testserver")
        async with c:
            assert c._token is not None

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, transport):
        c = RemoteDCClient("http://testserver")
        c._http = httpx.AsyncClient(transport=transport, base_url="http://testserver")
        await c.login("admin", "adminpass123")
        await c.close()
        await c.close()  # should not raise


class TestRemoteDCClientHubs:
    """Tests for hub-related async methods."""

    @pytest.mark.asyncio
    async def test_list_hubs_empty(self, client):
        hubs = await client.list_hubs_async()
        assert hubs == []

    @pytest.mark.asyncio
    async def test_connect_and_list(self, client):
        await client.connect("dchub://test:411")
        hubs = await client.list_hubs_async()
        assert len(hubs) == 1
        assert isinstance(hubs[0], HubInfo)
        assert hubs[0].url == "dchub://test:411"
        assert hubs[0].connected is True

    @pytest.mark.asyncio
    async def test_disconnect(self, client):
        await client.connect("dchub://test:411")
        await client.disconnect("dchub://test:411")
        hubs = await client.list_hubs_async()
        assert len(hubs) == 0

    @pytest.mark.asyncio
    async def test_is_connected(self, client):
        await client.connect("dchub://test:411")
        assert await client.is_connected_async("dchub://test:411") is True
        assert await client.is_connected_async("dchub://other:411") is False

    @pytest.mark.asyncio
    async def test_multiple_hubs(self, client):
        await client.connect("dchub://hub1:411")
        await client.connect("dchub://hub2:411")
        hubs = await client.list_hubs_async()
        assert len(hubs) == 2


class TestRemoteDCClientChat:
    """Tests for chat async methods."""

    @pytest.mark.asyncio
    async def test_send_and_get_history(self, client):
        await client.connect("dchub://test:411")
        await client.send_message_async("dchub://test:411", "Hello world")
        history = await client.get_chat_history_async("dchub://test:411")
        assert "Hello world" in history

    @pytest.mark.asyncio
    async def test_send_pm(self, client):
        await client.connect("dchub://test:411")
        # Should not raise
        await client.send_pm_async("dchub://test:411", "Bob", "Hi Bob")

    @pytest.mark.asyncio
    async def test_empty_chat_history(self, client):
        history = await client.get_chat_history_async("dchub://empty:411")
        assert history == []


class TestRemoteDCClientSearch:
    """Tests for search async methods."""

    @pytest.mark.asyncio
    async def test_search_no_hubs_returns_false(self, client):
        result = await client.search_async("test query")
        # No hubs connected, mock returns False
        assert result is False

    @pytest.mark.asyncio
    async def test_search_with_hub(self, client):
        await client.connect("dchub://test:411")
        result = await client.search_async("test query")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_search_results_empty(self, client):
        results = await client.get_search_results_async()
        assert results == []

    @pytest.mark.asyncio
    async def test_clear_search_results(self, client):
        # Should not raise
        await client.clear_search_results_async()


class TestRemoteDCClientQueue:
    """Tests for queue async methods."""

    @pytest.mark.asyncio
    async def test_download_and_list(self, client):
        result = await client.download_async("/tmp", "file.txt", 1024, "TTH123")
        assert result is True
        queue = await client.list_queue_async()
        assert len(queue) == 1
        assert isinstance(queue[0], QueueItemInfo)
        assert "file.txt" in queue[0].target

    @pytest.mark.asyncio
    async def test_remove_download(self, client):
        await client.download_async("/tmp", "file.txt", 1024, "TTH123")
        queue = await client.list_queue_async()
        target = queue[0].target
        await client.remove_download_async(target)
        queue = await client.list_queue_async()
        assert len(queue) == 0

    @pytest.mark.asyncio
    async def test_clear_queue(self, client):
        await client.download_async("/tmp", "a.txt", 100, "T1")
        await client.download_async("/tmp", "b.txt", 200, "T2")
        await client.clear_queue_async()
        queue = await client.list_queue_async()
        assert len(queue) == 0

    @pytest.mark.asyncio
    async def test_download_magnet(self, client):
        result = await client.download_magnet_async("magnet:?xt=urn:tree:tiger:ABC")
        assert result is True

    @pytest.mark.asyncio
    async def test_empty_queue(self, client):
        queue = await client.list_queue_async()
        assert queue == []


class TestRemoteDCClientShares:
    """Tests for share async methods."""

    @pytest.mark.asyncio
    async def test_add_and_list_share(self, client):
        result = await client.add_share_async("/data/files", "MyFiles")
        assert result is True
        shares = await client.list_shares_async()
        assert len(shares) == 1
        assert isinstance(shares[0], ShareInfoData)

    @pytest.mark.asyncio
    async def test_remove_share(self, client):
        await client.add_share_async("/data/files", "MyFiles")
        result = await client.remove_share_async("/data/files")
        assert result is True
        shares = await client.list_shares_async()
        assert len(shares) == 0

    @pytest.mark.asyncio
    async def test_refresh_share(self, client):
        # Should not raise
        await client.refresh_share_async()

    @pytest.mark.asyncio
    async def test_empty_shares(self, client):
        shares = await client.list_shares_async()
        assert shares == []


class TestRemoteDCClientSettings:
    """Tests for settings async methods."""

    @pytest.mark.asyncio
    async def test_get_setting(self, client):
        value = await client.get_setting_async("Nick")
        assert value == "TestUser"

    @pytest.mark.asyncio
    async def test_set_setting(self, client):
        await client.set_setting_async("Nick", "NewNick")
        value = await client.get_setting_async("Nick")
        assert value == "NewNick"

    @pytest.mark.asyncio
    async def test_get_nonexistent_setting(self, client):
        value = await client.get_setting_async("NonExistent")
        assert value == ""

    @pytest.mark.asyncio
    async def test_reload_config(self, client):
        await client.reload_config_async()

    @pytest.mark.asyncio
    async def test_start_networking(self, client):
        await client.start_networking_async()


class TestRemoteDCClientStatus:
    """Tests for status async methods."""

    @pytest.mark.asyncio
    async def test_get_status(self, client):
        status = await client.get_status()
        assert "version" in status
        assert "uptime_seconds" in status
        assert "connected_hubs" in status

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        result = await client.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_get_transfer_stats(self, client):
        stats = await client.get_transfer_stats()
        assert isinstance(stats, TransferStats)
        assert stats.download_speed >= 0

    @pytest.mark.asyncio
    async def test_get_hash_status(self, client):
        hs = await client.get_hash_status()
        assert isinstance(hs, HashStatus)


class TestRemoteDCClientUserManagement:
    """Tests for user management helpers."""

    @pytest.mark.asyncio
    async def test_create_and_list_users(self, client):
        await client.create_user("newuser", "password123", "readonly")
        users = await client.list_users()
        usernames = [u["username"] for u in users]
        assert "newuser" in usernames

    @pytest.mark.asyncio
    async def test_delete_user(self, client):
        await client.create_user("toremove", "pass12345", "readonly")
        await client.delete_user("toremove")
        users = await client.list_users()
        usernames = [u["username"] for u in users]
        assert "toremove" not in usernames

    @pytest.mark.asyncio
    async def test_update_user_role(self, client):
        await client.create_user("upgradeuser", "pass12345", "readonly")
        await client.update_user("upgradeuser", role="admin")
        users = await client.list_users()
        upgraded = [u for u in users if u["username"] == "upgradeuser"][0]
        assert upgraded["role"] == "admin"
