"""
File transfer integration tests -- separated from test_integration.py so
that the module-scoped ``alice_bob_with_shares`` fixture does NOT overlap
with the ``client`` and ``alice_and_bob`` fixtures from test_integration.

By the time pytest collects this module, test_integration's module-scoped
fixtures have been torn down, keeping peak memory at 2 DC client processes
instead of 5.

Requirements (same as test_integration.py):
  - Network access to nmdcs://wintermute.sublevels.net:411
  - libeiskaltdcpp built and installed (or wheel installed)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import socket
import shutil
import tempfile
from pathlib import Path

import pytest

try:
    import pytest_asyncio
except ImportError:
    pytest_asyncio = None

# Re-use shared infrastructure from the main integration module.
from test_integration import (
    BUILD_DIR,
    CONNECT_TIMEOUT,
    DOWNLOAD_TIMEOUT,
    FILE_LIST_TIMEOUT,
    HUB_WINTERMUTE,
    INIT_TIMEOUT,
    NICK_ALICE_FT,
    NICK_BOB_FT,
    RemoteDCClient,
    SHARE_REFRESH_WAIT,
    SWIG_AVAILABLE,
    USER_SYNC_TIMEOUT,
    _generate_test_file,
    _RUN_ID,
)

logger = logging.getLogger(__name__)


def _direct_connectivity_available() -> bool:
    """Check if this machine can accept inbound TCP from its public IP.

    File transfer tests require at least one bot to be directly reachable
    (active mode).  When both bots are behind NAT without port forwarding
    the hub rewrites the IP in $ConnectToMe to the public address but the
    connection times out because no port is forwarded.

    Returns True when the env-var DC_FILE_TRANSFER=1 is set (opt-in) or
    when a quick loopback-via-public-IP test succeeds (hairpin NAT / port
    forwarding).
    """
    if os.environ.get("DC_FILE_TRANSFER", "").strip() == "1":
        return True

    import urllib.request

    # Discover our public IPv4.
    try:
        ext_ip = urllib.request.urlopen(
            "https://api.ipify.org", timeout=5,
        ).read().decode().strip()
    except Exception:
        return False

    # Open a temp listener and try to reach it via the public IP.
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        srv.settimeout(3)

        cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cli.settimeout(2)
        try:
            cli.connect((ext_ip, port))
            srv.accept()
            reachable = True
        except OSError:
            reachable = False
        finally:
            cli.close()
            srv.close()
        return reachable
    except OSError:
        return False


_DIRECT_OK = _direct_connectivity_available()

pytestmark = [
    pytest.mark.skipif(not SWIG_AVAILABLE, reason="dc_core SWIG module not built"),
    pytest.mark.skipif(pytest_asyncio is None, reason="pytest-asyncio not installed"),
    pytest.mark.skipif(
        not _DIRECT_OK,
        reason="no direct inbound connectivity (set DC_FILE_TRANSFER=1 to force)",
    ),
    pytest.mark.integration,
    pytest.mark.asyncio,
]


# =========================================================================
# Fixture — alice_bob_with_shares (module-scoped, isolated from other tests)
# =========================================================================

@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def alice_bob_with_shares():
    """
    Alice and Bob with shared directories containing test files.

    Alice shares a ~2MB text file and a ~1.5MB binary file.
    Bob shares a ~2MB binary file.
    Both set up download directories.
    """
    alice = RemoteDCClient("alice_ft")
    bob = RemoteDCClient("bob_ft")

    # Temp dirs for shares and downloads
    alice_share = Path(tempfile.mkdtemp(prefix="dcpy_alice_share_"))
    bob_share = Path(tempfile.mkdtemp(prefix="dcpy_bob_share_"))
    alice_dl = Path(tempfile.mkdtemp(prefix="dcpy_alice_dl_"))
    bob_dl = Path(tempfile.mkdtemp(prefix="dcpy_bob_dl_"))

    # Generate test files
    alice_text_hash = _generate_test_file(
        alice_share / "test_document.txt", 2 * 1024 * 1024, binary=False,
    )
    alice_bin_hash = _generate_test_file(
        alice_share / "test_binary.dat", 1536 * 1024, binary=True,
    )
    bob_bin_hash = _generate_test_file(
        bob_share / "bob_payload.bin", 2 * 1024 * 1024, binary=True,
    )

    file_hashes = {
        "test_document.txt": alice_text_hash,
        "test_binary.dat": alice_bin_hash,
        "bob_payload.bin": bob_bin_hash,
    }

    try:
        await alice.start()
        await bob.start()

        assert await alice.init(), "Alice (FT) failed to initialize"
        assert await bob.init(), "Bob (FT) failed to initialize"

        # The DC++ hasher thread starts paused and won't unpause until
        # HASHING_START_DELAY seconds of uptime have elapsed (default 60s).
        # Set to 0 so hashing can begin immediately.
        await alice.set_setting("HashingStartDelay", "0")
        await bob.set_setting("HashingStartDelay", "0")

        await alice.set_setting("Nick", NICK_ALICE_FT)
        await alice.set_setting("Description", "eiskaltdcpp-py FT test bot A")
        await alice.set_setting("DownloadDirectory", str(alice_dl) + "/")

        await bob.set_setting("Nick", NICK_BOB_FT)
        await bob.set_setting("Description", "eiskaltdcpp-py FT test bot B")
        await bob.set_setting("DownloadDirectory", str(bob_dl) + "/")

        # Connection mode: alice = ACTIVE (listens for incoming connections),
        # bob = PASSIVE (asks peers to connect to him via $RevConnectToMe).
        #
        # This avoids having alice process incoming $ConnectToMe messages,
        # which can trigger heap-corruption-related std::bad_alloc on some
        # hubs due to the volume of protocol traffic from other users.
        # With bob passive, the flow is:
        #   bob  → hub: $RevConnectToMe bob alice
        #   hub  → alice: $RevConnectToMe bob alice
        #   alice → hub: $ConnectToMe alice bob <alice_ip>:<port>   (no allocation)
        #   hub  → bob: $ConnectToMe alice bob <ip>:<port>
        #   bob  → alice: TCP connect  (bob's heap is clean)
        #
        # NOTE: Use the actual SettingsManager enum names (UPPER_SNAKE_CASE),
        # not DC++ GUI names — SWIG exposes the C++ enum identifiers.

        # Alice: active — opens TCP/TLS listeners
        await alice.set_setting("INCOMING_CONNECTIONS", "0")  # Active/Direct
        await alice.set_setting("TCP_PORT", "4200")
        await alice.set_setting("UDP_PORT", "4200")
        await alice.set_setting("TLS_PORT", "4201")
        await alice.set_setting("EXTERNAL_IP", "127.0.0.1")
        await alice.set_setting("NO_IP_OVERRIDE", "1")
        await alice.set_setting("AUTO_DETECT_CONNECTION", "0")
        await alice.set_setting("SLOTS", "3")

        # Bob: passive — no TCP listener, relies on $RevConnectToMe
        await bob.set_setting("INCOMING_CONNECTIONS", "3")  # INCOMING_FIREWALL_PASSIVE
        await bob.set_setting("AUTO_DETECT_CONNECTION", "0")
        await bob.set_setting("SLOTS", "3")

        # Reduce memory footprint: disable DHT and transfer compression
        # to keep RAM usage low on CI runners.
        for client_obj in (alice, bob):
            await client_obj.set_setting("USE_DHT", "0")
            await client_obj.set_setting("COMPRESS_TRANSFERS", "0")
            await client_obj.set_setting("MAX_COMPRESSION", "0")
            await client_obj.set_setting("BUFFER_SIZE", "64")
            # Limit $GetINFO requests sent during $NickList processing.
            # This only controls how many users we explicitly request info for;
            # all users are still tracked via $MyINFO broadcasts from the hub.
            await client_obj.set_setting("NMDC_GETINFO_LIMIT", "100")

        # Apply the connection settings (opens TCP/UDP listeners)
        await alice.start_networking()
        await bob.start_networking()

        # Share directories
        assert await alice.add_share(str(alice_share) + "/", "AliceFiles")
        assert await bob.add_share(str(bob_share) + "/", "BobFiles")

        # Refresh to discover files & queue them for hashing.
        await alice.refresh_share()
        await bob.refresh_share()

        # The hasher thread starts paused.  Explicitly resume hashing.
        await asyncio.sleep(3)
        await alice.resume_hashing()
        await bob.resume_hashing()

        # Connect both to the hub while hashing runs in the background
        await asyncio.gather(
            alice.connect(HUB_WINTERMUTE, timeout=CONNECT_TIMEOUT),
            bob.connect(HUB_WINTERMUTE, timeout=CONNECT_TIMEOUT),
        )

        # Poll: re-refresh the share tree each iteration so that newly-
        # hashed files get included, then check the total share size.
        expected_alice = 2 * 1024 * 1024 + 1536 * 1024   # ~3.5 MB
        expected_bob = 2 * 1024 * 1024                     # ~2 MB
        deadline = asyncio.get_event_loop().time() + SHARE_REFRESH_WAIT
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(3)
            await alice.refresh_share()
            await bob.refresh_share()
            await asyncio.sleep(2)  # let the refresh thread finish
            a_sz = await alice.get_share_size()
            b_sz = await bob.get_share_size()
            if a_sz >= expected_alice and b_sz >= expected_bob:
                break
        else:
            # Gather diagnostics before failing
            a_sz = await alice.get_share_size()
            b_sz = await bob.get_share_size()
            a_hs = await alice.get_hash_status()
            b_hs = await bob.get_hash_status()
            assert False, (
                f"Share hashing did not complete in {SHARE_REFRESH_WAIT}s. "
                f"Alice share: {a_sz}/{expected_alice} (hash: {a_hs}), "
                f"Bob share: {b_sz}/{expected_bob} (hash: {b_hs})"
            )

        yield alice, bob, file_hashes, alice_dl, bob_dl

    finally:
        for c in (alice, bob):
            try:
                await c.close()
            except Exception:
                pass
        for d in (alice_share, bob_share, alice_dl, bob_dl):
            shutil.rmtree(d, ignore_errors=True)


# =========================================================================
# File transfer tests (separate processes with shared directories)
# =========================================================================

class TestMultiClientFileTransfer:
    """
    Verify file listing and transfer between two subprocess clients.

    Alice and Bob each share a directory with generated test files
    (a mix of text and binary data, ~1.5-2 MB each).  They request
    each other's file lists, browse them, queue downloads, and verify
    file integrity via SHA-256.
    """

    @pytest.mark.asyncio(loop_scope="module")
    async def test_bob_requests_alice_file_list(self, alice_bob_with_shares):
        """Bob can request and receive Alice's file list."""
        alice, bob, hashes, alice_dl, bob_dl = alice_bob_with_shares

        # Ensure Bob can see Alice on the hub first
        found = await bob.wait_for_nick_in_users(
            HUB_WINTERMUTE, NICK_ALICE_FT, timeout=USER_SYNC_TIMEOUT,
        )
        assert found, f"Bob never saw {NICK_ALICE_FT} in user list"

        result = await bob.request_and_browse_file_list(
            HUB_WINTERMUTE, NICK_ALICE_FT, timeout=FILE_LIST_TIMEOUT,
        )
        fl_id = result["file_list_id"]
        entries = result["entries"]

        assert fl_id, "No file list ID returned"
        assert len(entries) >= 1, "Alice's root file list is empty"

        # We expect an "AliceFiles" directory
        names = [e["name"] for e in entries]
        assert "AliceFiles" in names, (
            f"Expected 'AliceFiles' in root entries, got: {names}"
        )

        # Clean up
        await bob.close_file_list(fl_id)

    @pytest.mark.asyncio(loop_scope="module")
    async def test_alice_requests_bob_file_list(self, alice_bob_with_shares):
        """Alice can request and receive Bob's file list."""
        alice, bob, hashes, alice_dl, bob_dl = alice_bob_with_shares

        found = await alice.wait_for_nick_in_users(
            HUB_WINTERMUTE, NICK_BOB_FT, timeout=USER_SYNC_TIMEOUT,
        )
        assert found, f"Alice never saw {NICK_BOB_FT} in user list"

        result = await alice.request_and_browse_file_list(
            HUB_WINTERMUTE, NICK_BOB_FT, timeout=FILE_LIST_TIMEOUT,
        )
        fl_id = result["file_list_id"]
        entries = result["entries"]

        assert fl_id, "No file list ID returned"
        assert len(entries) >= 1, "Bob's root file list is empty"

        names = [e["name"] for e in entries]
        assert "BobFiles" in names, (
            f"Expected 'BobFiles' in root entries, got: {names}"
        )

        await alice.close_file_list(fl_id)

    @pytest.mark.asyncio(loop_scope="module")
    async def test_bob_browses_alice_share(self, alice_bob_with_shares):
        """Bob can browse Alice's shared directory and see files."""
        alice, bob, hashes, alice_dl, bob_dl = alice_bob_with_shares

        result = await bob.request_and_browse_file_list(
            HUB_WINTERMUTE, NICK_ALICE_FT, timeout=FILE_LIST_TIMEOUT,
        )
        fl_id = result["file_list_id"]

        try:
            # Browse into the AliceFiles virtual directory
            entries = await bob.browse_file_list(fl_id, "AliceFiles")
            file_names = [e["name"] for e in entries if not e["isDirectory"]]

            assert "test_document.txt" in file_names, (
                f"Expected test_document.txt in AliceFiles, got: {file_names}"
            )
            assert "test_binary.dat" in file_names, (
                f"Expected test_binary.dat in AliceFiles, got: {file_names}"
            )

            # Verify sizes are reasonable (should be ~2MB and ~1.5MB)
            for e in entries:
                if e["name"] == "test_document.txt":
                    assert e["size"] == 2 * 1024 * 1024, (
                        f"test_document.txt size mismatch: {e['size']}"
                    )
                elif e["name"] == "test_binary.dat":
                    assert e["size"] == 1536 * 1024, (
                        f"test_binary.dat size mismatch: {e['size']}"
                    )
        finally:
            await bob.close_file_list(fl_id)

    @pytest.mark.asyncio(loop_scope="module")
    async def test_bob_downloads_text_file_from_alice(self, alice_bob_with_shares):
        """Bob downloads a text file from Alice and verifies integrity."""
        alice, bob, hashes, alice_dl, bob_dl = alice_bob_with_shares

        result = await bob.request_and_browse_file_list(
            HUB_WINTERMUTE, NICK_ALICE_FT, timeout=FILE_LIST_TIMEOUT,
        )
        fl_id = result["file_list_id"]

        try:
            # Find the text file's TTH for queueing
            entries = await bob.browse_file_list(fl_id, "AliceFiles")
            text_entry = next(
                (e for e in entries if e["name"] == "test_document.txt"), None,
            )
            assert text_entry is not None, "test_document.txt not found"
            assert len(text_entry["tth"]) > 0, "TTH is empty"

            # Queue download via the file list
            ok = await bob.download_from_list(
                fl_id, "AliceFiles/test_document.txt",
                download_to=str(bob_dl) + "/",
            )
            assert ok, "download_from_list returned False"

            # Wait for download to complete (poll the filesystem)
            target_name = "test_document.txt"
            deadline = asyncio.get_event_loop().time() + DOWNLOAD_TIMEOUT
            downloaded = False
            while asyncio.get_event_loop().time() < deadline:
                dl_path = bob_dl / target_name
                if dl_path.exists() and dl_path.stat().st_size == text_entry["size"]:
                    downloaded = True
                    break
                # If the worker died, stop waiting
                if not bob.worker_alive:
                    stderr_tail = await bob.get_stderr()
                    rc = bob._proc.returncode if bob._proc else "?"
                    assert False, (
                        f"Worker died during download (returncode={rc}).\n"
                        f"stderr:\n{stderr_tail}"
                    )
                await asyncio.sleep(2)

            if not downloaded:
                assert False, (
                    f"Download of {target_name} did not complete within "
                    f"{DOWNLOAD_TIMEOUT}s"
                )

            # Verify integrity
            sha = hashlib.sha256()
            with open(dl_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha.update(chunk)
            actual_hash = sha.hexdigest()
            assert actual_hash == hashes["test_document.txt"], (
                f"SHA-256 mismatch for {target_name}: "
                f"expected {hashes['test_document.txt']}, got {actual_hash}"
            )
        finally:
            if bob.worker_alive:
                try:
                    await bob.close_file_list(fl_id)
                except Exception:
                    pass

    @pytest.mark.asyncio(loop_scope="module")
    async def test_bob_downloads_binary_file_from_alice(self, alice_bob_with_shares):
        """Bob downloads a binary file from Alice and verifies integrity."""
        alice, bob, hashes, alice_dl, bob_dl = alice_bob_with_shares

        result = await bob.request_and_browse_file_list(
            HUB_WINTERMUTE, NICK_ALICE_FT, timeout=FILE_LIST_TIMEOUT,
        )
        fl_id = result["file_list_id"]

        try:
            entries = await bob.browse_file_list(fl_id, "AliceFiles")
            bin_entry = next(
                (e for e in entries if e["name"] == "test_binary.dat"), None,
            )
            assert bin_entry is not None, "test_binary.dat not found"

            ok = await bob.download_from_list(
                fl_id, "AliceFiles/test_binary.dat",
                download_to=str(bob_dl) + "/",
            )
            assert ok, "download_from_list returned False"

            deadline = asyncio.get_event_loop().time() + DOWNLOAD_TIMEOUT
            downloaded = False
            while asyncio.get_event_loop().time() < deadline:
                dl_path = bob_dl / "test_binary.dat"
                if dl_path.exists() and dl_path.stat().st_size == bin_entry["size"]:
                    downloaded = True
                    break
                if not bob.worker_alive:
                    stderr_tail = await bob.get_stderr()
                    rc = bob._proc.returncode if bob._proc else "?"
                    assert False, (
                        f"Worker died during download (returncode={rc}).\n"
                        f"stderr:\n{stderr_tail}"
                    )
                await asyncio.sleep(2)

            if not downloaded:
                assert False, (
                    "Download of test_binary.dat did not complete within "
                    f"{DOWNLOAD_TIMEOUT}s"
                )

            sha = hashlib.sha256()
            with open(dl_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha.update(chunk)
            actual_hash = sha.hexdigest()
            assert actual_hash == hashes["test_binary.dat"], (
                f"SHA-256 mismatch for test_binary.dat: "
                f"expected {hashes['test_binary.dat']}, got {actual_hash}"
            )
        finally:
            if bob.worker_alive:
                try:
                    await bob.close_file_list(fl_id)
                except Exception:
                    pass

    @pytest.mark.asyncio(loop_scope="module")
    async def test_alice_downloads_file_from_bob(self, alice_bob_with_shares):
        """Alice downloads a binary file from Bob and verifies integrity."""
        alice, bob, hashes, alice_dl, bob_dl = alice_bob_with_shares

        result = await alice.request_and_browse_file_list(
            HUB_WINTERMUTE, NICK_BOB_FT, timeout=FILE_LIST_TIMEOUT,
        )
        fl_id = result["file_list_id"]

        try:
            entries = await alice.browse_file_list(fl_id, "BobFiles")
            bob_entry = next(
                (e for e in entries if e["name"] == "bob_payload.bin"), None,
            )
            assert bob_entry is not None, "bob_payload.bin not found"

            ok = await alice.download_from_list(
                fl_id, "BobFiles/bob_payload.bin",
                download_to=str(alice_dl) + "/",
            )
            assert ok, "download_from_list returned False"

            deadline = asyncio.get_event_loop().time() + DOWNLOAD_TIMEOUT
            downloaded = False
            while asyncio.get_event_loop().time() < deadline:
                dl_path = alice_dl / "bob_payload.bin"
                if dl_path.exists() and dl_path.stat().st_size == bob_entry["size"]:
                    downloaded = True
                    break
                if not alice.worker_alive:
                    stderr_tail = await alice.get_stderr()
                    rc = alice._proc.returncode if alice._proc else "?"
                    assert False, (
                        f"Worker died during download (returncode={rc}).\n"
                        f"stderr:\n{stderr_tail}"
                    )
                await asyncio.sleep(2)

            if not downloaded:
                assert False, (
                    "Download of bob_payload.bin did not complete within "
                    f"{DOWNLOAD_TIMEOUT}s"
                )

            sha = hashlib.sha256()
            with open(dl_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha.update(chunk)
            actual_hash = sha.hexdigest()
            assert actual_hash == hashes["bob_payload.bin"], (
                f"SHA-256 mismatch for bob_payload.bin: "
                f"expected {hashes['bob_payload.bin']}, got {actual_hash}"
            )
        finally:
            if alice.worker_alive:
                try:
                    await alice.close_file_list(fl_id)
                except Exception:
                    pass
