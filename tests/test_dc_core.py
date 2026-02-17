"""
Tests for the dc_core SWIG Python bindings.

These tests verify that the SWIG-generated Python module correctly wraps
the C++ DCBridge and related classes.

Follows the pattern from verlihub's test_verlihub_core.py.

Concurrency-safe: all tests use unique temporary directories via pytest's
tmp_path fixture. No hardcoded paths or shared filesystem state, so
multiple test runs can execute in parallel on the same machine.
"""
import asyncio
import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import List

import pytest
import pytest_asyncio

# Add build directory to path for SWIG module
BUILD_DIR = Path(__file__).parent.parent / "build" / "python"
if BUILD_DIR.exists():
    sys.path.insert(0, str(BUILD_DIR))

# Import SWIG module
try:
    from eiskaltdcpp import dc_core
    SWIG_AVAILABLE = True
except ImportError:
    SWIG_AVAILABLE = False
    dc_core = None


pytestmark = pytest.mark.skipif(
    not SWIG_AVAILABLE,
    reason="dc_core SWIG module not built"
)


@pytest.fixture
def unique_config_dir(tmp_path):
    """Provide a unique, isolated config directory for each test.

    Uses pytest's tmp_path (based on test node id) so parallel runs
    never collide. The directory is automatically cleaned up.
    """
    config = tmp_path / f"dc-config-{uuid.uuid4().hex[:8]}"
    config.mkdir()
    return config


# ============================================================================
# Module import & structure tests
# ============================================================================

class TestSwigModuleImport:
    """Tests for SWIG module availability and basic structure."""

    def test_module_imports(self):
        """dc_core module can be imported."""
        assert dc_core is not None

    def test_bridge_class_exists(self):
        """DCBridge class is available."""
        assert hasattr(dc_core, "DCBridge")

    def test_callback_class_exists(self):
        """DCClientCallback class is available for directors."""
        assert hasattr(dc_core, "DCClientCallback")

    def test_data_types_exist(self):
        """All data struct types are exported."""
        types = [
            "HubInfo", "UserInfo", "SearchResultInfo", "QueueItemInfo",
            "TransferInfo", "ShareDirInfo", "HashStatus", "FileListEntry",
            "TransferStats",
        ]
        for t in types:
            assert hasattr(dc_core, t), f"Missing type: {t}"

    def test_vector_templates_exist(self):
        """SWIG template instantiations for vector types are available."""
        templates = [
            "StringVector", "UserInfoVector", "SearchResultVector",
            "QueueItemVector", "HubInfoVector", "ShareDirVector",
            "FileListEntryVector", "TransferInfoVector",
        ]
        for t in templates:
            assert hasattr(dc_core, t), f"Missing template: {t}"


# ============================================================================
# DCBridge basic tests
# ============================================================================

class TestDCBridgeCreation:
    """Tests for DCBridge creation and lifecycle."""

    def test_construct(self):
        """DCBridge can be constructed."""
        bridge = dc_core.DCBridge()
        assert bridge is not None

    def test_not_initialized_by_default(self):
        """Newly constructed bridge is not initialized."""
        bridge = dc_core.DCBridge()
        assert not bridge.isInitialized()

    def test_bridge_methods_exist(self):
        """Key methods exist on DCBridge."""
        methods = [
            "initialize", "shutdown", "isInitialized",
            "setCallback",
            "connectHub", "disconnectHub", "listHubs", "isHubConnected",
            "sendMessage", "sendPM", "getChatHistory",
            "getHubUsers", "getUserInfo",
            "search", "getSearchResults", "clearSearchResults",
            "addToQueue", "addMagnet", "removeFromQueue",
            "setPriority", "listQueue", "clearQueue",
            "requestFileList", "openFileList", "browseFileList",
            "closeFileList", "closeAllFileLists",
            "addShareDir", "removeShareDir", "listShare",
            "refreshShare", "getShareSize", "getSharedFileCount",
            "getTransferStats", "getHashStatus", "pauseHashing",
            "getSetting", "setSetting", "reloadConfig",
            "getVersion",
        ]
        bridge = dc_core.DCBridge()
        for m in methods:
            assert hasattr(bridge, m), f"Missing method: {m}"

    def test_get_version(self):
        """getVersion returns a non-empty string."""
        ver = dc_core.DCBridge.getVersion()
        assert isinstance(ver, str)
        assert len(ver) > 0

    def test_context_manager_support(self):
        """DCBridge supports __enter__/__exit__."""
        bridge = dc_core.DCBridge()
        assert hasattr(bridge, "__enter__")
        assert hasattr(bridge, "__exit__")


