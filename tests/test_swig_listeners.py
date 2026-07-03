"""
Tests for Phase 4 — per-manager listener director adapters.

These tests verify that:
1. All PyXxxListener adapter classes are importable from dc_core
2. Python subclasses can override named virtual methods
3. EisPyContext exposes add/remove listener methods
4. Adapter classes have the correct method signatures
"""
import sys
from pathlib import Path

import pytest

BUILD_DIR = Path(__file__).parent.parent / "build" / "python"
if BUILD_DIR.exists():
    sys.path.insert(0, str(BUILD_DIR))

try:
    from eiskaltdcpp import dc_core
    SWIG_AVAILABLE = True
except ImportError:
    SWIG_AVAILABLE = False
    dc_core = None

pytestmark = pytest.mark.skipif(
    not SWIG_AVAILABLE,
    reason="dc_core SWIG module not built",
)


# ============================================================================
# Adapter class availability
# ============================================================================

class TestListenerAdapterTypes:
    """All listener adapter classes are importable from dc_core."""

    LISTENER_TYPES = [
        "PyClientListener",
        "PyClientManagerListener",
        "PySearchManagerListener",
        "PyQueueManagerListener",
        "PyDownloadManagerListener",
        "PyUploadManagerListener",
        "PyTimerManagerListener",
    ]

    @pytest.mark.parametrize("class_name", LISTENER_TYPES)
    def test_listener_class_exists(self, class_name):
        assert hasattr(dc_core, class_name), f"dc_core.{class_name} missing"

    @pytest.mark.parametrize("class_name", LISTENER_TYPES)
    def test_listener_instantiation(self, class_name):
        """Base adapter classes can be instantiated from Python."""
        cls = getattr(dc_core, class_name)
        obj = cls()
        assert obj is not None
        del obj


# ============================================================================
# PyClientListener methods
# ============================================================================

class TestPyClientListenerMethods:
    """PyClientListener has all expected named virtual methods."""

    METHODS = [
        "onConnecting", "onConnected", "onFailed", "onRedirect",
        "onGetPassword", "onHubUpdated", "onNickTaken", "onHubFull",
        "onSearchFlood", "onMessage", "onStatusMessage",
        "onUserUpdated", "onUsersUpdated", "onUserRemoved",
        "onHubUserCommand",
    ]

    @pytest.mark.parametrize("method", METHODS)
    def test_method_exists(self, method):
        listener = dc_core.PyClientListener()
        assert hasattr(listener, method)
        assert callable(getattr(listener, method))

    def test_subclass_override(self):
        """Python subclass can override PyClientListener methods."""
        calls = []

        class MyHubListener(dc_core.PyClientListener):
            def onConnected(self, hubUrl):
                calls.append(("connected", hubUrl))

            def onFailed(self, hubUrl, reason):
                calls.append(("failed", hubUrl, reason))

            def onMessage(self, hubUrl, nick, text, thirdPerson):
                calls.append(("msg", hubUrl, nick, text, thirdPerson))

        listener = MyHubListener()
        assert listener is not None
        # Can't fire events without a live dcpp hub, but verify the object
        # is a valid director-wrapped instance
        assert isinstance(listener, dc_core.PyClientListener)
        del listener


# ============================================================================
# PyClientManagerListener methods
# ============================================================================

class TestPyClientManagerListenerMethods:
    METHODS = [
        "onUserConnected", "onUserUpdated", "onUserDisconnected",
        "onIncomingSearch", "onClientConnected", "onClientUpdated",
        "onClientDisconnected",
    ]

    @pytest.mark.parametrize("method", METHODS)
    def test_method_exists(self, method):
        listener = dc_core.PyClientManagerListener()
        assert hasattr(listener, method)

    def test_subclass_override(self):
        class MyCMListener(dc_core.PyClientManagerListener):
            def onClientConnected(self, hubUrl):
                pass

            def onUserConnected(self, cid):
                pass

        listener = MyCMListener()
        assert isinstance(listener, dc_core.PyClientManagerListener)


# ============================================================================
# PySearchManagerListener methods
# ============================================================================

class TestPySearchManagerListenerMethods:
    def test_method_exists(self):
        listener = dc_core.PySearchManagerListener()
        assert hasattr(listener, "onSearchResult")

    def test_subclass_override(self):
        results = []

        class MySearchListener(dc_core.PySearchManagerListener):
            def onSearchResult(self, result):
                results.append(result)

        listener = MySearchListener()
        assert isinstance(listener, dc_core.PySearchManagerListener)


# ============================================================================
# PyQueueManagerListener methods
# ============================================================================

class TestPyQueueManagerListenerMethods:
    """PyQueueManagerListener wraps all 18 dcpp QueueManagerListener events."""

    METHODS = [
        # Core events
        "onAdded", "onFinished", "onRemoved", "onMoved",
        "onSourcesUpdated", "onStatusUpdated", "onSearchStringUpdated",
        "onFileMoved",
        # Recheck events
        "onRecheckStarted", "onRecheckNoFile", "onRecheckFileTooSmall",
        "onRecheckDownloadsRunning", "onRecheckNoTree",
        "onRecheckAlreadyFinished", "onRecheckDone",
        # Integrity
        "onCRCFailed", "onCRCChecked",
        # Partial
        "onPartialList",
    ]

    @pytest.mark.parametrize("method", METHODS)
    def test_method_exists(self, method):
        listener = dc_core.PyQueueManagerListener()
        assert hasattr(listener, method)

    def test_subclass_override(self):
        class MyQueueListener(dc_core.PyQueueManagerListener):
            def onAdded(self, target, size, tth):
                pass

            def onFinished(self, target, size, dir_):
                pass

            def onRemoved(self, target):
                pass

            def onSourcesUpdated(self, target):
                pass

        listener = MyQueueListener()
        assert isinstance(listener, dc_core.PyQueueManagerListener)


