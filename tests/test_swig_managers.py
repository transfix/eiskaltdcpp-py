"""
Tests for direct SWIG manager access via DCBridge properties.

These tests verify that Phase 1's modular .i files expose all managers
correctly and that DCClient/AsyncDCClient property accessors work.
"""
import sys
import uuid
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
# SWIG type import tests
# ============================================================================

class TestSwigManagerTypes:
    """All manager classes are importable from dc_core."""

    MANAGER_TYPES = [
        "SettingsManager",
        "ClientManager",
        "QueueManager",
        "ShareManager",
        "SearchManager",
        "HashManager",
        "DownloadManager",
        "UploadManager",
        "ThrottleManager",
        "FavoriteManager",
        "FinishedManager",
        "ConnectivityManager",
        "MappingManager",
        "CryptoManager",
        "LogManager",
        "ADLSearchManager",
        "DebugManager",
        "TimerManager",
        "ResourceManager",
    ]

    CORE_TYPES = [
        "CID",
        "TTHValue",
        "UserPtr",
        "User",
        "HintedUser",
        "Identity",
        "HubEntry",
        "FavoriteHubEntry",
        "UserCommand",
        "DCContext",
        "ContextAware",
        "IPFilter",
        "ADLSearch",
        "QueueItem",
        "FavoriteUser",
    ]

    @pytest.mark.parametrize("name", MANAGER_TYPES)
    def test_manager_type_exists(self, name):
        assert hasattr(dc_core, name), f"Missing type: {name}"

    @pytest.mark.parametrize("name", CORE_TYPES)
    def test_core_type_exists(self, name):
        assert hasattr(dc_core, name), f"Missing type: {name}"

    def test_dcpp_startup_exists(self):
        assert hasattr(dc_core, "dcpp_startup")

    def test_dcpp_shutdown_exists(self):
        assert hasattr(dc_core, "dcpp_shutdown")


# ============================================================================
# CID tests
# ============================================================================

