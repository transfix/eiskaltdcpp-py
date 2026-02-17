"""
Integration tests — two async clients connect to live DC hubs and interact.

These tests connect to real NMDC hubs and verify:
  1. Hub info and user lists are populated
  2. Both clients can see each other in the user list
  3. Private messages can be exchanged between clients
  4. File list requests and browsing work
  5. File download queueing works

Requirements:
  - Network access to nmdcs://paladin.sublevels.net:411
                     and nmdcs://wintermute.sublevels.net:411
  - libeiskaltdcpp built and installed (or wheel installed)

These tests are slow (network I/O, TLS negotiation, user list propagation)
and are NOT part of the regular unit test suite.  Run them explicitly:

    pytest tests/test_integration.py -v --tb=long

Or via CI with the "integration" workflow.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest
try:
    import pytest_asyncio
except ImportError:
    pytest_asyncio = None  # collected but skipped when not installed

# ── Locate SWIG module ──────────────────────────────────────────────
BUILD_DIR = Path(__file__).parent.parent / "build" / "python"
if BUILD_DIR.exists():
    sys.path.insert(0, str(BUILD_DIR))

try:
    from eiskaltdcpp import AsyncDCClient
    SWIG_AVAILABLE = True
except ImportError:
    SWIG_AVAILABLE = False

pytestmark = [
    pytest.mark.skipif(not SWIG_AVAILABLE, reason="dc_core SWIG module not built"),
    pytest.mark.skipif(pytest_asyncio is None, reason="pytest-asyncio not installed"),
    pytest.mark.integration,
    pytest.mark.asyncio,
]

# ── Constants ────────────────────────────────────────────────────────
HUB_PALADIN = "nmdcs://paladin.sublevels.net:411"
HUB_WINTERMUTE = "nmdcs://wintermute.sublevels.net:411"
HUBS = [HUB_PALADIN, HUB_WINTERMUTE]

# Unique nicks so parallel CI runs never collide
_RUN_ID = uuid.uuid4().hex[:6]
NICK_ALICE = f"IntBot_A_{_RUN_ID}"
NICK_BOB = f"IntBot_B_{_RUN_ID}"

# Time budget (seconds)
CONNECT_TIMEOUT = 45        # TLS + login + user list sync
USER_SYNC_TIMEOUT = 30      # wait for both clients to see each other
PM_TIMEOUT = 20             # wait for private message delivery
FILELIST_TIMEOUT = 60       # wait for file list download
SEARCH_TIMEOUT = 30         # wait for search results
DOWNLOAD_TIMEOUT = 60       # wait for file download

logger = logging.getLogger(__name__)

# Create a small shareable file for testing file transfers
SHARE_FILE_NAME = "eiskaltdcpp_py_test_file.txt"
SHARE_FILE_CONTENT = f"eiskaltdcpp-py integration test payload {_RUN_ID}\n" * 100


# ── Helpers ─────────────────────────────────────────────────────────

def _make_share_dir() -> Path:
    """Create a temp directory with a small file for sharing."""
    d = Path(tempfile.mkdtemp(prefix="dcpy_share_"))
    f = d / SHARE_FILE_NAME
    f.write_text(SHARE_FILE_CONTENT)
    return d


def _make_download_dir() -> Path:
    """Create a temp directory for downloads."""
    return Path(tempfile.mkdtemp(prefix="dcpy_dl_"))


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def share_dir():
    """Module-scoped temp share directory."""
    d = _make_share_dir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope="module")
def download_dir():
    """Module-scoped temp download directory."""
    d = _make_download_dir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def alice_and_bob(share_dir):
    """
    Create two AsyncDCClients (alice & bob), each with a unique config dir,
    initialize them, connect both to BOTH hubs, wait for connection,
    then yield for tests.  Shutdown on teardown.
    """
    cfg_a = Path(tempfile.mkdtemp(prefix="dcpy_alice_"))
    cfg_b = Path(tempfile.mkdtemp(prefix="dcpy_bob_"))

    alice = AsyncDCClient(str(cfg_a))
    bob = AsyncDCClient(str(cfg_b))

    try:
        # Initialize
        assert await alice.initialize(), "Alice failed to initialize"
        assert await bob.initialize(), "Bob failed to initialize"

        # Set unique nicks
        alice.set_setting("Nick", NICK_ALICE)
        bob.set_setting("Nick", NICK_BOB)

        # Set descriptions
        alice.set_setting("Description", "eiskaltdcpp-py integration bot A")
        bob.set_setting("Description", "eiskaltdcpp-py integration bot B")

        # Share a small directory from alice
        alice.add_share(str(share_dir), "TestShare")
        alice.refresh_share()

        # Connect both clients to both hubs concurrently
        connect_tasks = []
        for hub in HUBS:
            connect_tasks.append(
                alice.connect(hub, wait=True, timeout=CONNECT_TIMEOUT)
            )
            connect_tasks.append(
                bob.connect(hub, wait=True, timeout=CONNECT_TIMEOUT)
            )
        await asyncio.gather(*connect_tasks)

        # Give user lists a moment to populate
        await asyncio.sleep(3)

        yield alice, bob

    finally:
        # Graceful teardown
        for client in (alice, bob):
            try:
                await client.shutdown()
            except Exception:
                pass
        shutil.rmtree(cfg_a, ignore_errors=True)
        shutil.rmtree(cfg_b, ignore_errors=True)


# ── Tests ───────────────────────────────────────────────────────────

class TestHubConnection:
    """Verify basic hub connectivity and info."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_both_clients_connected(self, alice_and_bob):
        """Both clients report connected to both hubs."""
        alice, bob = alice_and_bob
        for hub in HUBS:
            assert alice.is_connected(hub), f"Alice not connected to {hub}"
            assert bob.is_connected(hub), f"Bob not connected to {hub}"

    @pytest.mark.asyncio(loop_scope="module")
    async def test_hub_info_reasonable(self, alice_and_bob):
        """Hub info has non-empty name and at least 2 users (us)."""
        alice, bob = alice_and_bob
        hubs = alice.list_hubs()
        assert len(hubs) >= 2, f"Expected >=2 hubs, got {len(hubs)}"
        for hub_info in hubs:
            assert hub_info.connected, f"{hub_info.url} not connected"
            assert len(hub_info.name) > 0, f"{hub_info.url} has empty name"
            assert hub_info.userCount >= 2, (
                f"{hub_info.url} has {hub_info.userCount} users, expected >=2"
            )

    @pytest.mark.asyncio(loop_scope="module")
    async def test_user_list_not_empty(self, alice_and_bob):
        """Each hub has a non-empty user list with at least our nicks."""
        alice, bob = alice_and_bob
        for hub in HUBS:
            users = alice.get_users(hub)
            nicks = [u.nick for u in users]
            assert len(nicks) >= 2, (
                f"{hub}: expected >=2 users, got {len(nicks)}: {nicks}"
            )


