"""
Tests for the dc_core SWIG Python bindings.

These tests verify that the SWIG-generated Python module correctly wraps
the C++ DCBridge and related classes.

Follows the pattern from verlihub's test_verlihub_core.py.

Concurrency-safe: all tests use unique temporary directories via pytest's
tmp_path fixture. No hardcoded paths or shared filesystem state, so
multiple test runs can execute in parallel on the same machine.
"""
import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import List

import pytest

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
        assert hasattr(info, "fileName")
        assert hasattr(info, "filePath")
        assert hasattr(info, "fileSize")
        assert hasattr(info, "freeSlots")
        assert hasattr(info, "totalSlots")
        assert hasattr(info, "tth")
        assert hasattr(info, "hubUrl")
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

            def onChatMessage(self, hubUrl, nick, message):
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

            def onChatMessage(self, hubUrl, nick, message):
                self.events.append(f"chat:{nick}:{message}")

            def onSearchResult(self, result):
                self.events.append("search_result")

        cb = TestCallback()
        cb.onHubConnected("dchub://test:411", "TestHub")
        cb.onHubDisconnected("dchub://test:411", "bye")
        cb.onChatMessage("dchub://test:411", "user", "hello")

        assert "connected:dchub://test:411" in cb.events
        assert "disconnected:dchub://test:411" in cb.events
        assert "chat:user:hello" in cb.events

    def test_callback_all_methods_overridable(self):
        """All callback methods can be overridden."""
        callback_methods = [
            "onHubConnecting", "onHubConnected", "onHubDisconnected",
            "onHubRedirect", "onHubGetPassword", "onHubUpdated",
            "onHubNickTaken", "onHubFull",
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

            def onChatMessage(self, hubUrl, nick, message):
                with self.lock:
                    self.counter += 1

        cb = ThreadSafeCallback()
        threads = []

        def call_chat(n):
            for _ in range(100):
                cb.onChatMessage("hub", f"user{n}", "msg")

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