class TestCID:
    def test_default_construct(self):
        c = dc_core.CID()
        assert c is not None

    def test_str(self):
        c = dc_core.CID()
        s = str(c)
        assert len(s) > 0

    def test_repr(self):
        c = dc_core.CID()
        r = repr(c)
        assert r.startswith("CID('")

    def test_hash(self):
        c = dc_core.CID()
        h = hash(c)
        assert isinstance(h, int)

    def test_equality(self):
        c1 = dc_core.CID()
        c2 = dc_core.CID()
        assert c1 == c2

    def test_from_base32(self):
        c = dc_core.CID("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
        assert str(c) == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

    def test_generate(self):
        c = dc_core.CID.generate()
        s = str(c)
        assert len(s) > 0
        # Generated CID should not be all zeros
        assert s != "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


# ============================================================================
# TTHValue tests
# ============================================================================

class TestTTHValue:
    def test_default_construct(self):
        t = dc_core.TTHValue()
        assert t is not None

    def test_str(self):
        t = dc_core.TTHValue()
        s = str(t)
        assert len(s) > 0

    def test_repr(self):
        t = dc_core.TTHValue()
        r = repr(t)
        assert r.startswith("TTHValue('")

    def test_equality(self):
        t1 = dc_core.TTHValue()
        t2 = dc_core.TTHValue()
        assert t1 == t2


# ============================================================================
# HubEntry tests
# ============================================================================

class TestHubEntry:
    def test_construct(self):
        e = dc_core.HubEntry()
        assert e is not None

    def test_name(self):
        e = dc_core.HubEntry()
        e.setName("Test Hub")
        assert e.getName() == "Test Hub"

    def test_server(self):
        e = dc_core.HubEntry()
        e.setServer("dchub://test:411")
        assert e.getServer() == "dchub://test:411"

    def test_str(self):
        e = dc_core.HubEntry()
        e.setName("TestHub")
        s = str(e)
        assert "TestHub" in s


# ============================================================================
# Identity tests
# ============================================================================

class TestIdentity:
    def test_construct(self):
        i = dc_core.Identity()
        assert i is not None

    def test_nick(self):
        i = dc_core.Identity()
        i.setNick("testuser")
        assert i.getNick() == "testuser"

    def test_description(self):
        i = dc_core.Identity()
        i.setDescription("hello")
        assert i.getDescription() == "hello"

    def test_str(self):
        i = dc_core.Identity()
        i.setNick("bob")
        s = str(i)
        assert "bob" in s

    def test_is_op(self):
        i = dc_core.Identity()
        assert not i.isOp()


# ============================================================================
# UserCommand tests
# ============================================================================

class TestUserCommand:
    def test_construct(self):
        uc = dc_core.UserCommand()
        assert uc is not None

    def test_type_constants(self):
        assert dc_core.UserCommand.TYPE_SEPARATOR == 0
        assert dc_core.UserCommand.TYPE_RAW == 1

    def test_context_constants(self):
        assert dc_core.UserCommand.CONTEXT_HUB == 0x01
        assert dc_core.UserCommand.CONTEXT_USER == 0x02

    def test_set_name(self):
        uc = dc_core.UserCommand()
        uc.setName("test command")
        assert uc.getName() == "test command"


# ============================================================================
# HintedUser tests
# ============================================================================

class TestHintedUser:
    def test_construct(self):
        hu = dc_core.HintedUser()
        assert hu is not None

    def test_str(self):
        hu = dc_core.HintedUser()
        s = str(hu)
        assert "HintedUser" in s


# ============================================================================
# DCContext tests
# ============================================================================

class TestDCContext:
    """Test DCContext type (cannot construct directly — use getContext())."""

    def test_type_exists(self):
        assert hasattr(dc_core, "DCContext")

    def test_no_direct_construction(self):
        """DCContext must not be constructable from Python (class layout
        varies with compile-time flags, so Python-side 'new' would
        allocate an undersized object and corrupt the heap)."""
        with pytest.raises((TypeError, AttributeError)):
            dc_core.DCContext()

    def test_str_via_bridge(self, tmp_path):
        b = dc_core.EisPyContext()
        b.initialize(str(tmp_path) + "/")
        ctx = b.context
        s = str(ctx)
        assert "DCContext" in s
        assert "True" in s  # running after initialize
        b.shutdown()


# ============================================================================
# QueueItem enum tests
# ============================================================================

class TestQueueItemEnum:
    def test_priority_values(self):
        assert dc_core.QueueItem.DEFAULT == -1
        assert dc_core.QueueItem.PAUSED == 0
        assert dc_core.QueueItem.LOWEST == 1
        assert dc_core.QueueItem.LOW == 2
        assert dc_core.QueueItem.NORMAL == 3
        assert dc_core.QueueItem.HIGH == 4
        assert dc_core.QueueItem.HIGHEST == 5


# ============================================================================
# ADLSearch tests
# ============================================================================

class TestADLSearch:
    def test_type_exists(self):
        assert hasattr(dc_core, "ADLSearch")

    def test_manager_type_exists(self):
        assert hasattr(dc_core, "ADLSearchManager")


# ============================================================================
# SettingsManager enum tests
# ============================================================================

class TestSettingsManagerEnums:
    def test_str_settings(self):
        assert hasattr(dc_core.SettingsManager, "NICK")
        assert hasattr(dc_core.SettingsManager, "DESCRIPTION")
        assert hasattr(dc_core.SettingsManager, "DOWNLOAD_DIRECTORY")

    def test_int_settings(self):
        assert hasattr(dc_core.SettingsManager, "SLOTS")
        assert hasattr(dc_core.SettingsManager, "TCP_PORT")
        assert hasattr(dc_core.SettingsManager, "UDP_PORT")

    def test_bool_settings(self):
        assert hasattr(dc_core.SettingsManager, "AUTO_SEARCH")


# ============================================================================
# DCBridge manager property tests (requires initialized bridge)
# ============================================================================

class TestBridgeManagerProperties:
    """Test direct manager access via EisPyContext properties."""

    @pytest.fixture(autouse=True, scope="class")
    def bridge(self, tmp_path_factory):
        cfg = tmp_path_factory.mktemp("dc-manager-tests")
        b = dc_core.EisPyContext()
        ok = b.initialize(str(cfg) + "/")
        assert ok, "Context initialization failed"
        yield b
        b.shutdown()

    def test_context_property(self, bridge):
        ctx = bridge.context
        assert ctx is not None

    def test_settings_manager(self, bridge):
        sm = bridge.settings_manager
        assert sm is not None
        # Read a setting via direct manager access
        nick = sm.get(dc_core.SettingsManager.NICK)
        assert isinstance(nick, str)
        assert len(nick) > 0

    def test_settings_set_get(self, bridge):
        sm = bridge.settings_manager
        sm.set(dc_core.SettingsManager.DESCRIPTION, "swig-test-desc")
        val = sm.get(dc_core.SettingsManager.DESCRIPTION)
        assert val == "swig-test-desc"

    def test_client_manager(self, bridge):
        cm = bridge.client_manager
        assert cm is not None

    def test_queue_manager(self, bridge):
        qm = bridge.queue_manager
        assert qm is not None

    def test_share_manager(self, bridge):
        sm = bridge.share_manager
        assert sm is not None
        # Share size should be 0 with no shares
        size = sm.getShareSize()
        assert size == 0

    def test_search_manager(self, bridge):
        sm = bridge.search_manager
        assert sm is not None

    def test_hash_manager(self, bridge):
        hm = bridge.hash_manager
        assert hm is not None

    def test_download_manager(self, bridge):
        dm = bridge.download_manager
        assert dm is not None

    def test_upload_manager(self, bridge):
        um = bridge.upload_manager
        assert um is not None

    def test_throttle_manager(self, bridge):
        tm = bridge.throttle_manager
        assert tm is not None

    def test_favorite_manager(self, bridge):
        fm = bridge.favorite_manager
        assert fm is not None

    def test_finished_manager(self, bridge):
        fm = bridge.finished_manager
        assert fm is not None

    def test_connectivity_manager(self, bridge):
        cm = bridge.connectivity_manager
        assert cm is not None

    def test_mapping_manager(self, bridge):
        mm = bridge.mapping_manager
        assert mm is not None

    def test_crypto_manager(self, bridge):
        cm = bridge.crypto_manager
        assert cm is not None

    def test_log_manager(self, bridge):
        lm = bridge.log_manager
        assert lm is not None

    def test_adl_search_manager(self, bridge):
        am = bridge.adl_search_manager
        assert am is not None

    def test_debug_manager(self, bridge):
        dm = bridge.debug_manager
        assert dm is not None


# ============================================================================
# DCClient manager property tests
# ============================================================================

class TestDCClientManagerProperties:
    """Test DCClient manager properties delegate to bridge."""

    @pytest.fixture(autouse=True, scope="class")
    def client(self, tmp_path_factory):
        from eiskaltdcpp.dc_client import DCClient
        cfg = tmp_path_factory.mktemp("dc-client-mgr-tests")
        c = DCClient(str(cfg) + "/")
        c.initialize()
        yield c
        c.shutdown()

    MANAGER_PROPERTIES = [
        "settings",
        "clients",
        "queue",
        "shares",
        "search_manager",
        "downloads",
        "uploads",
        "favorites",
        "finished",
        "hashing",
        "throttle",
        "connectivity",
        "crypto",
        "logs",
        "ip_filter",
        "adl_search",
    ]

    @pytest.mark.parametrize("prop", MANAGER_PROPERTIES)
    def test_manager_property_not_none(self, client, prop):
        val = getattr(client, prop)
        assert val is not None, f"DCClient.{prop} returned None"

    def test_settings_direct_access(self, client):
        sm = client.settings
        nick = sm.get(dc_core.SettingsManager.NICK)
        assert isinstance(nick, str)

    def test_share_manager_stats(self, client):
        sm = client.shares
        assert sm.getShareSize() == 0
        assert sm.getSharedFiles() == 0
