"""
Tests for the WebSocket event system (websocket.py).

Covers:
- Channel enum and event-to-channel mapping
- Event serialization (_serialize_event)
- ConnectionManager: connect, disconnect, broadcast, send_personal
- WebSocket endpoint: auth, subscribe/unsubscribe, ping/pong
- Event bridge (start/stop)
"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.testclient import TestClient as _StarletteClient
from starlette.websockets import WebSocketState

from eiskaltdcpp.api.app import create_app
from eiskaltdcpp.api.auth import AuthManager, UserRecord, UserStore
from eiskaltdcpp.api.models import UserRole
from eiskaltdcpp.api.websocket import (
    EVENT_ARG_NAMES,
    EVENT_CHANNELS,
    Channel,
    ConnectionManager,
    _ClientConnection,
    _serialize_event,
    ws_manager,
)
from eiskaltdcpp.event_meta import EVENT_ARG_NAMES as _EVENT_ARG_NAMES_SHARED


# ============================================================================
# Fixtures
# ============================================================================

class _DictObj:
    def __init__(self, d: dict):
        self.__dict__.update(d)


class MockDCClient:
    """Minimal mock for WebSocket tests."""

    def __init__(self):
        self.is_initialized = True
        self.version = "2.5.0.0-test"
        self._hubs = []
        self._queue = []
        self._share_size = 1024
        self._shared_files = 10
        self._hashing_paused = False
        self._settings = {}
        self._shares = []
        self._search_results = []
        self._chat_history = {}
        self._users = {}

    async def connect(self, url, encoding=""):
        self._hubs.append({"url": url, "name": url, "connected": True, "userCount": 0})

    async def disconnect(self, url):
        self._hubs = [h for h in self._hubs if h["url"] != url]

    def list_hubs(self):
        return [_DictObj(h) for h in self._hubs]

    def is_connected(self, url):
        return any(h["url"] == url for h in self._hubs)

    def list_queue(self):
        return [_DictObj(q) for q in self._queue]

    @property
    def share_size(self):
        return self._share_size

    @property
    def shared_files(self):
        return self._shared_files

    @property
    def transfer_stats(self):
        return _DictObj({"downloadSpeed": 100, "uploadSpeed": 50,
                         "downloaded": 0, "uploaded": 0})

    @property
    def hash_status(self):
        return _DictObj({"currentFile": "", "filesLeft": 0,
                         "bytesLeft": 0, "isPaused": False})

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
        return True

    def remove_download(self, target):
        self._queue = [q for q in self._queue if q["target"] != target]

    def clear_queue(self):
        self._queue.clear()

    def add_share(self, real_path, virtual_name):
        self._shares.append({"realPath": real_path, "virtualName": virtual_name, "size": 0})
        return True

    def remove_share(self, real_path):
        self._shares = [s for s in self._shares if s["realPath"] != real_path]
        return True

    def list_shares(self):
        return [_DictObj(s) for s in self._shares]

    def refresh_share(self):
        pass

    def get_setting(self, name):
        return self._settings.get(name, "")

    def set_setting(self, name, value):
        self._settings[name] = value

    def start_networking(self):
        pass

    def set_priority(self, target, priority):
        for q in self._queue:
            if q["target"] == target:
                q["priority"] = priority

    def reload_config(self):
        pass

    def pause_hashing(self, pause=True):
        self._hashing_paused = pause

    @property
    def _sync_client(self):
        return self


@pytest.fixture
def mock_client():
    return MockDCClient()


@pytest.fixture
def user_store(tmp_path):
    return UserStore(persist_path=tmp_path / "users.json")


@pytest.fixture
def auth_manager(user_store):
    return AuthManager(
        user_store=user_store,
        secret_key="test-ws-secret",
        token_expire_minutes=60,
    )


@pytest.fixture
def app(mock_client, auth_manager):
    application = create_app(
        auth_manager=auth_manager,
        dc_client=mock_client,
        admin_username="admin",
        admin_password="adminpass123",
    )
    return TestClient(application)


@pytest.fixture
def admin_token(app):
    resp = app.post("/api/auth/login", json={
        "username": "admin",
        "password": "adminpass123",
    })
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
def readonly_token(app, admin_token):
    app.post(
        "/api/auth/users",
        json={"username": "viewer", "password": "viewerpass1", "role": "readonly"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = app.post("/api/auth/login", json={
        "username": "viewer",
        "password": "viewerpass1",
    })
    assert resp.status_code == 200
    return resp.json()["access_token"]


# ============================================================================
# Unit tests: Channel enum
# ============================================================================

class TestChannelEnum:
    """Tests for the Channel enum."""

    def test_channel_values(self):
        assert Channel.events == "events"
        assert Channel.chat == "chat"
        assert Channel.search == "search"
        assert Channel.transfers == "transfers"
        assert Channel.hubs == "hubs"
        assert Channel.status == "status"

    def test_channel_from_string(self):
        assert Channel("events") == Channel.events
        assert Channel("chat") == Channel.chat

    def test_channel_invalid_raises(self):
        with pytest.raises(ValueError):
            Channel("invalid_channel")

    def test_all_channels_count(self):
        assert len(Channel) == 6


# ============================================================================
# Unit tests: EVENT_CHANNELS mapping
# ============================================================================

class TestEventChannels:
    """Tests for the event-to-channel mapping."""

    def test_all_events_have_mapping(self):
        """Every event in EVENT_ARG_NAMES should have a channel mapping."""
        for event in EVENT_ARG_NAMES:
            assert event in EVENT_CHANNELS, f"Missing channel mapping for {event}"

    def test_events_channel_always_included(self):
        """Channel.events should be in every event's channel set."""
        for event, channels in EVENT_CHANNELS.items():
            assert Channel.events in channels, \
                f"Channel.events missing for {event}"

    def test_chat_events_mapped_to_chat_channel(self):
        assert Channel.chat in EVENT_CHANNELS["chat_message"]
        assert Channel.chat in EVENT_CHANNELS["private_message"]
        assert Channel.chat in EVENT_CHANNELS["status_message"]

    def test_search_event_mapped_to_search_channel(self):
        assert Channel.search in EVENT_CHANNELS["search_result"]

    def test_hub_events_mapped_to_hubs_channel(self):
        for ev in ("hub_connecting", "hub_connected", "hub_disconnected",
                    "user_connected", "user_disconnected"):
            assert Channel.hubs in EVENT_CHANNELS[ev]

    def test_transfer_events_mapped_to_transfers_channel(self):
        for ev in ("download_starting", "download_complete",
                    "upload_starting", "upload_complete",
                    "queue_item_added", "queue_item_finished"):
            assert Channel.transfers in EVENT_CHANNELS[ev]


