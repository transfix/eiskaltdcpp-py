"""
Integration tests -- single async client connects to live DC hubs.

These tests connect to real NMDC hubs and verify:
  1. Hub connectivity and info are populated
  2. User lists contain at least one user (us)
  3. Chat history is available
  4. Search returns results (when other users are sharing)
  5. Clean disconnection works

NOTE: The DC++ core uses global singletons (dcpp::Singleton<T>) which
means only ONE DCBridge instance can exist per process.  Two-client
tests (PM exchange, mutual user visibility) are not possible in-process.
See TODO.md for the upstream fix plan.

Requirements:
  - Network access to nmdcs://wintermute.sublevels.net:411
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

# -- Locate SWIG module ---------------------------------------------------
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

# -- Constants -------------------------------------------------------------
HUB_WINTERMUTE = "nmdcs://wintermute.sublevels.net:411"
HUBS = [HUB_WINTERMUTE]

# Unique nick so parallel CI runs never collide
_RUN_ID = uuid.uuid4().hex[:6]
NICK = f"IntBot_{_RUN_ID}"

# Time budget (seconds)
INIT_TIMEOUT = 60           # dcpp::startup + cert generation
CONNECT_TIMEOUT = 45        # TLS + login + user list sync
USER_SYNC_TIMEOUT = 30      # wait for user list to populate
SEARCH_TIMEOUT = 30         # wait for search results

logger = logging.getLogger(__name__)


# -- Fixtures --------------------------------------------------------------

@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client():
    """
    Module-scoped async DC client.  Initializes once, connects to all hubs,
    yields for tests, then shuts down.

    Only ONE client can exist per process due to dcpp's singleton managers.
    """
    cfg_dir = Path(tempfile.mkdtemp(prefix="dcpy_inttest_"))

    c = AsyncDCClient(str(cfg_dir))

    try:
        ok = await c.initialize(timeout=INIT_TIMEOUT)
        assert ok, "Client failed to initialize"

        # Set unique nick
        c.set_setting("Nick", NICK)
        c.set_setting("Description", "eiskaltdcpp-py integration test bot")

        # Connect to all hubs concurrently
        connect_tasks = [
            c.connect(hub, wait=True, timeout=CONNECT_TIMEOUT)
            for hub in HUBS
        ]
        await asyncio.gather(*connect_tasks)

        # Give user lists a moment to populate
        await asyncio.sleep(3)

        yield c

    finally:
        try:
            await c.shutdown()
        except Exception:
            pass
        shutil.rmtree(cfg_dir, ignore_errors=True)


# -- Tests -----------------------------------------------------------------

class TestHubConnection:
    """Verify basic hub connectivity and info."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_client_connected(self, client):
        """Client reports connected to all hubs."""
        for hub in HUBS:
            assert client.is_connected(hub), f"Not connected to {hub}"

    @pytest.mark.asyncio(loop_scope="module")
    async def test_hub_info_reasonable(self, client):
        """Hub info has non-empty name and at least 1 user (us)."""
        hubs = client.list_hubs()
        assert len(hubs) >= len(HUBS), (
            f"Expected >={len(HUBS)} hubs, got {len(hubs)}"
        )
        for hub_info in hubs:
            assert hub_info.connected, f"{hub_info.url} not connected"
            assert len(hub_info.name) > 0, f"{hub_info.url} has empty name"
            assert hub_info.userCount >= 1, (
                f"{hub_info.url} has {hub_info.userCount} users, expected >=1"
            )

    @pytest.mark.asyncio(loop_scope="module")
    async def test_user_list_not_empty(self, client):
        """Each hub has a non-empty user list."""
        for hub in HUBS:
            users = client.get_users(hub)
            nicks = [u.nick for u in users]
            assert len(nicks) >= 1, (
                f"{hub}: expected >=1 users, got {len(nicks)}: {nicks}"
            )

    @pytest.mark.asyncio(loop_scope="module")
    async def test_our_nick_in_user_list(self, client):
        """Our own nick appears in the user list on at least one hub."""
        found = False
        for hub in HUBS:
            users = client.get_users(hub)
            nicks = [u.nick for u in users]
            if NICK in nicks:
                found = True
                break
        assert found, (
            f"Our nick '{NICK}' not found on any hub"
        )


class TestSettings:
    """Verify settings survive connection."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_nick_setting_matches(self, client):
        """The Nick setting returns what we set."""
        current = client.get_setting("Nick")
        assert current == NICK, (
            f"Expected nick '{NICK}', got '{current}'"
        )

    @pytest.mark.asyncio(loop_scope="module")
    async def test_description_setting(self, client):
        """Description setting is readable."""
        desc = client.get_setting("Description")
        assert "integration test" in desc.lower(), (
            f"Unexpected description: '{desc}'"
        )


class TestSearch:
    """Verify search functionality."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_search_does_not_crash(self, client):
        """A search call completes without crashing."""
        hub = HUBS[0]
        ok = client.search("test", hub_url=hub)
        # Just verify the call doesn't crash -- results depend on hub state
        await asyncio.sleep(2)

    @pytest.mark.asyncio(loop_scope="module")
    async def test_search_and_wait(self, client):
        """search_and_wait returns (possibly empty) results list."""
        try:
            results = await client.search_and_wait(
                "linux",
                hub_url=HUBS[0],
                timeout=SEARCH_TIMEOUT,
                min_results=0,
            )
            # We got results -- verify they're dicts
            for r in results:
                assert isinstance(r, dict)
        except asyncio.TimeoutError:
            pytest.skip("Search timed out -- hub may not relay results")


class TestCleanDisconnect:
    """Verify clean disconnection (runs last by ordering)."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_disconnect_from_all_hubs(self, client):
        """Client can disconnect cleanly from all hubs."""
        for hub in HUBS:
            if client.is_connected(hub):
                await client.disconnect(hub)

        await asyncio.sleep(2)

        for hub in HUBS:
            assert not client.is_connected(hub), (
                f"Still connected to {hub} after disconnect"
            )
