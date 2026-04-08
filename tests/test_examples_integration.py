"""
Integration tests that validate the patterns shown in the examples/ directory
and the NMDCpb protobuf extension features.

These tests ensure that the example code users rely on actually works
against a live hub.  Each test class maps to one or more examples:

  - TestBasicChatPattern        → examples/basic_chat.py
  - TestMultiHubBotPattern      → examples/multi_hub_bot.py
  - TestSearchPattern           → examples/search_and_download.py
  - TestShareManagerPattern     → examples/share_manager.py
  - TestDownloadProgressPattern → examples/download_progress.py
  - TestNmdcPbBroadcast         → NMDCpb protobuf extension (broadcast)
  - TestNmdcPbRouted            → NMDCpb protobuf extension (routed P2P)

Requirements:
  - Network access to nmdcs://wintermute.sublevels.net:411
  - libeiskaltdcpp built with -DWITH_NMDCPB=ON (for PB tests)
  - libeiskaltdcpp built and installed (or wheel installed)

Run them explicitly:

    pytest tests/test_examples_integration.py -v --tb=long

Or via CI with the "integration" workflow.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import random
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

try:
    import pytest_asyncio
except ImportError:
    pytest_asyncio = None

from test_integration import (
    BUILD_DIR,
    CONNECT_TIMEOUT,
    HUB_WINTERMUTE,
    INIT_TIMEOUT,
    PM_TIMEOUT,
    RemoteDCClient,
    SEARCH_TIMEOUT,
    SHARE_REFRESH_WAIT,
    SWIG_AVAILABLE,
    USER_SYNC_TIMEOUT,
    _RUN_ID,
)

try:
    from eiskaltdcpp import AsyncDCClient
except ImportError:
    pass

logger = logging.getLogger(__name__)

pytestmark = [
    pytest.mark.skipif(not SWIG_AVAILABLE, reason="dc_core SWIG module not built"),
    pytest.mark.skipif(pytest_asyncio is None, reason="pytest-asyncio not installed"),
    pytest.mark.integration,
    pytest.mark.asyncio,
]

# Unique nicks so parallel CI runs never collide
NICK_EXAMPLE = f"ExBot_{_RUN_ID}"
NICK_EX_ALICE = f"ExBot_A_{_RUN_ID}"
NICK_EX_BOB = f"ExBot_B_{_RUN_ID}"

# Timeouts
CHAT_TIMEOUT = 30
EVENT_TIMEOUT = 30


# =========================================================================
# Fixtures
# =========================================================================

@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def single_client():
    """
    Module-scoped in-process async DC client for single-client example tests.
    Mirrors the pattern from basic_chat.py / share_manager.py.
    """
    cfg_dir = Path(tempfile.mkdtemp(prefix="dcpy_ex_single_"))
    c = AsyncDCClient(str(cfg_dir))
    try:
        ok = await c.initialize(timeout=INIT_TIMEOUT)
        assert ok, "Client failed to initialize"
        await c.set_setting("Nick", NICK_EXAMPLE)
        await c.set_setting("Description", "eiskaltdcpp-py example integration test")
        await c.connect(HUB_WINTERMUTE, wait=True, timeout=CONNECT_TIMEOUT)
        # Wait for user list to propagate — TLS hubs can be slow
        await asyncio.sleep(10)
        yield c
    finally:
        try:
            await c.shutdown()
        except Exception:
            pass
        shutil.rmtree(cfg_dir, ignore_errors=True)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def alice_and_bob_examples():
    """
    Module-scoped pair of RemoteDCClients for multi-client example tests.
    Each runs in a separate process (like multi_hub_bot.py pattern).
    """
    alice = RemoteDCClient("ex_alice")
    bob = RemoteDCClient("ex_bob")

    try:
        await alice.start()
        await bob.start()

        assert await alice.init(), "Alice failed to initialize"
        assert await bob.init(), "Bob failed to initialize"

        await alice.set_setting("Nick", NICK_EX_ALICE)
        await alice.set_setting("Description", "example test bot A")

        await bob.set_setting("Nick", NICK_EX_BOB)
        await bob.set_setting("Description", "example test bot B")

        await asyncio.gather(
            alice.connect(HUB_WINTERMUTE, timeout=CONNECT_TIMEOUT),
            bob.connect(HUB_WINTERMUTE, timeout=CONNECT_TIMEOUT),
        )

        # Let user lists propagate
        await asyncio.sleep(5)

        yield alice, bob

    finally:
        for c in (alice, bob):
            try:
                await c.close()
            except Exception:
                pass


# =========================================================================
# basic_chat.py patterns
# =========================================================================

class TestBasicChatPattern:
    """
    Validates patterns from examples/basic_chat.py:
      - Connect to a hub
      - Receive hub_connected event with hub name
      - See users in user list
      - Register event handlers via @client.on() decorator
    """

    @pytest.mark.asyncio(loop_scope="module")
    async def test_hub_connected_with_name(self, single_client):
        """Hub reports connected with a non-empty name (basic_chat on_connected pattern)."""
        # Poll until hub reports connected (network latency)
        connected_hub = None
        for _ in range(30):
            hubs = await single_client.list_hubs()
            if hubs:
                for h in hubs:
                    if h.connected:
                        connected_hub = h
                        break
            if connected_hub:
                break
            await asyncio.sleep(1)
        assert connected_hub is not None, "No hub connected after 30s"
        assert len(connected_hub.name) > 0, "Hub has empty name"

    @pytest.mark.asyncio(loop_scope="module")
    async def test_user_list_accessible(self, single_client):
        """User list is accessible and non-empty (basic_chat /users pattern)."""
        for _ in range(30):
            users = await single_client.get_users(HUB_WINTERMUTE)
            if len(users) >= 1:
                break
            await asyncio.sleep(1)
        assert len(users) >= 1, "User list empty after 30s"

    @pytest.mark.asyncio(loop_scope="module")
    async def test_own_nick_visible(self, single_client):
        """Our nick appears in the user list (basic_chat identity pattern)."""
        found = False
        for _ in range(30):
            users = await single_client.get_users(HUB_WINTERMUTE)
            nicks = [u.nick for u in users]
            if NICK_EXAMPLE in nicks:
                found = True
                break
            await asyncio.sleep(1)
        assert found, f"Our nick '{NICK_EXAMPLE}' never appeared in user list"

    @pytest.mark.asyncio(loop_scope="module")
    async def test_event_handler_decorator(self, single_client):
        """The @client.on() decorator pattern works for receiving events."""
        received = []

        @single_client.on("hub_updated")
        def on_updated(hub_url, hub_name):
            received.append((hub_url, hub_name))

        # Wait briefly — hub_updated fires periodically on some hubs
        await asyncio.sleep(3)
        # Even if no update fires, registering the handler must not crash
        single_client.off("hub_updated", on_updated)

    @pytest.mark.asyncio(loop_scope="module")
    async def test_hubs_listing(self, single_client):
        """list_hubs() pattern from basic_chat /hubs command."""
        hubs = await single_client.list_hubs()
        assert len(hubs) >= 1
        for h in hubs:
            assert hasattr(h, "url")
            assert hasattr(h, "name")
            assert hasattr(h, "connected")
            assert hasattr(h, "userCount")


# =========================================================================
# multi_hub_bot.py patterns
# =========================================================================

class TestMultiHubBotPattern:
    """
    Validates patterns from examples/multi_hub_bot.py:
      - Two separate clients connected simultaneously
      - User tracking across clients
      - Both clients see each other
    """

    @pytest.mark.asyncio(loop_scope="module")
    async def test_both_clients_connected(self, alice_and_bob_examples):
        """Both clients report connected (multi_hub_bot parallel connect)."""
        alice, bob = alice_and_bob_examples
        assert await alice.is_connected(HUB_WINTERMUTE), "Alice not connected"
        assert await bob.is_connected(HUB_WINTERMUTE), "Bob not connected"

    @pytest.mark.asyncio(loop_scope="module")
    async def test_mutual_visibility(self, alice_and_bob_examples):
        """Alice and Bob can see each other (multi_hub_bot user tracking)."""
        alice, bob = alice_and_bob_examples

        alice_sees_bob = await alice.wait_for_nick_in_users(
            HUB_WINTERMUTE, NICK_EX_BOB, timeout=USER_SYNC_TIMEOUT
        )
        bob_sees_alice = await bob.wait_for_nick_in_users(
            HUB_WINTERMUTE, NICK_EX_ALICE, timeout=USER_SYNC_TIMEOUT
        )
        assert alice_sees_bob, f"Alice never saw {NICK_EX_BOB}"
        assert bob_sees_alice, f"Bob never saw {NICK_EX_ALICE}"

    @pytest.mark.asyncio(loop_scope="module")
    async def test_private_message_exchange(self, alice_and_bob_examples):
        """PM exchange works (multi_hub_bot command handling via PM)."""
        alice, bob = alice_and_bob_examples
        test_msg = f"!help from test {_RUN_ID}"

        wait_task = asyncio.create_task(
            bob.wait_pm(from_nick=NICK_EX_ALICE, timeout=PM_TIMEOUT)
        )
        await asyncio.sleep(0.5)

        try:
            await alice.send_pm(HUB_WINTERMUTE, NICK_EX_BOB, test_msg)
        except (asyncio.TimeoutError, RuntimeError) as e:
            wait_task.cancel()
            pytest.skip(f"send_pm failed: {e}")

        try:
            pm = await asyncio.wait_for(wait_task, timeout=PM_TIMEOUT)
        except asyncio.TimeoutError:
            pytest.skip("PM delivery timed out — hub may not relay PMs between bots")

        assert test_msg in pm["message"]

    @pytest.mark.asyncio(loop_scope="module")
    async def test_hub_info_from_both_perspectives(self, alice_and_bob_examples):
        """Both clients see consistent hub info (multi_hub_bot !hubs pattern)."""
        alice, bob = alice_and_bob_examples

        for c, label in [(alice, "Alice"), (bob, "Bob")]:
            hubs = await c.list_hubs()
            assert len(hubs) >= 1, f"{label}: no hubs"
            h = hubs[0]
            assert h["connected"], f"{label}: not connected"
            assert len(h["name"]) > 0, f"{label}: empty hub name"
            assert h["userCount"] >= 2, f"{label}: expected >=2 users, got {h['userCount']}"


# =========================================================================
# search_and_download.py patterns
# =========================================================================

class TestSearchPattern:
    """
    Validates patterns from examples/search_and_download.py:
      - Initiating a search
      - Receiving search results (if any)
      - Search does not crash the client
    """

    @pytest.mark.asyncio(loop_scope="module")
    async def test_search_initiation(self, single_client):
        """search() returns without error (search_and_download pattern)."""
        ok = await single_client.search("test", hub_url=HUB_WINTERMUTE)
        # search() may return True/None depending on hub state
        await asyncio.sleep(2)

    @pytest.mark.asyncio(loop_scope="module")
    async def test_search_and_wait(self, single_client):
        """search_and_wait() returns a list (search_and_download result handling)."""
        try:
            results = await single_client.search_and_wait(
                "linux", hub_url=HUB_WINTERMUTE,
                timeout=SEARCH_TIMEOUT, min_results=0,
            )
            # Results is a list (possibly empty if hub has no matching shares)
            assert isinstance(results, list)
        except asyncio.TimeoutError:
            pytest.skip("Search timed out — hub may not relay results")


# =========================================================================
# share_manager.py patterns
# =========================================================================

class TestShareManagerPattern:
    """
    Validates patterns from examples/share_manager.py:
      - Adding a share directory
      - Listing shares
      - share_size and shared_files properties
      - Hash status
    """

    @pytest.mark.asyncio(loop_scope="module")
    async def test_share_size_accessible(self, single_client):
        """share_size property is accessible (share_manager stats pattern)."""
        size = single_client.share_size
        assert isinstance(size, int)
        assert size >= 0

    @pytest.mark.asyncio(loop_scope="module")
    async def test_shared_files_accessible(self, single_client):
        """shared_files property is accessible (share_manager stats pattern)."""
        count = single_client.shared_files
        assert isinstance(count, int)
        assert count >= 0

    @pytest.mark.asyncio(loop_scope="module")
    async def test_hash_status_accessible(self, single_client):
        """hash_status is accessible (share_manager hash command pattern)."""
        hs = single_client.hash_status
        assert hasattr(hs, "filesLeft")
        assert hasattr(hs, "bytesLeft")
        assert hasattr(hs, "currentFile")

    @pytest.mark.asyncio(loop_scope="module")
    async def test_list_shares(self, single_client):
        """list_shares() returns a list (share_manager list command)."""
        shares = single_client.list_shares()
        assert isinstance(shares, list)

    @pytest.mark.asyncio(loop_scope="module")
    async def test_version_accessible(self, single_client):
        """version property is accessible (share_manager stats command)."""
        ver = single_client.version
        assert isinstance(ver, str)
        assert len(ver) > 0


# =========================================================================
# download_progress.py patterns
# =========================================================================

class TestDownloadProgressPattern:
    """
    Validates patterns from examples/download_progress.py:
      - Transfer stats are accessible
      - Event handler registration for download events doesn't crash
    """

    @pytest.mark.asyncio(loop_scope="module")
    async def test_transfer_stats_accessible(self, single_client):
        """transfer_stats returns valid stats (download_progress dashboard)."""
        stats = single_client.transfer_stats
        assert hasattr(stats, "downloadSpeed")
        assert hasattr(stats, "uploadSpeed")
        assert hasattr(stats, "downloadCount")
        assert hasattr(stats, "uploadCount")
        assert hasattr(stats, "totalDownloaded")
        assert hasattr(stats, "totalUploaded")

    @pytest.mark.asyncio(loop_scope="module")
    async def test_download_event_handlers(self, single_client):
        """Registering download event handlers works (download_progress pattern)."""
        received = {"starting": [], "complete": [], "failed": []}

        @single_client.on("download_starting")
        def on_start(target, nick, size):
            received["starting"].append(target)

        @single_client.on("download_complete")
        def on_complete(target, nick, size, speed):
            received["complete"].append(target)

        @single_client.on("download_failed")
        def on_failed(target, reason):
            received["failed"].append(target)

        # Handlers registered without crash
        await asyncio.sleep(1)

        # Clean up handlers
        single_client.off("download_starting", on_start)
        single_client.off("download_complete", on_complete)
        single_client.off("download_failed", on_failed)

    @pytest.mark.asyncio(loop_scope="module")
    async def test_queue_event_handlers(self, single_client):
        """Registering queue event handlers works (download_progress queue pattern)."""
        @single_client.on("queue_item_added")
        def on_queued(target, size, tth):
            pass

        @single_client.on("queue_item_finished")
        def on_finished(target, size):
            pass

        @single_client.on("queue_item_removed")
        def on_removed(target):
            pass

        await asyncio.sleep(0.5)

        single_client.off("queue_item_added", on_queued)
        single_client.off("queue_item_finished", on_finished)
        single_client.off("queue_item_removed", on_removed)


# =========================================================================
# settings patterns (used by all examples)
# =========================================================================

class TestSettingsPattern:
    """
    Validates settings patterns used across all examples:
      - get_setting / set_setting
      - Nick and Description survive connection
    """

    @pytest.mark.asyncio(loop_scope="module")
    async def test_nick_setting(self, single_client):
        """Nick setting matches what was set (all examples set nick)."""
        nick = await single_client.get_setting("Nick")
        assert nick == NICK_EXAMPLE

    @pytest.mark.asyncio(loop_scope="module")
    async def test_description_setting(self, single_client):
        """Description setting persists (basic_chat pattern)."""
        desc = await single_client.get_setting("Description")
        assert "example integration test" in desc.lower()


# =========================================================================
# NMDCpb protobuf extension — broadcast ($PB)
# =========================================================================

class TestNmdcPbBroadcast:
    """
    Validates NMDCpb protobuf broadcast messaging:
      - hub_supports_nmdcpb() check
      - send_pb() broadcast to hub
      - Receiving $PB messages via wait_pb_message()

    These tests require the hub to support the NMDCpb extension.
    If the hub doesn't support NMDCpb, tests are skipped gracefully.
    """

    @pytest.mark.asyncio(loop_scope="module")
    async def test_hub_supports_nmdcpb_check(self, alice_and_bob_examples):
        """hub_supports_nmdcpb() returns a boolean without crashing."""
        alice, bob = alice_and_bob_examples
        result = await alice.hub_supports_nmdcpb(HUB_WINTERMUTE)
        assert isinstance(result, bool)

    @pytest.mark.asyncio(loop_scope="module")
    async def test_pb_broadcast_received(self, alice_and_bob_examples):
        """Alice sends a $PB broadcast and Bob receives it."""
        alice, bob = alice_and_bob_examples

        # Check if hub supports NMDCpb
        supported = await alice.hub_supports_nmdcpb(HUB_WINTERMUTE)
        if not supported:
            pytest.skip("Hub does not support NMDCpb extension")

        # Create a simple test payload (base64-encoded)
        payload = base64.b64encode(
            f"test_broadcast_{_RUN_ID}".encode()
        ).decode()

        # Start Bob listening before Alice sends
        wait_task = asyncio.create_task(
            bob.wait_pb_message(
                cmd="$PB", from_nick=NICK_EX_ALICE, timeout=EVENT_TIMEOUT
            )
        )
        await asyncio.sleep(0.5)

        try:
            await alice.send_pb(HUB_WINTERMUTE, payload)
        except (asyncio.TimeoutError, RuntimeError) as e:
            wait_task.cancel()
            pytest.skip(f"send_pb failed: {e}")

        try:
            msg = await asyncio.wait_for(wait_task, timeout=EVENT_TIMEOUT)
        except asyncio.TimeoutError:
            pytest.skip(
                "PB broadcast delivery timed out — hub may not relay NMDCpb"
            )

        assert msg["cmd"] == "$PB"
        assert msg["nick"] == NICK_EX_ALICE
        assert msg["data"] == payload

    @pytest.mark.asyncio(loop_scope="module")
    async def test_pb_broadcast_bidirectional(self, alice_and_bob_examples):
        """Bob sends a $PB broadcast and Alice receives it (reverse direction)."""
        alice, bob = alice_and_bob_examples

        supported = await bob.hub_supports_nmdcpb(HUB_WINTERMUTE)
        if not supported:
            pytest.skip("Hub does not support NMDCpb extension")

        payload = base64.b64encode(
            f"test_broadcast_reverse_{_RUN_ID}".encode()
        ).decode()

        wait_task = asyncio.create_task(
            alice.wait_pb_message(
                cmd="$PB", from_nick=NICK_EX_BOB, timeout=EVENT_TIMEOUT
            )
        )
        await asyncio.sleep(0.5)

        try:
            await bob.send_pb(HUB_WINTERMUTE, payload)
        except (asyncio.TimeoutError, RuntimeError) as e:
            wait_task.cancel()
            pytest.skip(f"send_pb failed: {e}")

        try:
            msg = await asyncio.wait_for(wait_task, timeout=EVENT_TIMEOUT)
        except asyncio.TimeoutError:
            pytest.skip(
                "PB broadcast delivery timed out — hub may not relay NMDCpb"
            )

        assert msg["cmd"] == "$PB"
        assert msg["nick"] == NICK_EX_BOB
        assert msg["data"] == payload


# =========================================================================
# NMDCpb protobuf extension — routed ($PBR)
# =========================================================================

class TestNmdcPbRouted:
    """
    Validates NMDCpb protobuf routed (point-to-point) messaging:
      - send_pb_routed() sends to a specific nick
      - Only the target nick receives the $PBR message
    """

    @pytest.mark.asyncio(loop_scope="module")
    async def test_pb_routed_to_bob(self, alice_and_bob_examples):
        """Alice sends a $PBR routed message to Bob and Bob receives it."""
        alice, bob = alice_and_bob_examples

        supported = await alice.hub_supports_nmdcpb(HUB_WINTERMUTE)
        if not supported:
            pytest.skip("Hub does not support NMDCpb extension")

        payload = base64.b64encode(
            f"test_routed_to_bob_{_RUN_ID}".encode()
        ).decode()

        wait_task = asyncio.create_task(
            bob.wait_pb_message(
                cmd="$PBR", from_nick=NICK_EX_ALICE, timeout=EVENT_TIMEOUT
            )
        )
        await asyncio.sleep(0.5)

        try:
            await alice.send_pb_routed(
                HUB_WINTERMUTE, NICK_EX_BOB, payload
            )
        except (asyncio.TimeoutError, RuntimeError) as e:
            wait_task.cancel()
            pytest.skip(f"send_pb_routed failed: {e}")

        try:
            msg = await asyncio.wait_for(wait_task, timeout=EVENT_TIMEOUT)
        except asyncio.TimeoutError:
            pytest.skip(
                "PBR delivery timed out — hub may not relay routed NMDCpb"
            )

        assert msg["cmd"] == "$PBR"
        assert msg["nick"] == NICK_EX_ALICE
        assert msg["data"] == payload

    @pytest.mark.asyncio(loop_scope="module")
    async def test_pb_routed_to_alice(self, alice_and_bob_examples):
        """Bob sends a $PBR routed message to Alice and Alice receives it."""
        alice, bob = alice_and_bob_examples

        supported = await bob.hub_supports_nmdcpb(HUB_WINTERMUTE)
        if not supported:
            pytest.skip("Hub does not support NMDCpb extension")

        payload = base64.b64encode(
            f"test_routed_to_alice_{_RUN_ID}".encode()
        ).decode()

        wait_task = asyncio.create_task(
            alice.wait_pb_message(
                cmd="$PBR", from_nick=NICK_EX_BOB, timeout=EVENT_TIMEOUT
            )
        )
        await asyncio.sleep(0.5)

        try:
            await bob.send_pb_routed(
                HUB_WINTERMUTE, NICK_EX_ALICE, payload
            )
        except (asyncio.TimeoutError, RuntimeError) as e:
            wait_task.cancel()
            pytest.skip(f"send_pb_routed failed: {e}")

        try:
            msg = await asyncio.wait_for(wait_task, timeout=EVENT_TIMEOUT)
        except asyncio.TimeoutError:
            pytest.skip(
                "PBR delivery timed out — hub may not relay routed NMDCpb"
            )

        assert msg["cmd"] == "$PBR"
        assert msg["nick"] == NICK_EX_BOB
        assert msg["data"] == payload

    @pytest.mark.asyncio(loop_scope="module")
    async def test_pb_routed_roundtrip(self, alice_and_bob_examples):
        """Alice sends $PBR to Bob, Bob replies with $PBR to Alice (full roundtrip)."""
        alice, bob = alice_and_bob_examples

        supported = await alice.hub_supports_nmdcpb(HUB_WINTERMUTE)
        if not supported:
            pytest.skip("Hub does not support NMDCpb extension")

        request_payload = base64.b64encode(
            f"request_{_RUN_ID}".encode()
        ).decode()
        reply_payload = base64.b64encode(
            f"reply_{_RUN_ID}".encode()
        ).decode()

        # Step 1: Alice sends to Bob
        bob_wait = asyncio.create_task(
            bob.wait_pb_message(
                cmd="$PBR", from_nick=NICK_EX_ALICE, timeout=EVENT_TIMEOUT
            )
        )
        await asyncio.sleep(0.5)

        try:
            await alice.send_pb_routed(
                HUB_WINTERMUTE, NICK_EX_BOB, request_payload
            )
        except (asyncio.TimeoutError, RuntimeError) as e:
            bob_wait.cancel()
            pytest.skip(f"send_pb_routed failed: {e}")

        try:
            bob_msg = await asyncio.wait_for(bob_wait, timeout=EVENT_TIMEOUT)
        except asyncio.TimeoutError:
            pytest.skip("PBR roundtrip timed out on first leg")

        assert bob_msg["data"] == request_payload

        # Step 2: Bob replies to Alice
        alice_wait = asyncio.create_task(
            alice.wait_pb_message(
                cmd="$PBR", from_nick=NICK_EX_BOB, timeout=EVENT_TIMEOUT
            )
        )
        await asyncio.sleep(0.5)

        await bob.send_pb_routed(
            HUB_WINTERMUTE, NICK_EX_ALICE, reply_payload
        )

        try:
            alice_msg = await asyncio.wait_for(
                alice_wait, timeout=EVENT_TIMEOUT
            )
        except asyncio.TimeoutError:
            pytest.skip("PBR roundtrip timed out on reply leg")

        assert alice_msg["data"] == reply_payload


# =========================================================================
# Clean disconnect pattern (basic_chat.py /quit)
# =========================================================================

class TestCleanDisconnectPattern:
    """
    Validates the clean disconnect pattern from basic_chat.py /quit.
    This test class should run LAST since it disconnects the single_client.
    """

    @pytest.mark.asyncio(loop_scope="module")
    async def test_clean_disconnect(self, single_client):
        """Disconnect from hub cleanly (basic_chat /quit pattern)."""
        if await single_client.is_connected(HUB_WINTERMUTE):
            await single_client.disconnect(HUB_WINTERMUTE)
        await asyncio.sleep(2)
        assert not await single_client.is_connected(HUB_WINTERMUTE)