# ============================================================================
# Unit tests: EVENT_ARG_NAMES
# ============================================================================

class TestEventArgNames:
    """Tests for event argument name mappings."""

    def test_chat_message_args(self):
        assert EVENT_ARG_NAMES["chat_message"] == (
            "hub_url", "nick", "message", "third_person",
        )

    def test_search_result_args(self):
        names = EVENT_ARG_NAMES["search_result"]
        assert "hub_url" in names
        assert "file" in names
        assert "tth" in names

    def test_hub_connected_args(self):
        assert EVENT_ARG_NAMES["hub_connected"] == ("hub_url", "hub_name")

    def test_all_arg_names_are_tuples(self):
        for event, names in EVENT_ARG_NAMES.items():
            assert isinstance(names, tuple), f"{event} args not a tuple"


# ============================================================================
# Unit tests: _serialize_event
# ============================================================================

class TestSerializeEvent:
    """Tests for the _serialize_event function."""

    def test_basic_serialization(self):
        result = _serialize_event("hub_connected", ("dchub://test:411", "TestHub"))
        assert result["type"] == "event"
        assert result["event"] == "hub_connected"
        assert result["data"]["hub_url"] == "dchub://test:411"
        assert result["data"]["hub_name"] == "TestHub"
        assert "timestamp" in result

    def test_chat_message_serialization(self):
        result = _serialize_event(
            "chat_message",
            ("dchub://hub:411", "Bob", "Hello world!", False),
        )
        assert result["data"]["hub_url"] == "dchub://hub:411"
        assert result["data"]["nick"] == "Bob"
        assert result["data"]["message"] == "Hello world!"
        assert result["data"]["third_person"] is False

    def test_search_result_serialization(self):
        result = _serialize_event(
            "search_result",
            ("dchub://h:411", "/path/file.mp3", 1048576, 3, 5, "ABC123", "user1", False),
        )
        data = result["data"]
        assert data["file"] == "/path/file.mp3"
        assert data["size"] == 1048576
        assert data["free_slots"] == 3
        assert data["tth"] == "ABC123"

    def test_unknown_event_empty_data(self):
        result = _serialize_event("unknown_event_xyz", ("a", "b"))
        assert result["event"] == "unknown_event_xyz"
        assert result["data"] == {}

    def test_fewer_args_than_names(self):
        # hub_connected expects (hub_url, hub_name) but only 1 arg given
        result = _serialize_event("hub_connected", ("dchub://x:411",))
        assert result["data"]["hub_url"] == "dchub://x:411"
        assert "hub_name" not in result["data"]

    def test_timestamp_is_iso_format(self):
        result = _serialize_event("hub_connected", ("url", "name"))
        ts = result["timestamp"]
        # Should parse as ISO format
        from datetime import datetime
        dt = datetime.fromisoformat(ts)
        assert dt.year >= 2025

    def test_hub_alias_injected_when_present(self, tmp_path, monkeypatch):
        """Events with hub_url include hub_alias when an alias exists."""
        hubs_file = tmp_path / "hubs.json"
        monkeypatch.setenv("EISPY_HUBS_FILE", str(hubs_file))
        from eiskaltdcpp.hub_aliases import add_alias
        add_alias("winter", "nmdcs://wintermute:411")

        result = _serialize_event(
            "hub_connected", ("nmdcs://wintermute:411", "Wintermute")
        )
        assert result["data"]["hub_url"] == "nmdcs://wintermute:411"
        assert result["data"]["hub_alias"] == "winter"

    def test_hub_alias_absent_when_no_alias(self, tmp_path, monkeypatch):
        """Events with hub_url omit hub_alias when no alias is defined."""
        hubs_file = tmp_path / "hubs.json"
        monkeypatch.setenv("EISPY_HUBS_FILE", str(hubs_file))

        result = _serialize_event(
            "hub_connected", ("dchub://unknown:411", "NoAlias")
        )
        assert result["data"]["hub_url"] == "dchub://unknown:411"
        assert "hub_alias" not in result["data"]

    def test_hub_alias_not_added_to_non_hub_events(self, tmp_path, monkeypatch):
        """Events without hub_url (e.g. queue/transfer) never get hub_alias."""
        hubs_file = tmp_path / "hubs.json"
        monkeypatch.setenv("EISPY_HUBS_FILE", str(hubs_file))

        result = _serialize_event(
            "download_complete", ("/tmp/file.bin", "user1", 1024, 500.0)
        )
        assert "hub_alias" not in result["data"]