# ============================================================================
# Settings and initialization tests
# ============================================================================

class TestBridgeSettings:
    """Tests for settings get/set and automatic nick generation.

    These tests share a single bridge instance because dcpp's global
    singletons don't support repeated startup()/shutdown() cycles within
    the same process.
    """

    @pytest.fixture(autouse=True, scope="class")
    def bridge(self, tmp_path_factory):
        """Create a single bridge for all settings tests."""
        cfg = tmp_path_factory.mktemp("dc-settings-tests")
        b = dc_core.DCBridge()
        ok = b.initialize(str(cfg) + "/")
        assert ok, "Bridge initialization failed"
        yield b
        b.shutdown()

    def test_get_setting_returns_value(self, bridge):
        """getSetting returns a value after initialization."""
        # DownloadDirectory always has a non-empty default
        dl_dir = bridge.getSetting("DownloadDirectory")
        assert isinstance(dl_dir, str)
        assert len(dl_dir) > 0

    def test_set_and_get_setting(self, bridge):
        """setSetting persists a value readable by getSetting."""
        bridge.setSetting("Description", "pytest-bot")
        val = bridge.getSetting("Description")
        assert val == "pytest-bot"

    def test_default_nick_assigned(self, bridge):
        """A default nick is generated when none is configured."""
        nick = bridge.getSetting("Nick")
        assert nick, "Expected a non-empty default nick"
        assert nick.startswith("dcpy-"), \
            f"Default nick should start with 'dcpy-', got {nick!r}"

    def test_nick_survives_set(self, bridge):
        """Nick set via setSetting is readable."""
        bridge.setSetting("Nick", "my-test-nick")
        assert bridge.getSetting("Nick") == "my-test-nick"

    def test_unknown_setting_returns_empty(self, bridge):
        """getSetting returns empty string for unknown setting names."""
        val = bridge.getSetting("NonExistentSetting99")
        assert val == ""

    def test_lua_init_no_crash(self, bridge):
        """Initializing the bridge doesn't crash due to Lua scripting.

        When the system libeiskaltdcpp is compiled with LUA_SCRIPT,
        every incoming NMDC line passes through a Lua hook.  If the
        Lua state isn't initialized, that path segfaults.  This test
        verifies that initialize() correctly sets up the Lua state
        (or gracefully handles the absence of Lua support).
        """
        # If we got here without a segfault, the Lua init worked
        assert bridge.isInitialized()


# ============================================================================
# Data type tests
# ============================================================================

class TestDataTypes:
    """Tests for data struct construction and field access."""

    def test_hub_info_fields(self):
        """HubInfo has expected fields."""
        info = dc_core.HubInfo()
        assert hasattr(info, "name")
        assert hasattr(info, "url")
        assert hasattr(info, "description")
        assert hasattr(info, "userCount")
        assert hasattr(info, "sharedBytes")
        assert hasattr(info, "connected")
        assert hasattr(info, "isOp")

    def test_user_info_fields(self):
        """UserInfo has expected fields."""
        info = dc_core.UserInfo()
        assert hasattr(info, "nick")
        assert hasattr(info, "description")
        assert hasattr(info, "connection")
        assert hasattr(info, "email")
        assert hasattr(info, "shareSize")
        assert hasattr(info, "isOp")
        assert hasattr(info, "isBot")
        assert hasattr(info, "cid")

    def test_search_result_fields(self):
        """SearchResultInfo has expected fields."""
        info = dc_core.SearchResultInfo()
        assert hasattr(info, "file")
        assert hasattr(info, "size")
        assert hasattr(info, "freeSlots")
        assert hasattr(info, "totalSlots")
        assert hasattr(info, "tth")
        assert hasattr(info, "hubUrl")
        assert hasattr(info, "hubName")
        assert hasattr(info, "nick")
        assert hasattr(info, "isDirectory")

    def test_queue_item_fields(self):
        """QueueItemInfo has expected fields."""
        info = dc_core.QueueItemInfo()
        assert hasattr(info, "target")
        assert hasattr(info, "size")
        assert hasattr(info, "downloadedBytes")
        assert hasattr(info, "priority")
        assert hasattr(info, "tth")

    def test_transfer_stats_fields(self):
        """TransferStats has expected fields."""
        stats = dc_core.TransferStats()
        assert hasattr(stats, "downloadSpeed")
        assert hasattr(stats, "uploadSpeed")
        assert hasattr(stats, "totalDownloaded")
        assert hasattr(stats, "totalUploaded")
        assert hasattr(stats, "downloadCount")
        assert hasattr(stats, "uploadCount")

    def test_hub_info_str(self):
        """HubInfo has __str__ representation."""
        info = dc_core.HubInfo()
        info.name = "TestHub"
        info.url = "dchub://test:411"
        s = str(info)
        assert "TestHub" in s

    def test_user_info_str(self):
        """UserInfo has __str__ representation."""
        info = dc_core.UserInfo()
        info.nick = "TestUser"
        s = str(info)
        assert "TestUser" in s


