"""
Async lifecycle tests for AsyncDCClient with a live DC core.

These tests run in a **separate process** from test_dc_core.py because
dcpp's global singletons (SettingsManager, ShareManager, etc.) only
support a single startup()/shutdown() cycle per process.

All tests share one class-scoped AsyncDCClient fixture that initializes
the core once and shuts it down after the last test.
"""
import asyncio
import sys
from pathlib import Path

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


@pytest.mark.asyncio(loop_scope="class")
class TestAsyncClientLifecycle:
    """Tests that exercise the full async lifecycle with a live DC core.

    A class-scoped fixture initializes a single AsyncDCClient and shuts
    it down after all tests in this class run, because dcpp's global
    singletons don't support repeated startup()/shutdown() cycles in the
    same process.
    """

    @pytest_asyncio.fixture(autouse=True, scope="class", loop_scope="class")
    async def client(self, tmp_path_factory):
        """Create and initialize a single async client for all tests.

        Skips the entire class when dcpp's global singletons have already
        been consumed by another test file in the same process (e.g.
        test_dc_core.py's TestBridgeSettings).  Run this file on its own
        for full coverage:  ``pytest tests/test_async_lifecycle.py``
        """
        from eiskaltdcpp.async_client import AsyncDCClient
        cfg = tmp_path_factory.mktemp("async-lifecycle")
        c = AsyncDCClient(str(cfg) + "/")
        ok = await c.initialize(timeout=30)
        if not ok:
            pytest.skip(
                "dcpp singleton already consumed — run this file separately: "
                "pytest tests/test_async_lifecycle.py"
            )
        yield c
        await c.shutdown()

    async def test_is_initialized(self, client):
        """Client reports initialized after initialize()."""
        assert client.is_initialized

    async def test_repr_shows_initialized(self, client):
        """repr reflects initialized state."""
        r = repr(client)
        assert "initialized" in r
        assert "not initialized" not in r

    async def test_version_after_init(self, client):
        """Version string is available after init."""
        v = client.version
        assert isinstance(v, str)
        assert len(v) > 0

    # -- Settings ----------------------------------------------------------

    async def test_set_and_get_setting(self, client):
        """Settings round-trip correctly."""
        client.set_setting("Description", "async-test-bot")
        assert client.get_setting("Description") == "async-test-bot"

    async def test_default_nick_assigned(self, client):
        """Default auto-generated nick starts with 'dcpy-'."""
        nick = client.get_setting("Nick")
        assert nick.startswith("dcpy-"), f"Expected 'dcpy-' prefix, got {nick!r}"

    async def test_unknown_setting_returns_empty(self, client):
        """Unknown setting name returns empty string."""
        assert client.get_setting("TotallyBogus12345") == ""

    # -- Hub state before connection ---------------------------------------

    async def test_not_connected_to_nonexistent_hub(self, client):
        """is_connected returns False for a hub we never connected to."""
        assert not client.is_connected("dchub://nonexistent.example.com:411")

    async def test_list_hubs_empty_before_connect(self, client):
        """list_hubs returns an empty list before any connections."""
        hubs = client.list_hubs()
        assert isinstance(hubs, list)

    async def test_get_users_empty_for_unknown_hub(self, client):
        """get_users returns empty list for a hub we aren't on."""
        users = client.get_users("dchub://nonexistent.example.com:411")
        assert isinstance(users, list)
        assert len(users) == 0

    # -- Sharing -----------------------------------------------------------

    async def test_share_size_zero_initially(self, client):
        """Share size is 0 before adding any directories."""
        assert client.share_size == 0

    async def test_shared_files_zero_initially(self, client):
        """Shared file count is 0 before adding any directories."""
        assert client.shared_files == 0

    async def test_list_shares_empty_initially(self, client):
        """Share directory list is empty initially."""
        shares = client.list_shares()
        assert isinstance(shares, list)
        assert len(shares) == 0

    async def test_add_and_remove_share(self, client, tmp_path_factory):
        """add_share / list_shares / remove_share round-trip."""
        share_dir = tmp_path_factory.mktemp("share-roundtrip")
        ok = client.add_share(str(share_dir) + "/", "RoundTripTest")
        assert ok

        shares = client.list_shares()
        vnames = [s.virtualName for s in shares]
        assert "RoundTripTest" in vnames

        ok2 = client.remove_share(str(share_dir) + "/")
        assert ok2
        shares_after = client.list_shares()
        vnames_after = [s.virtualName for s in shares_after]
        assert "RoundTripTest" not in vnames_after

    # -- Download queue ----------------------------------------------------

    async def test_list_queue_empty_initially(self, client):
        """Download queue is empty at start."""
        q = client.list_queue()
        assert isinstance(q, list)
        assert len(q) == 0

    async def test_clear_queue_no_error(self, client):
        """clear_queue doesn't raise on an empty queue."""
        client.clear_queue()

    # -- Search results ----------------------------------------------------

    async def test_search_results_empty_initially(self, client):
        """Search results are empty before any search."""
        results = client.get_search_results("")
        assert isinstance(results, list)
        assert len(results) == 0

    async def test_clear_search_results_no_error(self, client):
        """clear_search_results doesn't raise."""
        client.clear_search_results("")

    # -- Transfer stats / hash status --------------------------------------

    async def test_transfer_stats_accessible(self, client):
        """transfer_stats returns a TransferStats object."""
        stats = client.transfer_stats
        assert hasattr(stats, "downloadSpeed")
        assert hasattr(stats, "uploadSpeed")
        assert hasattr(stats, "downloadCount")
        assert hasattr(stats, "uploadCount")

    async def test_transfer_stats_zero_initially(self, client):
        """No transfers have occurred, speeds should be 0."""
        stats = client.transfer_stats
        assert stats.downloadCount == 0
        assert stats.uploadCount == 0

    async def test_hash_status_accessible(self, client):
        """hash_status returns a HashStatus object."""
        hs = client.hash_status
        assert hasattr(hs, "filesLeft")
        assert hasattr(hs, "bytesLeft")

    async def test_pause_hashing_no_error(self, client):
        """pause_hashing / unpause doesn't raise."""
        client.pause_hashing(True)
        client.pause_hashing(False)

    # -- Chat history (no hub) ---------------------------------------------

    async def test_chat_history_empty_for_unknown_hub(self, client):
        """get_chat_history returns empty for a hub we aren't on."""
        history = client.get_chat_history("dchub://nonexistent:411", 10)
        assert isinstance(history, list)
        assert len(history) == 0

    # -- File lists --------------------------------------------------------

    async def test_close_all_file_lists_no_error(self, client):
        """close_all_file_lists doesn't raise when none are open."""
        client.close_all_file_lists()