# ============================================================================
# Unit tests: ConnectionManager
# ============================================================================

class TestConnectionManager:
    """Tests for the ConnectionManager class."""

    def test_initial_state(self):
        mgr = ConnectionManager()
        assert mgr.connection_count == 0
        assert mgr._event_stream_task is None
        assert mgr._status_task is None

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        user = UserRecord(username="test", hashed_password="x", role=UserRole.admin)
        channels = {Channel.events}

        conn = await mgr.connect(ws, user, channels)
        assert mgr.connection_count == 1
        assert conn.user.username == "test"
        assert conn.channels == {Channel.events}
        ws.accept.assert_awaited_once()

        await mgr.disconnect(conn)
        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_idempotent(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        user = UserRecord(username="test", hashed_password="x", role=UserRole.admin)
        conn = await mgr.connect(ws, user, {Channel.events})
        await mgr.disconnect(conn)
        # Second disconnect should be safe
        await mgr.disconnect(conn)
        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_to_matching_channels(self):
        mgr = ConnectionManager()
        msg = {"type": "test", "data": "hello"}

        ws1 = AsyncMock()
        ws1.client_state = WebSocketState.CONNECTED
        ws2 = AsyncMock()
        ws2.client_state = WebSocketState.CONNECTED

        user = UserRecord(username="u1", hashed_password="x", role=UserRole.admin)

        conn1 = await mgr.connect(ws1, user, {Channel.chat, Channel.events})
        conn2 = await mgr.connect(ws2, user, {Channel.search})

        await mgr.broadcast(msg, {Channel.chat})
        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_not_awaited()

        await mgr.disconnect(conn1)
        await mgr.disconnect(conn2)

    @pytest.mark.asyncio
    async def test_broadcast_to_events_channel(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        user = UserRecord(username="u", hashed_password="x", role=UserRole.admin)
        conn = await mgr.connect(ws, user, {Channel.events})

        await mgr.broadcast({"test": 1}, {Channel.events, Channel.chat})
        ws.send_text.assert_awaited_once()

        await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connections(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        ws.send_text.side_effect = RuntimeError("connection closed")

        user = UserRecord(username="u", hashed_password="x", role=UserRole.admin)
        await mgr.connect(ws, user, {Channel.events})
        assert mgr.connection_count == 1

        await mgr.broadcast({"test": 1}, {Channel.events})
        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_send_personal(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        user = UserRecord(username="u", hashed_password="x", role=UserRole.admin)
        conn = await mgr.connect(ws, user, {Channel.events})

        await mgr.send_personal(conn, {"type": "hello"})
        ws.send_text.assert_awaited_once()
        payload = json.loads(ws.send_text.call_args[0][0])
        assert payload["type"] == "hello"

        await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_send_personal_handles_error(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        ws.send_text.side_effect = RuntimeError("closed")
        user = UserRecord(username="u", hashed_password="x", role=UserRole.admin)
        conn = await mgr.connect(ws, user, {Channel.events})

        # Should not raise
        await mgr.send_personal(conn, {"type": "hello"})
        await mgr.disconnect(conn)

    def test_start_stop_event_bridge(self):
        mgr = ConnectionManager()
        # Just verify it doesn't error with no async loop setup
        mgr.stop_event_bridge()
        assert mgr._event_stream_task is None
        assert mgr._status_task is None


# ============================================================================
# Unit tests: _ClientConnection
# ============================================================================

class TestClientConnection:
    def test_slots(self):
        ws = MagicMock()
        user = UserRecord(username="x", hashed_password="h", role=UserRole.admin)
        conn = _ClientConnection(ws, user, {Channel.events})
        assert conn.ws is ws
        assert conn.user.username == "x"
        assert Channel.events in conn.channels
        assert conn.connected_at <= time.time()


# ============================================================================
# Integration tests: WebSocket endpoint
# ============================================================================

class TestWebSocketEndpoint:
    """Tests for the /ws/events WebSocket endpoint."""

    def test_ws_connect_with_valid_token(self, app, admin_token):
        with app.websocket_connect(
            f"/ws/events?token={admin_token}&channels=events"
        ) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"
            assert msg["user"] == "admin"
            assert msg["role"] == "admin"
            assert "events" in msg["channels"]

    def test_ws_connect_no_token_rejected(self, app):
        with pytest.raises(Exception):
            with app.websocket_connect("/ws/events") as ws:
                ws.receive_json()

    def test_ws_connect_invalid_token_rejected(self, app):
        with pytest.raises(Exception):
            with app.websocket_connect(
                "/ws/events?token=invalid.jwt.token"
            ) as ws:
                ws.receive_json()

    def test_ws_connect_multiple_channels(self, app, admin_token):
        with app.websocket_connect(
            f"/ws/events?token={admin_token}&channels=events,chat,search"
        ) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"
            assert set(msg["channels"]) == {"events", "chat", "search"}

    def test_ws_ping_pong(self, app, admin_token):
        with app.websocket_connect(
            f"/ws/events?token={admin_token}&channels=events"
        ) as ws:
            ws.receive_json()  # welcome
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"

    def test_ws_subscribe(self, app, admin_token):
        with app.websocket_connect(
            f"/ws/events?token={admin_token}&channels=events"
        ) as ws:
            ws.receive_json()  # welcome
            ws.send_json({"type": "subscribe", "channels": ["chat", "search"]})
            msg = ws.receive_json()
            assert msg["type"] == "subscribed"
            assert "chat" in msg["channels"]
            assert "search" in msg["channels"]
            assert "events" in msg["channels"]

    def test_ws_unsubscribe(self, app, admin_token):
        with app.websocket_connect(
            f"/ws/events?token={admin_token}&channels=events,chat,search"
        ) as ws:
            ws.receive_json()  # welcome
            ws.send_json({"type": "unsubscribe", "channels": ["search"]})
            msg = ws.receive_json()
            assert msg["type"] == "subscribed"
            assert "search" not in msg["channels"]
            assert "events" in msg["channels"]
            assert "chat" in msg["channels"]

    def test_ws_unknown_message_type(self, app, admin_token):
        with app.websocket_connect(
            f"/ws/events?token={admin_token}&channels=events"
        ) as ws:
            ws.receive_json()  # welcome
            ws.send_json({"type": "foobar"})
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "Unknown" in msg["message"]

    def test_ws_invalid_json(self, app, admin_token):
        with app.websocket_connect(
            f"/ws/events?token={admin_token}&channels=events"
        ) as ws:
            ws.receive_json()  # welcome
            ws.send_text("not-valid-json{{{")
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "JSON" in msg["message"]

    def test_ws_readonly_user_can_connect(self, app, readonly_token):
        with app.websocket_connect(
            f"/ws/events?token={readonly_token}&channels=events,chat"
        ) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"
            assert msg["role"] == "readonly"

    def test_ws_default_channel_is_events(self, app, admin_token):
        with app.websocket_connect(
            f"/ws/events?token={admin_token}"
        ) as ws:
            msg = ws.receive_json()
            assert "events" in msg["channels"]

    def test_ws_invalid_channels_ignored(self, app, admin_token):
        with app.websocket_connect(
            f"/ws/events?token={admin_token}&channels=events,bogus,fake"
        ) as ws:
            msg = ws.receive_json()
            assert "events" in msg["channels"]
            assert "bogus" not in msg["channels"]
            assert "fake" not in msg["channels"]


# ============================================================================
# Parametrized serialization: every event type round-trips correctly
# ============================================================================

# Sample args for each event type — one representative value per argument.
_SAMPLE_ARGS: dict[str, tuple] = {
    "hub_connecting": ("dchub://hub:411",),
    "hub_connected": ("dchub://hub:411", "TestHub"),
    "hub_disconnected": ("dchub://hub:411", "Timeout"),
    "hub_redirect": ("dchub://old:411", "dchub://new:411"),
    "hub_get_password": ("dchub://hub:411",),
    "hub_updated": ("dchub://hub:411", "NewName"),
    "hub_nick_taken": ("dchub://hub:411",),
    "hub_full": ("dchub://hub:411",),
    "chat_message": ("dchub://hub:411", "Alice", "Hello!", False),
    "private_message": ("dchub://hub:411", "Alice", "Bob", "Secret"),
    "status_message": ("dchub://hub:411", "Connected"),
    "user_connected": ("dchub://hub:411", "Alice"),
    "user_disconnected": ("dchub://hub:411", "Alice"),
    "user_updated": ("dchub://hub:411", "Alice"),
    "search_result": (
        "dchub://hub:411", "/share/file.mp3", 1048576,
        3, 5, "TTHAAABBB", "Alice", False,
    ),
    "queue_item_added": ("/dl/file.bin", 2048, "TTH123"),
    "queue_item_finished": ("/dl/file.bin", 2048),
    "queue_item_removed": ("/dl/file.bin",),
    "download_starting": ("/dl/file.bin", "Alice", 2048),
    "download_complete": ("/dl/file.bin", "Alice", 2048, 102400),
    "download_failed": ("/dl/file.bin", "No slots"),
    "upload_starting": ("/share/file.bin", "Bob", 4096),
    "upload_complete": ("/share/file.bin", "Bob", 4096),
    "hash_progress": ("/data/video.mkv", 7, 5000000),
}


class TestSerializeAllEvents:
    """Parametrized serialization tests for every event type."""

    @pytest.mark.parametrize("event_type", sorted(EVENT_ARG_NAMES.keys()))
    def test_serialize_round_trip(self, event_type):
        """Serialize an event, then verify every arg is in the output."""
        args = _SAMPLE_ARGS[event_type]
        result = _serialize_event(event_type, args)

        assert result["type"] == "event"
        assert result["event"] == event_type
        assert "timestamp" in result

        # Every named arg should appear in data with correct value
        arg_names = EVENT_ARG_NAMES[event_type]
        assert len(arg_names) == len(args), (
            f"{event_type}: arg count mismatch "
            f"({len(arg_names)} names vs {len(args)} values)"
        )
        for name, value in zip(arg_names, args):
            assert result["data"][name] == value, (
                f"{event_type}.{name}: expected {value!r}, "
                f"got {result['data'].get(name)!r}"
            )

    @pytest.mark.parametrize("event_type", sorted(EVENT_ARG_NAMES.keys()))
    def test_sample_args_match_arg_names(self, event_type):
        """Ensure _SAMPLE_ARGS has the right arity for every event."""
        expected = len(EVENT_ARG_NAMES[event_type])
        actual = len(_SAMPLE_ARGS[event_type])
        assert actual == expected, (
            f"{event_type}: _SAMPLE_ARGS has {actual} args, "
            f"EVENT_ARG_NAMES expects {expected}"
        )

    def test_all_events_have_sample_args(self):
        """Every event in EVENT_ARG_NAMES should have sample args."""
        missing = set(EVENT_ARG_NAMES) - set(_SAMPLE_ARGS)
        assert not missing, f"Missing sample args for: {missing}"

    def test_event_meta_matches_websocket(self):
        """event_meta.EVENT_ARG_NAMES and websocket.EVENT_ARG_NAMES agree."""
        assert EVENT_ARG_NAMES == _EVENT_ARG_NAMES_SHARED


# ============================================================================
# End-to-end: event bridge forwards to WebSocket subscribers
# ============================================================================

class _MockAsyncDCClient:
    """Mock DC client that supports events() for the event bridge."""

    def __init__(self):
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._share_size = 0
        self._shared_files = 0

    def inject_event(self, event_name: str, args: tuple) -> None:
        """Push an event into the stream (call from tests)."""
        self._event_queue.put_nowait((event_name, args))

    def events(self, maxsize: int = 5000):
        return _MockEventStream(self._event_queue)

    def list_hubs(self):
        return []

    def list_queue(self):
        return []

    @property
    def share_size(self):
        return self._share_size

    @property
    def shared_files(self):
        return self._shared_files

    @property
    def transfer_stats(self):
        class _S:
            downloadSpeed = 0
            uploadSpeed = 0
        return _S()


class _MockEventStream:
    """Async iterator backed by an asyncio.Queue."""

    def __init__(self, queue: asyncio.Queue):
        self._queue = queue

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self._queue.get()

    async def close(self):
        pass


class TestEventBridgeE2E:
    """End-to-end tests: DC events → bridge → WebSocket client."""

    @pytest.mark.asyncio
    async def test_event_reaches_websocket_subscriber(self):
        """Fire a hub_connected event and verify a WS client receives it."""
        mgr = ConnectionManager()
        mock_dc = _MockAsyncDCClient()

        # Collect messages sent to the mock WebSocket
        received: list[dict] = []
        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED

        async def capture(text):
            received.append(json.loads(text))

        ws.send_text = AsyncMock(side_effect=capture)

        user = UserRecord(username="e2e", hashed_password="x",
                          role=UserRole.admin)
        conn = await mgr.connect(ws, user, {Channel.events})

        # Start bridge
        mgr._event_stream_task = asyncio.create_task(
            mgr._event_bridge_loop(mock_dc)
        )

        # Inject event
        mock_dc.inject_event("hub_connected", ("dchub://test:411", "TestHub"))
        await asyncio.sleep(0.05)

        # Verify
        assert len(received) >= 1
        msg = received[0]
        assert msg["type"] == "event"
        assert msg["event"] == "hub_connected"
        assert msg["data"]["hub_url"] == "dchub://test:411"
        assert msg["data"]["hub_name"] == "TestHub"

        mgr.stop_event_bridge()
        await mgr.disconnect(conn)

    @pytest.mark.asyncio
    async def test_channel_filtering_in_bridge(self):
        """Events are only delivered to clients subscribed to the right channel."""
        mgr = ConnectionManager()
        mock_dc = _MockAsyncDCClient()

        chat_msgs: list[dict] = []
        search_msgs: list[dict] = []

        ws_chat = AsyncMock()
        ws_chat.client_state = WebSocketState.CONNECTED
        ws_chat.send_text = AsyncMock(
            side_effect=lambda t: chat_msgs.append(json.loads(t))
        )

        ws_search = AsyncMock()
        ws_search.client_state = WebSocketState.CONNECTED
        ws_search.send_text = AsyncMock(
            side_effect=lambda t: search_msgs.append(json.loads(t))
        )

        user = UserRecord(username="e2e", hashed_password="x",
                          role=UserRole.admin)
        conn_chat = await mgr.connect(ws_chat, user, {Channel.chat})
        conn_search = await mgr.connect(ws_search, user, {Channel.search})

        mgr._event_stream_task = asyncio.create_task(
            mgr._event_bridge_loop(mock_dc)
        )

        # Inject chat event — should go to chat subscriber only
        mock_dc.inject_event(
            "chat_message", ("dchub://h:411", "Alice", "Hi", False)
        )
        await asyncio.sleep(0.05)

        assert len(chat_msgs) == 1
        assert chat_msgs[0]["event"] == "chat_message"
        assert len(search_msgs) == 0

        # Inject search event — should go to search subscriber only
        mock_dc.inject_event(
            "search_result",
            ("dchub://h:411", "file.mp3", 1024, 2, 4, "TTH", "Bob", False),
        )
        await asyncio.sleep(0.05)

        assert len(search_msgs) == 1
        assert search_msgs[0]["event"] == "search_result"
        assert len(chat_msgs) == 1  # unchanged

        mgr.stop_event_bridge()
        await mgr.disconnect(conn_chat)
        await mgr.disconnect(conn_search)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("event_type", sorted(EVENT_ARG_NAMES.keys()))
    async def test_every_event_forwarded_through_bridge(self, event_type):
        """Every known event type is forwarded through the bridge to a WS client."""
        mgr = ConnectionManager()
        mock_dc = _MockAsyncDCClient()

        received: list[dict] = []
        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        ws.send_text = AsyncMock(
            side_effect=lambda t: received.append(json.loads(t))
        )

        user = UserRecord(username="e2e", hashed_password="x",
                          role=UserRole.admin)
        conn = await mgr.connect(ws, user, {Channel.events})

        mgr._event_stream_task = asyncio.create_task(
            mgr._event_bridge_loop(mock_dc)
        )

        args = _SAMPLE_ARGS[event_type]
        mock_dc.inject_event(event_type, args)
        await asyncio.sleep(0.05)

        assert len(received) >= 1, f"No message received for {event_type}"
        msg = received[0]
        assert msg["type"] == "event"
        assert msg["event"] == event_type

        # Verify all args survived the round trip
        arg_names = EVENT_ARG_NAMES[event_type]
        for name, value in zip(arg_names, args):
            assert msg["data"][name] == value, (
                f"{event_type}.{name}: expected {value!r}, "
                f"got {msg['data'].get(name)!r}"
            )

        mgr.stop_event_bridge()
        await mgr.disconnect(conn)