# ============================================================================
# PyDownloadManagerListener methods
# ============================================================================

class TestPyDownloadManagerListenerMethods:
    METHODS = ["onRequesting", "onStarting", "onTick", "onComplete", "onFailed"]

    @pytest.mark.parametrize("method", METHODS)
    def test_method_exists(self, method):
        listener = dc_core.PyDownloadManagerListener()
        assert hasattr(listener, method)

    def test_subclass_override(self):
        class MyDLListener(dc_core.PyDownloadManagerListener):
            def onStarting(self, transfer):
                pass

            def onComplete(self, transfer):
                pass

            def onFailed(self, transfer, reason):
                pass

        listener = MyDLListener()
        assert isinstance(listener, dc_core.PyDownloadManagerListener)


# ============================================================================
# PyUploadManagerListener methods
# ============================================================================

class TestPyUploadManagerListenerMethods:
    METHODS = [
        "onStarting", "onTick", "onComplete", "onFailed",
        "onWaitingAddFile", "onWaitingRemoveUser",
    ]

    @pytest.mark.parametrize("method", METHODS)
    def test_method_exists(self, method):
        listener = dc_core.PyUploadManagerListener()
        assert hasattr(listener, method)


# ============================================================================
# PyTimerManagerListener methods
# ============================================================================

class TestPyTimerManagerListenerMethods:
    METHODS = ["onSecond", "onMinute"]

    @pytest.mark.parametrize("method", METHODS)
    def test_method_exists(self, method):
        listener = dc_core.PyTimerManagerListener()
        assert hasattr(listener, method)

    def test_subclass_override(self):
        class MyTimerListener(dc_core.PyTimerManagerListener):
            def onSecond(self, tick):
                pass

            def onMinute(self, tick):
                pass

        listener = MyTimerListener()
        assert isinstance(listener, dc_core.PyTimerManagerListener)


# ============================================================================
# EisPyContext listener subscription methods
# ============================================================================

class TestEisPyContextListenerMethods:
    """EisPyContext exposes add/remove methods for all listener types."""

    ADD_REMOVE_PAIRS = [
        ("addHubListener", "removeHubListener"),
        ("addClientManagerListener", "removeClientManagerListener"),
        ("addSearchListener", "removeSearchListener"),
        ("addQueueListener", "removeQueueListener"),
        ("addDownloadListener", "removeDownloadListener"),
        ("addUploadListener", "removeUploadListener"),
        ("addTimerListener", "removeTimerListener"),
    ]

    @pytest.mark.parametrize("add_name,remove_name", ADD_REMOVE_PAIRS)
    def test_subscribe_methods_exist(self, add_name, remove_name):
        ctx = dc_core.EisPyContext()
        assert hasattr(ctx, add_name), f"EisPyContext.{add_name} missing"
        assert hasattr(ctx, remove_name), f"EisPyContext.{remove_name} missing"
        assert callable(getattr(ctx, add_name))
        assert callable(getattr(ctx, remove_name))
        del ctx


# ============================================================================
# Director identity checks
# ============================================================================

class TestListenerDirectorIdentity:
    """SWIG directors preserve Python subclass type through C++."""

    def test_client_listener_director(self):
        class Sub(dc_core.PyClientListener):
            pass

        obj = Sub()
        assert isinstance(obj, dc_core.PyClientListener)
        assert type(obj).__name__ == "Sub"

    def test_queue_listener_director(self):
        class Sub(dc_core.PyQueueManagerListener):
            pass

        obj = Sub()
        assert isinstance(obj, dc_core.PyQueueManagerListener)
        assert type(obj).__name__ == "Sub"

    def test_search_listener_director(self):
        class Sub(dc_core.PySearchManagerListener):
            pass

        obj = Sub()
        assert isinstance(obj, dc_core.PySearchManagerListener)

    def test_download_listener_director(self):
        class Sub(dc_core.PyDownloadManagerListener):
            pass

        obj = Sub()
        assert isinstance(obj, dc_core.PyDownloadManagerListener)

    def test_timer_listener_director(self):
        class Sub(dc_core.PyTimerManagerListener):
            pass

        obj = Sub()
        assert isinstance(obj, dc_core.PyTimerManagerListener)


# ============================================================================
# Multiple instantiation
# ============================================================================

class TestMultipleListenerInstances:
    """Multiple listener instances can coexist without issues."""

    def test_multiple_instances_same_type(self):
        listeners = [dc_core.PyQueueManagerListener() for _ in range(5)]
        assert len(listeners) == 5
        for listener in listeners:
            assert hasattr(listener, "onAdded")

    def test_multiple_instances_different_types(self):
        listeners = [
            dc_core.PyClientListener(),
            dc_core.PyClientManagerListener(),
            dc_core.PySearchManagerListener(),
            dc_core.PyQueueManagerListener(),
            dc_core.PyDownloadManagerListener(),
            dc_core.PyUploadManagerListener(),
            dc_core.PyTimerManagerListener(),
        ]
        assert len(listeners) == 7

    def test_multiple_subclass_instances(self):
        class QL1(dc_core.PyQueueManagerListener):
            def onAdded(self, target, size, tth):
                return "QL1"

        class QL2(dc_core.PyQueueManagerListener):
            def onAdded(self, target, size, tth):
                return "QL2"

        a, b = QL1(), QL2()
        assert type(a).__name__ == "QL1"
        assert type(b).__name__ == "QL2"