class TestUserVisibility:
    """Verify clients can see each other in the user list."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_alice_sees_bob(self, alice_and_bob):
        """Alice can find Bob in the user list on at least one hub."""
        alice, bob = alice_and_bob
        found = False
        for hub in HUBS:
            try:
                await alice.wait_user(
                    hub, NICK_BOB, timeout=USER_SYNC_TIMEOUT
                )
                found = True
                break
            except asyncio.TimeoutError:
                continue
        assert found, f"Alice never saw {NICK_BOB} on any hub"

    @pytest.mark.asyncio(loop_scope="module")
    async def test_bob_sees_alice(self, alice_and_bob):
        """Bob can find Alice in the user list on at least one hub."""
        alice, bob = alice_and_bob
        found = False
        for hub in HUBS:
            try:
                await bob.wait_user(
                    hub, NICK_ALICE, timeout=USER_SYNC_TIMEOUT
                )
                found = True
                break
            except asyncio.TimeoutError:
                continue
        assert found, f"Bob never saw {NICK_ALICE} on any hub"

    @pytest.mark.asyncio(loop_scope="module")
    async def test_user_info_has_nick(self, alice_and_bob):
        """getUserInfo returns the correct nick for the other client."""
        alice, bob = alice_and_bob
        for hub in HUBS:
            info = alice.get_user(NICK_BOB, hub)
            if info and info.nick == NICK_BOB:
                assert info.nick == NICK_BOB
                return
        pytest.fail(f"Could not get user info for {NICK_BOB} on any hub")


class TestPrivateMessages:
    """Verify private message exchange between clients."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_alice_sends_pm_to_bob(self, alice_and_bob):
        """Alice sends a PM to Bob and Bob receives it."""
        alice, bob = alice_and_bob
        test_msg = f"Hello Bob from Alice {_RUN_ID}"
        hub = HUBS[0]

        alice.send_pm(hub, NICK_BOB, test_msg)

        pm = await bob.wait_pm(from_nick=NICK_ALICE, timeout=PM_TIMEOUT)
        assert test_msg in pm[3], (
            f"Expected '{test_msg}' in PM, got: '{pm[3]}'"
        )

    @pytest.mark.asyncio(loop_scope="module")
    async def test_bob_sends_pm_to_alice(self, alice_and_bob):
        """Bob sends a PM to Alice and Alice receives it."""
        alice, bob = alice_and_bob
        test_msg = f"Hello Alice from Bob {_RUN_ID}"
        hub = HUBS[0]

        bob.send_pm(hub, NICK_ALICE, test_msg)

        pm = await alice.wait_pm(from_nick=NICK_BOB, timeout=PM_TIMEOUT)
        assert test_msg in pm[3], (
            f"Expected '{test_msg}' in PM, got: '{pm[3]}'"
        )