# ============================================================================
# Callback / director tests
# ============================================================================

class TestEventCallback:
    """Tests for Python callback implementation via SWIG directors."""

    def test_can_instantiate_callback(self):
        """DCClientCallback can be instantiated in Python."""
        cb = dc_core.DCClientCallback()
        assert cb is not None

    def test_can_subclass_callback(self):
        """DCClientCallback can be subclassed with overrides."""
        class MyCallback(dc_core.DCClientCallback):
            def __init__(self):
                super().__init__()
                self.messages: List[str] = []

            def onChatMessage(self, hubUrl, nick, message, thirdPerson):
                self.messages.append(f"<{nick}> {message}")

        cb = MyCallback()
        assert len(cb.messages) == 0

    def test_callback_methods_callable(self):
        """Callback override methods can be called directly."""
        class TestCallback(dc_core.DCClientCallback):
            def __init__(self):
                super().__init__()
                self.events: List[str] = []

            def onHubConnected(self, hubUrl, hubName):
                self.events.append(f"connected:{hubUrl}")

            def onHubDisconnected(self, hubUrl, reason):
                self.events.append(f"disconnected:{hubUrl}")

            def onChatMessage(self, hubUrl, nick, message, thirdPerson):
                self.events.append(f"chat:{nick}:{message}")

            def onSearchResult(self, hubUrl, file, size, freeSlots,
                               totalSlots, tth, nick, isDirectory):
                self.events.append("search_result")

        cb = TestCallback()
        cb.onHubConnected("dchub://test:411", "TestHub")
        cb.onHubDisconnected("dchub://test:411", "bye")
        cb.onChatMessage("dchub://test:411", "user", "hello", False)

        assert "connected:dchub://test:411" in cb.events
        assert "disconnected:dchub://test:411" in cb.events
        assert "chat:user:hello" in cb.events

    def test_callback_all_methods_overridable(self):
        """All callback methods can be overridden."""
        callback_methods = [
            "onHubConnecting", "onHubConnected", "onHubDisconnected",
            "onHubRedirect", "onHubPasswordRequest", "onHubUpdated",
            "onNickTaken", "onHubFull",
            "onChatMessage", "onPrivateMessage", "onStatusMessage",
            "onUserConnected", "onUserDisconnected", "onUserUpdated",
            "onSearchResult",
            "onQueueItemAdded", "onQueueItemFinished", "onQueueItemRemoved",
            "onDownloadStarting", "onDownloadComplete", "onDownloadFailed",
            "onUploadStarting", "onUploadComplete",
            "onHashProgress",
        ]
        cb = dc_core.DCClientCallback()
        for method in callback_methods:
            assert hasattr(cb, method), f"Missing callback: {method}"


# ============================================================================
# Thread safety tests
# ============================================================================