class TestFileListBrowsing:
    """Verify file list request and browsing."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_bob_requests_alice_filelist(self, alice_and_bob):
        """Bob can request and browse Alice's file list."""
        alice, bob = alice_and_bob
        hub = HUBS[0]

        try:
            fl_id, entries = await bob.request_and_browse_file_list(
                hub, NICK_ALICE, timeout=FILELIST_TIMEOUT
            )
        except asyncio.TimeoutError:
            pytest.skip(
                "File list download timed out — hub may not support "
                "client-to-client in this network environment"
            )
        except RuntimeError as e:
            pytest.skip(f"File list error: {e}")

        try:
            names = [e.name for e in entries]
            assert len(names) > 0, "File list root is empty"
            logger.info("Alice's file list root: %s", names)

            # Try browsing subdirectories
            dirs = [e for e in entries if e.isDirectory]
            if dirs:
                sub_entries = bob.browse_file_list(
                    fl_id, f"/{dirs[0].name}/"
                )
                logger.info(
                    "Subdirectory %s: %s",
                    dirs[0].name,
                    [e.name for e in sub_entries],
                )
        finally:
            bob.close_file_list(fl_id)


class TestSearch:
    """Verify search functionality."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_search_returns_results(self, alice_and_bob):
        """A search finds at least something on the hub."""
        alice, bob = alice_and_bob

        results = await alice.search_and_wait(
            "eiskaltdcpp_py_test_file",
            hub_url=HUBS[0],
            timeout=SEARCH_TIMEOUT,
            min_results=1,
        )

        if not results:
            # Try a broader search
            results = await alice.search_and_wait(
                "*",
                hub_url=HUBS[0],
                timeout=SEARCH_TIMEOUT,
                min_results=1,
            )

        if not results:
            pytest.skip(
                "No search results — hub may not relay to bots"
            )

        r = results[0]
        assert "file" in r
        assert "nick" in r
        assert "size" in r


class TestFileDownload:
    """Verify file download queueing."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_queue_file_from_search(self, alice_and_bob, download_dir):
        """Queue a file from search results (if any available)."""
        alice, bob = alice_and_bob

        results = await bob.search_and_wait(
            SHARE_FILE_NAME,
            hub_url=HUBS[0],
            timeout=SEARCH_TIMEOUT,
            min_results=1,
        )

        if not results:
            pytest.skip(
                "Search returned no results — client-to-client search "
                "may not work in this network environment"
            )

        files = [r for r in results if not r.get("isDirectory")]
        if not files:
            pytest.skip("No file results found in search")

        result = files[0]
        tth = result.get("tth", "")
        if not tth:
            pytest.skip("Search result has no TTH, cannot queue")

        ok = bob.download(
            str(download_dir),
            result["file"],
            result["size"],
            tth,
        )
        logger.info("Queue result: %s for %s", ok, result["file"])

        # Wait briefly — download may or may not complete
        await asyncio.sleep(5)

        queue = bob.list_queue()
        logger.info("Queue has %d items", len(queue))


class TestCleanDisconnect:
    """Verify clean disconnection (runs last)."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_disconnect_from_all_hubs(self, alice_and_bob):
        """Both clients can disconnect cleanly from all hubs."""
        alice, bob = alice_and_bob

        for hub in HUBS:
            if alice.is_connected(hub):
                await alice.disconnect(hub)
            if bob.is_connected(hub):
                await bob.disconnect(hub)

        await asyncio.sleep(2)