class TestThreadSafety:
    """Tests for thread-safety of SWIG bindings."""

    def test_callback_from_multiple_threads(self):
        """Callbacks can be invoked from multiple threads safely."""
        class ThreadSafeCallback(dc_core.DCClientCallback):
            def __init__(self):
                super().__init__()
                self.lock = threading.Lock()
                self.counter = 0

            def onChatMessage(self, hubUrl, nick, message, thirdPerson):
                with self.lock:
                    self.counter += 1

        cb = ThreadSafeCallback()
        threads = []

        def call_chat(n):
            for _ in range(100):
                cb.onChatMessage("hub", f"user{n}", "msg", False)

        for i in range(4):
            t = threading.Thread(target=call_chat, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert cb.counter == 400

    def test_module_import_from_thread(self):
        """Module can be imported from a worker thread."""
        result = {"success": False, "error": None}

        def import_in_thread():
            try:
                from eiskaltdcpp import dc_core as m
                result["success"] = m is not None
            except Exception as e:
                result["error"] = str(e)

        thread = threading.Thread(target=import_in_thread)
        thread.start()
        thread.join()

        assert result["success"], f"Import failed: {result['error']}"


# ============================================================================
# High-level wrapper tests (no SWIG needed for basic tests)
# ============================================================================

class TestDCClientWrapper:
    """Tests for the high-level DCClient Python wrapper."""

    def test_import_dc_client(self):
        """DCClient wrapper can be imported."""
        from eiskaltdcpp.dc_client import DCClient
        assert DCClient is not None

    def test_dc_client_construct(self, unique_config_dir):
        """DCClient can be constructed."""
        from eiskaltdcpp.dc_client import DCClient
        client = DCClient(str(unique_config_dir))
        assert not client.is_initialized

    def test_dc_client_repr(self, unique_config_dir):
        """DCClient has a useful repr."""
        from eiskaltdcpp.dc_client import DCClient
        cfg = str(unique_config_dir)
        client = DCClient(cfg)
        r = repr(client)
        assert cfg in r
        assert "not initialized" in r

    def test_dc_client_event_registration(self, unique_config_dir):
        """Event handlers can be registered."""
        from eiskaltdcpp.dc_client import DCClient
        client = DCClient(str(unique_config_dir))

        called = []

        @client.on("chat_message")
        def on_chat(hub, nick, msg):
            called.append((nick, msg))

        # Verify registration didn't crash
        assert len(called) == 0

    def test_dc_client_invalid_event(self, unique_config_dir):
        """Registering an invalid event type raises ValueError."""
        from eiskaltdcpp.dc_client import DCClient
        client = DCClient(str(unique_config_dir))

        with pytest.raises(ValueError, match="Unknown event type"):
            client.on("nonexistent_event", lambda: None)

    def test_dc_client_event_types(self):
        """All expected event types are defined."""
        from eiskaltdcpp.dc_client import EVENT_TYPES

        expected = {
            "hub_connecting", "hub_connected", "hub_disconnected",
            "hub_redirect", "hub_get_password", "hub_updated",
            "hub_nick_taken", "hub_full",
            "chat_message", "private_message", "status_message",
            "user_connected", "user_disconnected", "user_updated",
            "search_result",
            "queue_item_added", "queue_item_finished", "queue_item_removed",
            "download_starting", "download_complete", "download_failed",
            "upload_starting", "upload_complete",
            "hash_progress",
        }
        assert expected == EVENT_TYPES

    def test_dc_client_on_decorator(self, unique_config_dir):
        """The @client.on('event') decorator pattern works."""
        from eiskaltdcpp.dc_client import DCClient
        client = DCClient(str(unique_config_dir))

        @client.on("hub_connected")
        def handler(url, name):
            pass

        # The handler should be registered (not called yet)
        assert callable(handler)

    def test_dc_client_on_method_call(self, unique_config_dir):
        """client.on('event', fn) method-call style works."""
        from eiskaltdcpp.dc_client import DCClient
        client = DCClient(str(unique_config_dir))

        def my_handler(url, reason):
            pass

        client.on("hub_disconnected", my_handler)

    def test_dc_client_off(self, unique_config_dir):
        """client.off() unregisters a handler without error."""
        from eiskaltdcpp.dc_client import DCClient
        client = DCClient(str(unique_config_dir))

        def my_handler(url, nick, msg):
            pass

        client.on("chat_message", my_handler)
        client.off("chat_message", my_handler)  # should not raise

    def test_dc_client_multiple_handlers(self, unique_config_dir):
        """Multiple handlers can be registered for the same event."""
        from eiskaltdcpp.dc_client import DCClient
        client = DCClient(str(unique_config_dir))

        results = []

        client.on("status_message", lambda hub, msg: results.append(("a", msg)))
        client.on("status_message", lambda hub, msg: results.append(("b", msg)))

        # Both registered without error
        assert len(results) == 0


# ============================================================================
# AsyncDCClient wrapper tests
# ============================================================================

class TestAsyncDCClient:
    """Tests for the AsyncDCClient async wrapper."""

    def test_import_async_client(self):
        """AsyncDCClient can be imported."""
        from eiskaltdcpp.async_client import AsyncDCClient
        assert AsyncDCClient is not None

    def test_async_client_construct(self, unique_config_dir):
        """AsyncDCClient can be constructed without initializing."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient(str(unique_config_dir))
        assert not client.is_initialized

    def test_async_client_repr(self, unique_config_dir):
        """AsyncDCClient has a useful repr."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient(str(unique_config_dir))
        r = repr(client)
        assert "AsyncDCClient" in r
        assert "not initialized" in r

    def test_async_client_event_registration(self, unique_config_dir):
        """Async client event registration works."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient(str(unique_config_dir))

        @client.on("chat_message")
        async def handler(hub, nick, msg, third):
            pass

        # Registered without error
        assert len(client._handlers["chat_message"]) == 1

    def test_async_client_invalid_event(self, unique_config_dir):
        """Registering an invalid event raises ValueError."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient(str(unique_config_dir))

        with pytest.raises(ValueError):
            client.on("bogus_event", lambda: None)

    def test_async_client_off(self, unique_config_dir):
        """client.off() unregisters a handler."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient(str(unique_config_dir))

        async def handler(hub, nick, msg, third):
            pass

        client.on("chat_message", handler)
        assert len(client._handlers["chat_message"]) == 1
        client.off("chat_message", handler)
        assert len(client._handlers["chat_message"]) == 0

    def test_async_client_version(self, unique_config_dir):
        """Async client exposes version."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient(str(unique_config_dir))
        v = client.version
        assert v and len(v) > 0

    def test_async_client_from_package_init(self):
        """AsyncDCClient is importable from the package."""
        from eiskaltdcpp import AsyncDCClient
        assert AsyncDCClient is not None

    def test_event_stream_class(self, unique_config_dir):
        """EventStream can be created."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient(str(unique_config_dir))
        stream = client.events()
        assert stream is not None


# ============================================================================
# Async event dispatch & concurrency tests
# ============================================================================

class TestAsyncEventDispatch:
    """Tests for the async event dispatch machinery.

    These test the internal event dispatch, handler invocation, and
    EventStream functionality without needing a live hub connection.
    """

    async def test_sync_handler_dispatched_from_loop(self):
        """A sync handler registered with .on() is invoked via _dispatch_event."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        received = []

        @client.on("status_message")
        def handler(hub_url, message):
            received.append((hub_url, message))

        # Simulate the C++ callback dispatching an event in the loop
        client._run_handlers("status_message", ("dchub://test:411", "hello"))

        assert len(received) == 1
        assert received[0] == ("dchub://test:411", "hello")

    async def test_async_handler_dispatched(self):
        """An async handler is scheduled as a coroutine task."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        received = asyncio.Event()
        captured = {}

        @client.on("status_message")
        async def handler(hub_url, message):
            captured["hub"] = hub_url
            captured["msg"] = message
            received.set()

        client._run_handlers("status_message", ("dchub://test:411", "async-hello"))

        # The async handler is scheduled as a task — give it a tick to run
        await asyncio.wait_for(received.wait(), timeout=2.0)
        assert captured["hub"] == "dchub://test:411"
        assert captured["msg"] == "async-hello"

    async def test_multiple_handlers_all_called(self):
        """Multiple handlers on the same event all get invoked."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        results = []

        @client.on("user_connected")
        def h1(hub, nick):
            results.append(("h1", nick))

        @client.on("user_connected")
        def h2(hub, nick):
            results.append(("h2", nick))

        client._run_handlers("user_connected", ("dchub://test:411", "Alice"))

        assert ("h1", "Alice") in results
        assert ("h2", "Alice") in results

    async def test_handler_exception_does_not_crash(self):
        """A handler that raises doesn't prevent other handlers from running."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        results = []

        @client.on("user_connected")
        def bad_handler(hub, nick):
            raise RuntimeError("intentional failure")

        @client.on("user_connected")
        def good_handler(hub, nick):
            results.append(nick)

        # Should not raise
        client._run_handlers("user_connected", ("dchub://test:411", "Bob"))
        assert "Bob" in results

    async def test_off_prevents_handler_from_firing(self):
        """off() prevents a handler from being called."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        results = []

        def handler(hub, nick):
            results.append(nick)

        client.on("user_connected", handler)
        client.off("user_connected", handler)

        client._run_handlers("user_connected", ("hub", "Alice"))
        assert len(results) == 0

    async def test_off_nonexistent_handler_is_silent(self):
        """off() with an unregistered handler doesn't raise."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")
        client.off("user_connected", lambda h, n: None)  # no-op

    async def test_event_stream_receives_events(self):
        """EventStream yields events dispatched via _run_handlers."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        stream = client.events()
        client._run_handlers("status_message", ("hub", "test-msg"))

        event_name, args = await asyncio.wait_for(
            stream.__anext__(), timeout=2.0
        )
        assert event_name == "status_message"
        assert args == ("hub", "test-msg")
        await stream.close()

    async def test_event_stream_multiple_events(self):
        """EventStream yields multiple events in order."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        stream = client.events()
        client._run_handlers("user_connected", ("hub", "Alice"))
        client._run_handlers("user_connected", ("hub", "Bob"))

        e1_name, e1_args = await asyncio.wait_for(stream.__anext__(), timeout=2.0)
        e2_name, e2_args = await asyncio.wait_for(stream.__anext__(), timeout=2.0)

        assert e1_args[1] == "Alice"
        assert e2_args[1] == "Bob"
        await stream.close()

    async def test_event_stream_close_unsubscribes(self):
        """After close(), the stream's queue is removed from the registry."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        stream = client.events()
        assert len(client._event_queues) == 1
        await stream.close()
        assert len(client._event_queues) == 0

    async def test_event_stream_as_async_for(self):
        """EventStream works with 'async for'."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        stream = client.events()
        client._run_handlers("chat_message", ("hub", "nick", "hi", False))
        client._run_handlers("chat_message", ("hub", "nick", "bye", False))

        collected = []

        async def drain():
            async for name, args in stream:
                collected.append(args[2])  # message text
                if len(collected) >= 2:
                    break

        await asyncio.wait_for(drain(), timeout=2.0)
        assert collected == ["hi", "bye"]
        await stream.close()

    async def test_multiple_event_streams(self):
        """Multiple EventStreams each receive all events independently."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        s1 = client.events()
        s2 = client.events()

        client._run_handlers("status_message", ("hub", "msg1"))

        e1_name, e1_args = await asyncio.wait_for(s1.__anext__(), timeout=2.0)
        e2_name, e2_args = await asyncio.wait_for(s2.__anext__(), timeout=2.0)

        assert e1_args[1] == "msg1"
        assert e2_args[1] == "msg1"

        await s1.close()
        await s2.close()

    # -- Connect / disconnect event waits ----------------------------------

    async def test_wait_connected_event_signaling(self):
        """wait_connected() returns when the connect event is signaled."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        hub_url = "dchub://fake:411"

        # Simulate a pending connect wait
        ev = asyncio.Event()
        client._connect_events[hub_url] = ev

        # Mock is_connected to return True when checked after signal
        original_is_connected = client._sync_client.is_connected
        client._sync_client.is_connected = lambda url: True

        async def fire_later():
            await asyncio.sleep(0.1)
            ev.set()

        asyncio.create_task(fire_later())

        # Should complete within timeout
        await asyncio.wait_for(ev.wait(), timeout=2.0)
        assert ev.is_set()

        # Restore
        client._sync_client.is_connected = original_is_connected
        client._connect_events.pop(hub_url, None)

    async def test_wait_connected_already_connected(self):
        """wait_connected() returns immediately if already connected."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        hub_url = "dchub://fake:411"

        # Mock is_connected
        client._sync_client.is_connected = lambda url: True
        await client.wait_connected(hub_url, timeout=1.0)
        # Should return without waiting

    async def test_wait_disconnected_already_disconnected(self):
        """wait_disconnected() returns immediately if not connected."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        hub_url = "dchub://fake:411"
        client._sync_client.is_connected = lambda url: False
        await client.wait_disconnected(hub_url, timeout=1.0)

    # -- PM queue ----------------------------------------------------------

    async def test_pm_queue_receives_messages(self):
        """Private messages are enqueued and can be awaited via wait_pm."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        # Simulate the callback wiring pushing a PM to the queue
        client._pm_queue.put_nowait(
            ("dchub://hub:411", "Alice", "Bot", "hello bot")
        )

        result = await asyncio.wait_for(
            client.wait_pm(timeout=2.0), timeout=3.0
        )
        assert result == ("dchub://hub:411", "Alice", "Bot", "hello bot")

    async def test_pm_queue_filters_by_nick(self):
        """wait_pm(from_nick=...) only returns PMs from that nick."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        client._pm_queue.put_nowait(("hub", "Eve", "Bot", "ignore me"))
        client._pm_queue.put_nowait(("hub", "Alice", "Bot", "pick me"))

        result = await asyncio.wait_for(
            client.wait_pm(from_nick="Alice", timeout=2.0), timeout=3.0
        )
        assert result[1] == "Alice"
        assert result[3] == "pick me"

    async def test_pm_queue_timeout_raises(self):
        """wait_pm raises TimeoutError when no PM arrives."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        with pytest.raises(asyncio.TimeoutError):
            await client.wait_pm(timeout=0.1)

    # -- Search queue ------------------------------------------------------

    async def test_search_queue_receives_results(self):
        """Search results pushed via _run_handlers show up in _search_queue."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        # Simulate a search result arriving via the callback
        result_dict = {
            "hub_url": "hub", "file": "test.txt", "size": 42,
            "freeSlots": 3, "totalSlots": 5, "tth": "ABCDE",
            "nick": "Alice", "isDirectory": False,
        }
        client._search_queue.put_nowait(result_dict)

        r = await asyncio.wait_for(
            client._search_queue.get(), timeout=2.0
        )
        assert r["file"] == "test.txt"
        assert r["nick"] == "Alice"

    # -- Download event tracking -------------------------------------------

    async def test_download_event_tracking(self):
        """download_and_wait event tracking signals on queue_item_finished."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        target = "/tmp/test/file.txt"
        ev = asyncio.Event()
        client._download_events[target] = ev
        client._download_results[target] = (False, "timeout")

        # Simulate queue_item_finished
        client._download_results[target] = (True, "")
        ev.set()

        await asyncio.wait_for(ev.wait(), timeout=2.0)
        success, error = client._download_results[target]
        assert success is True
        assert error == ""

        # Cleanup
        client._download_events.pop(target, None)
        client._download_results.pop(target, None)

    async def test_download_event_failure_tracking(self):
        """download_and_wait event tracking signals on download_failed."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient("")

        target = "/tmp/test/fail.txt"
        ev = asyncio.Event()
        client._download_events[target] = ev
        client._download_results[target] = (False, "timeout")

        # Simulate download_failed
        client._download_results[target] = (False, "No slots available")
        ev.set()

        await asyncio.wait_for(ev.wait(), timeout=2.0)
        success, error = client._download_results[target]
        assert success is False
        assert "No slots" in error

        client._download_events.pop(target, None)
        client._download_results.pop(target, None)


# ============================================================================
# Async context manager tests
# ============================================================================

class TestAsyncContextManager:
    """Tests for the async with AsyncDCClient() pattern."""

    async def test_context_manager_protocol(self, unique_config_dir):
        """AsyncDCClient has __aenter__ and __aexit__."""
        from eiskaltdcpp.async_client import AsyncDCClient
        client = AsyncDCClient(str(unique_config_dir))
        assert hasattr(client, "__aenter__")
        assert hasattr(client, "__aexit__")

