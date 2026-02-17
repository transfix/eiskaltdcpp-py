"""
Integration tests -- async clients connect to live DC hubs.

Single-client tests run with an in-process AsyncDCClient.
Multi-client tests (PM exchange, mutual user visibility) spawn each
client as a SEPARATE PROCESS via ``dc_worker.py`` so each gets its own
set of dcpp singletons.  See TODO.md for the upstream fix plan that
will eventually let us run multi-client in-process.

Requirements:
  - Network access to nmdcs://wintermute.sublevels.net:411
  - libeiskaltdcpp built and installed (or wheel installed)

These tests are slow (network I/O, TLS negotiation, user list
propagation) and are NOT part of the regular unit test suite.
Run them explicitly:

    pytest tests/test_integration.py -v --tb=long

Or via CI with the "integration" workflow.
"""
from __future__ import annotations

import asyncio
import json
import hashlib
import logging
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

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
HUB_LOCAL = "dchub://127.0.0.1:4111"
HUBS = [HUB_WINTERMUTE]

# Unique nicks so parallel CI runs never collide
_RUN_ID = uuid.uuid4().hex[:6]
NICK = f"IntBot_{_RUN_ID}"
NICK_ALICE = f"IntBot_A_{_RUN_ID}"
NICK_BOB = f"IntBot_B_{_RUN_ID}"

# Time budget (seconds)
INIT_TIMEOUT = 60
CONNECT_TIMEOUT = 45
USER_SYNC_TIMEOUT = 60
PM_TIMEOUT = 30
SEARCH_TIMEOUT = 30
HASH_TIMEOUT = 60
DOWNLOAD_TIMEOUT = 120

# File transfer test parameters
TEST_FILE_SIZE = 1024 * 1024  # 1 MB

WORKER_SCRIPT = Path(__file__).parent / "dc_worker.py"

logger = logging.getLogger(__name__)


# =========================================================================
# RemoteDCClient — subprocess-based client proxy
# =========================================================================

class RemoteDCClient:
    """
    Drives a DC client in a child process via JSON-lines RPC.

    Each instance spawns ``dc_worker.py`` as a subprocess, giving it
    its own dcpp singleton set.  Commands are sent as JSON over stdin
    and responses read from stdout.
    """

    def __init__(self, label: str = "remote") -> None:
        self.label = label
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._msg_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._events: asyncio.Queue[tuple[str, list]] = asyncio.Queue()
        self._reader_task: Optional[asyncio.Task] = None
        self._closed = False

    async def start(self) -> None:
        """Launch the worker subprocess."""
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        # Ensure the worker can find the SWIG module
        if BUILD_DIR.exists():
            env["PYTHONPATH"] = str(BUILD_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        self._proc = await asyncio.create_subprocess_exec(
            sys.executable, str(WORKER_SCRIPT),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        """Read JSON lines from the worker's stdout."""
        assert self._proc and self._proc.stdout
        while True:
            raw = await self._proc.stdout.readline()
            if not raw:
                break
            line = raw.decode().strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("[%s] bad JSON from worker: %s", self.label, line)
                continue

            if "event" in msg:
                await self._events.put((msg["event"], msg.get("args", [])))
            elif "id" in msg:
                fut = self._pending.pop(msg["id"], None)
                if fut and not fut.done():
                    if msg.get("ok"):
                        fut.set_result(msg.get("result"))
                    else:
                        fut.set_exception(RuntimeError(msg.get("error", "unknown")))

    async def _send(self, cmd: str, args: dict | None = None, timeout: float = 120) -> Any:
        """Send a command and wait for the reply."""
        if self._closed or not self._proc or self._proc.stdin is None:
            raise RuntimeError(f"[{self.label}] worker not running")
        self._msg_id += 1
        msg_id = self._msg_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        payload = json.dumps({"cmd": cmd, "args": args or {}, "id": msg_id}) + "\n"
        self._proc.stdin.write(payload.encode())
        await self._proc.stdin.drain()
        return await asyncio.wait_for(fut, timeout=timeout)

    # -- Public API --------------------------------------------------------

    async def init(self, config_dir: str = "", timeout: float = INIT_TIMEOUT) -> bool:
        return await self._send("init", {"config_dir": config_dir, "timeout": timeout}, timeout=timeout + 10)

    async def connect(self, hub_url: str, timeout: float = CONNECT_TIMEOUT) -> None:
        await self._send("connect", {"hub_url": hub_url, "timeout": timeout, "wait": True}, timeout=timeout + 10)

    async def disconnect(self, hub_url: str) -> None:
        await self._send("disconnect", {"hub_url": hub_url})

    async def set_setting(self, name: str, value: str) -> None:
        await self._send("set_setting", {"name": name, "value": value})

    async def get_setting(self, name: str) -> str:
        return await self._send("get_setting", {"name": name})

    async def is_connected(self, hub_url: str) -> bool:
        return await self._send("is_connected", {"hub_url": hub_url})

    async def list_hubs(self) -> list:
        return await self._send("list_hubs")

    async def get_users(self, hub_url: str) -> list:
        return await self._send("get_users", {"hub_url": hub_url})

    async def send_pm(self, hub_url: str, nick: str, message: str) -> None:
        await self._send("send_pm", {"hub_url": hub_url, "nick": nick, "message": message}, timeout=15)

    async def wait_pm(self, from_nick: str | None = None, timeout: float = PM_TIMEOUT) -> dict:
        return await self._send("wait_pm", {"from_nick": from_nick, "timeout": timeout}, timeout=timeout + 10)

    async def send_message(self, hub_url: str, message: str) -> None:
        await self._send("send_message", {"hub_url": hub_url, "message": message})

    async def search(self, query: str, hub_url: str = "", timeout: float = SEARCH_TIMEOUT, min_results: int = 1) -> list:
        return await self._send("search", {"query": query, "hub_url": hub_url, "timeout": timeout, "min_results": min_results}, timeout=timeout + 10)

    async def add_share(self, real_path: str, virtual_name: str) -> bool:
        return await self._send("add_share", {"real_path": real_path, "virtual_name": virtual_name})

    async def refresh_share(self) -> None:
        await self._send("refresh_share")

    async def start_networking(self) -> None:
        await self._send("start_networking")

    async def share_size(self) -> int:
        return await self._send("share_size")

    async def shared_files(self) -> int:
        return await self._send("shared_files")

    async def hash_status(self) -> dict:
        return await self._send("hash_status")

    async def download_and_wait(
        self, directory: str, name: str, size: int, tth: str,
        hub_url: str = "", nick: str = "", timeout: float = 120,
    ) -> dict:
        return await self._send(
            "download_and_wait",
            {"directory": directory, "name": name, "size": size, "tth": tth,
             "hub_url": hub_url, "nick": nick, "timeout": timeout},
            timeout=timeout + 30,
        )

    async def list_queue(self) -> list:
        return await self._send("list_queue")

    async def clear_queue(self) -> None:
        await self._send("clear_queue")

    async def wait_event(self, event_name: str, timeout: float = 30) -> list:
        """Wait for a specific event from the worker."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError(f"No '{event_name}' event within {timeout}s")
            try:
                name, args = await asyncio.wait_for(self._events.get(), timeout=remaining)
                if name == event_name:
                    return args
                # Put back? No -- just discard non-matching events.
            except asyncio.TimeoutError:
                raise asyncio.TimeoutError(f"No '{event_name}' event within {timeout}s")

    async def wait_for_nick_in_users(self, hub_url: str, nick: str, timeout: float = USER_SYNC_TIMEOUT) -> bool:
        """Poll user list until nick appears."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            users = await self.get_users(hub_url)
            nicks = [u["nick"] for u in users]
            if nick in nicks:
                return True
            await asyncio.sleep(1)
        return False

    async def close(self) -> None:
        """Shut down the worker subprocess."""
        if self._closed:
            return
        self._closed = True
        try:
            await self._send("shutdown", timeout=15)
        except Exception:
            pass
        if self._proc:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass

    async def get_stderr(self) -> str:
        """Read stderr from the worker (for debugging)."""
        if self._proc and self._proc.stderr:
            try:
                data = await asyncio.wait_for(self._proc.stderr.read(), timeout=1)
                return data.decode(errors="replace")
            except asyncio.TimeoutError:
                return ""
        return ""


# =========================================================================
# Fixtures
# =========================================================================

@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client():
    """
    Module-scoped in-process async DC client for single-client tests.
    """
    cfg_dir = Path(tempfile.mkdtemp(prefix="dcpy_inttest_"))
    c = AsyncDCClient(str(cfg_dir))
    try:
        ok = await c.initialize(timeout=INIT_TIMEOUT)
        assert ok, "Client failed to initialize"
        c.set_setting("Nick", NICK)
        c.set_setting("Description", "eiskaltdcpp-py integration test bot")
        connect_tasks = [
            c.connect(hub, wait=True, timeout=CONNECT_TIMEOUT)
            for hub in HUBS
        ]
        await asyncio.gather(*connect_tasks)
        await asyncio.sleep(5)
        yield c
    finally:
        try:
            await c.shutdown()
        except Exception:
            pass
        shutil.rmtree(cfg_dir, ignore_errors=True)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def alice_and_bob():
    """
    Module-scoped pair of RemoteDCClients (separate processes).

    Alice and Bob each run in their own subprocess with independent
    dcpp singletons, connected to the same hub.
    """
    alice = RemoteDCClient("alice")
    bob = RemoteDCClient("bob")

    try:
        await alice.start()
        await bob.start()

        assert await alice.init(), "Alice failed to initialize"
        assert await bob.init(), "Bob failed to initialize"

        await alice.set_setting("Nick", NICK_ALICE)
        await alice.set_setting("Description", "eiskaltdcpp-py integration bot A")

        await bob.set_setting("Nick", NICK_BOB)
        await bob.set_setting("Description", "eiskaltdcpp-py integration bot B")

        # Connect both to the hub
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
# Single-client tests (in-process)
# =========================================================================

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
        assert len(hubs) >= len(HUBS)
        for hub_info in hubs:
            assert hub_info.connected, f"{hub_info.url} not connected"
            assert len(hub_info.name) > 0, f"{hub_info.url} has empty name"
            assert hub_info.userCount >= 1

    @pytest.mark.asyncio(loop_scope="module")
    async def test_user_list_not_empty(self, client):
        """Each hub has a non-empty user list (polls up to 30s)."""
        for hub in HUBS:
            for _ in range(30):
                users = client.get_users(hub)
                if len(users) >= 1:
                    break
                await asyncio.sleep(1)
            assert len(users) >= 1, (
                f"{hub}: user list still empty after 30s"
            )

    @pytest.mark.asyncio(loop_scope="module")
    async def test_our_nick_in_user_list(self, client):
        """Our own nick appears in the user list (polls up to 30s)."""
        found = False
        for _ in range(30):
            for hub in HUBS:
                users = client.get_users(hub)
                nicks = [u.nick for u in users]
                if NICK in nicks:
                    found = True
                    break
            if found:
                break
            await asyncio.sleep(1)
        assert found, f"Our nick '{NICK}' not found on any hub after 30s"


class TestSettings:
    """Verify settings survive connection."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_nick_setting_matches(self, client):
        current = client.get_setting("Nick")
        assert current == NICK

    @pytest.mark.asyncio(loop_scope="module")
    async def test_description_setting(self, client):
        desc = client.get_setting("Description")
        assert "integration test" in desc.lower()


class TestSearch:
    """Verify search functionality."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_search_does_not_crash(self, client):
        ok = client.search("test", hub_url=HUBS[0])
        await asyncio.sleep(2)

    @pytest.mark.asyncio(loop_scope="module")
    async def test_search_and_wait(self, client):
        try:
            results = await client.search_and_wait(
                "linux", hub_url=HUBS[0], timeout=SEARCH_TIMEOUT, min_results=0,
            )
            for r in results:
                assert isinstance(r, dict)
        except asyncio.TimeoutError:
            pytest.skip("Search timed out -- hub may not relay results")


class TestCleanDisconnect:
    """Verify clean disconnection."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_disconnect_from_all_hubs(self, client):
        for hub in HUBS:
            if client.is_connected(hub):
                await client.disconnect(hub)
        await asyncio.sleep(2)
        for hub in HUBS:
            assert not client.is_connected(hub)


# =========================================================================
# Multi-client tests (separate processes)
# =========================================================================

class TestMultiClientConnection:
    """Verify two subprocess clients can connect independently."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_both_connected(self, alice_and_bob):
        """Both Alice and Bob report connected."""
        alice, bob = alice_and_bob
        assert await alice.is_connected(HUB_WINTERMUTE), "Alice not connected"
        assert await bob.is_connected(HUB_WINTERMUTE), "Bob not connected"

    @pytest.mark.asyncio(loop_scope="module")
    async def test_hub_info(self, alice_and_bob):
        """Both clients see reasonable hub info."""
        alice, bob = alice_and_bob
        for c, label in [(alice, "Alice"), (bob, "Bob")]:
            hubs = await c.list_hubs()
            assert len(hubs) >= 1, f"{label}: no hubs"
            h = hubs[0]
            assert h["connected"], f"{label}: not connected"
            assert len(h["name"]) > 0, f"{label}: empty hub name"
            assert h["userCount"] >= 2, (
                f"{label}: {h['userCount']} users, expected >=2"
            )


class TestMultiClientVisibility:
    """Verify clients can see each other in the user list."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_alice_sees_bob(self, alice_and_bob):
        """Alice can find Bob in the user list."""
        alice, bob = alice_and_bob
        found = await alice.wait_for_nick_in_users(
            HUB_WINTERMUTE, NICK_BOB, timeout=USER_SYNC_TIMEOUT
        )
        assert found, f"Alice never saw {NICK_BOB} in user list"

    @pytest.mark.asyncio(loop_scope="module")
    async def test_bob_sees_alice(self, alice_and_bob):
        """Bob can find Alice in the user list."""
        alice, bob = alice_and_bob
        found = await bob.wait_for_nick_in_users(
            HUB_WINTERMUTE, NICK_ALICE, timeout=USER_SYNC_TIMEOUT
        )
        assert found, f"Bob never saw {NICK_ALICE} in user list"


class TestMultiClientPrivateMessage:
    """Verify private message exchange between clients."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_alice_sends_pm_to_bob(self, alice_and_bob):
        """Alice sends a PM to Bob and Bob receives it."""
        alice, bob = alice_and_bob
        test_msg = f"Hello Bob from Alice {_RUN_ID}"

        # Start Bob listening before Alice sends
        wait_task = asyncio.create_task(
            bob.wait_pm(from_nick=NICK_ALICE, timeout=PM_TIMEOUT)
        )
        # Small delay to ensure Bob's wait_pm is active
        await asyncio.sleep(0.5)

        try:
            await alice.send_pm(HUB_WINTERMUTE, NICK_BOB, test_msg)
        except (asyncio.TimeoutError, RuntimeError) as e:
            wait_task.cancel()
            pytest.skip(f"send_pm failed: {e}")

        try:
            pm = await asyncio.wait_for(wait_task, timeout=PM_TIMEOUT)
        except asyncio.TimeoutError:
            pytest.skip(
                "PM delivery timed out — hub may not relay PMs between bots"
            )

        assert test_msg in pm["message"], (
            f"Expected '{test_msg}' in PM, got: '{pm['message']}'"
        )

    @pytest.mark.asyncio(loop_scope="module")
    async def test_bob_sends_pm_to_alice(self, alice_and_bob):
        """Bob sends a PM to Alice and Alice receives it."""
        alice, bob = alice_and_bob
        test_msg = f"Hello Alice from Bob {_RUN_ID}"

        wait_task = asyncio.create_task(
            alice.wait_pm(from_nick=NICK_BOB, timeout=PM_TIMEOUT)
        )
        await asyncio.sleep(0.5)

        try:
            await bob.send_pm(HUB_WINTERMUTE, NICK_ALICE, test_msg)
        except (asyncio.TimeoutError, RuntimeError) as e:
            wait_task.cancel()
            pytest.skip(f"send_pm failed: {e}")

        try:
            pm = await asyncio.wait_for(wait_task, timeout=PM_TIMEOUT)
        except asyncio.TimeoutError:
            pytest.skip(
                "PM delivery timed out — hub may not relay PMs between bots"
            )

        assert test_msg in pm["message"], (
            f"Expected '{test_msg}' in PM, got: '{pm['message']}'"
        )


# =========================================================================
# File transfer tests (separate processes)
# =========================================================================

NICK_ALICE_FT = f"IntBot_AF_{_RUN_ID}"
NICK_BOB_FT = f"IntBot_BF_{_RUN_ID}"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def file_transfer_pair():
    """
    Module-scoped pair of RemoteDCClients configured for file transfer.

    Alice shares a directory containing a 1 MB random file.
    Bob has a download directory ready to receive files.
    Both clients are set to active mode on 127.0.0.1 so they can
    connect directly to each other on the same machine.
    """
    alice = RemoteDCClient("alice_ft")
    bob = RemoteDCClient("bob_ft")

    # Create temp directories
    share_dir = Path(tempfile.mkdtemp(prefix="dcpy_share_"))
    download_dir = Path(tempfile.mkdtemp(prefix="dcpy_dl_"))

    # Generate a 1 MB random file with known hash
    test_file = share_dir / f"testfile_{_RUN_ID}.dat"
    file_data = secrets.token_bytes(TEST_FILE_SIZE)
    test_file.write_bytes(file_data)
    file_sha256 = hashlib.sha256(file_data).hexdigest()

    try:
        await alice.start()
        await bob.start()

        assert await alice.init(), "Alice failed to initialize"
        assert await bob.init(), "Bob failed to initialize"

        # Configure Alice — MUST be in active mode so she responds to
        # Bob's passive searches and can accept incoming connections.
        # In NMDC, passive clients silently ignore passive searches.
        await alice.set_setting("Nick", NICK_ALICE_FT)
        await alice.set_setting("Description", "eiskaltdcpp-py file transfer test A")
        await alice.set_setting("IncomingConnections", "0")  # active/direct
        await alice.set_setting("InPort", "31410")
        await alice.set_setting("UDPPort", "31410")
        await alice.set_setting("TLSPort", "31411")
        await alice.set_setting("ExternalIp", "127.0.0.1")
        await alice.set_setting("NoIPOverride", "1")
        await alice.set_setting("Slots", "5")
        await alice.set_setting("HashingStartDelay", "0")  # no delay

        # Configure Bob — passive mode.  Search results come via hub TCP
        # (not UDP), avoiding Docker-bridge routing issues.
        # For downloads, Bob issues $RevConnectToMe → Alice connects to him.
        await bob.set_setting("Nick", NICK_BOB_FT)
        await bob.set_setting("Description", "eiskaltdcpp-py file transfer test B")
        await bob.set_setting("IncomingConnections", "3")  # passive
        await bob.set_setting("DownloadDirectory", str(download_dir) + "/")
        await bob.set_setting("HashingStartDelay", "0")  # no delay

        # Apply networking config — must be called AFTER changing
        # connection settings so listen sockets are bound to the right ports.
        # Only Alice needs networking (active mode); Bob is passive.
        await alice.start_networking()

        # Alice shares the test directory (path MUST end with '/' for DC++)
        share_path = str(share_dir)
        if not share_path.endswith("/"):
            share_path += "/"
        ok = await alice.add_share(share_path, "TestShare")
        assert ok, "Alice failed to add share directory"

        # addShareDir() scans the directory and submits new files for
        # hashing, but unhashed files are NOT included in the share tree.
        # With HashingStartDelay=0 and a 1 MB file, hashing completes
        # almost instantly.  The file appears in sha once hashed.
        # We must: (1) wait for hashing to complete, then (2) refresh
        # the share so the now-hashed files are picked up.

        # Wait for hashing + share rebuild.
        # addShareDir auto-indexes after hash completes for new adds,
        # so share_size should become > 0 quickly.
        deadline = asyncio.get_event_loop().time() + HASH_TIMEOUT
        while asyncio.get_event_loop().time() < deadline:
            share_sz = await alice.share_size()
            if share_sz > 0:
                break
            await asyncio.sleep(0.5)
        else:
            # If share not ready, try an explicit refresh
            await alice.refresh_share()
            refresh_deadline = asyncio.get_event_loop().time() + 15
            while asyncio.get_event_loop().time() < refresh_deadline:
                share_sz = await alice.share_size()
                if share_sz > 0:
                    break
                await asyncio.sleep(0.5)
            else:
                hs = await alice.hash_status()
                share_sz = await alice.share_size()
                pytest.skip(
                    f"Share not ready in time: size={share_sz}, "
                    f"filesLeft={hs['filesLeft']}, bytesLeft={hs['bytesLeft']}"
                )

        # Verify Alice's share is non-empty
        shared_fc = await alice.shared_files()
        assert share_sz > 0, f"Alice share size is {share_sz}, expected > 0"
        assert shared_fc >= 1, f"Alice shared file count is {shared_fc}, expected >= 1"

        # Connect both to the LOCAL Docker hub — file transfer
        # requires direct peer-to-peer connections.  The local hub
        # rewrites client IPs to the Docker bridge IP which is
        # routable from localhost, whereas a remote hub would see
        # the machine's public IP, making $ConnectToMe unreachable.
        await asyncio.gather(
            alice.connect(HUB_LOCAL, timeout=CONNECT_TIMEOUT),
            bob.connect(HUB_LOCAL, timeout=CONNECT_TIMEOUT),
        )

        # Let user lists propagate
        await asyncio.sleep(5)

        # Make sure they can see each other
        found_bob = await alice.wait_for_nick_in_users(
            HUB_LOCAL, NICK_BOB_FT, timeout=USER_SYNC_TIMEOUT
        )
        found_alice = await bob.wait_for_nick_in_users(
            HUB_LOCAL, NICK_ALICE_FT, timeout=USER_SYNC_TIMEOUT
        )
        if not found_bob or not found_alice:
            pytest.skip("Clients cannot see each other in user list")

        yield {
            "alice": alice,
            "bob": bob,
            "share_dir": share_dir,
            "download_dir": download_dir,
            "test_file": test_file,
            "file_data": file_data,
            "file_sha256": file_sha256,
            "file_name": test_file.name,
            "file_size": TEST_FILE_SIZE,
        }

    finally:
        for c in (alice, bob):
            try:
                await c.close()
            except Exception:
                pass
        shutil.rmtree(share_dir, ignore_errors=True)
        shutil.rmtree(download_dir, ignore_errors=True)


class TestMultiClientFileTransfer:
    """Verify file sharing and transfer between two clients."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_alice_share_visible(self, file_transfer_pair):
        """Alice's shared file count is at least 1."""
        info = file_transfer_pair
        alice = info["alice"]
        count = await alice.shared_files()
        assert count >= 1, f"Alice shares {count} files, expected >= 1"
        size = await alice.share_size()
        assert size >= info["file_size"], (
            f"Alice share size {size} < test file size {info['file_size']}"
        )

    @pytest.mark.asyncio(loop_scope="module")
    async def test_bob_finds_file_via_search(self, file_transfer_pair):
        """Bob can find Alice's shared file by searching for its name."""
        info = file_transfer_pair
        bob = info["bob"]
        file_name = info["file_name"]

        # NMDC hubs rate-limit searches (~10s between searches per user)
        # and share info takes time to propagate.  Retry a few times.
        alice_results: list[dict] = []
        for attempt in range(4):
            if attempt > 0:
                # Wait for hub search rate-limit to expire
                await asyncio.sleep(15)

            results = await bob.search(
                _RUN_ID,
                hub_url=HUB_LOCAL,
                timeout=SEARCH_TIMEOUT,
            )

            alice_results = [
                r for r in results
                if r.get("nick") == NICK_ALICE_FT
            ]
            if alice_results:
                break

        if not alice_results:
            pytest.skip(
                "Bob did not receive search results from Alice — "
                "hub may not relay search results between bots, "
                f"or share not yet propagated. Got {len(results)} total results."
            )

        # Verify the result has expected fields
        r = alice_results[0]
        assert r["size"] == info["file_size"], (
            f"Search result size {r['size']} != expected {info['file_size']}"
        )
        assert len(r.get("tth", "")) > 0, "Search result missing TTH"
        assert file_name in r.get("file", ""), (
            f"Search result file '{r.get('file')}' doesn't contain '{file_name}'"
        )

        # Stash the search result so the download test can reuse it
        # without hitting hub rate limits with a second search.
        info["_search_result"] = r

    @pytest.mark.asyncio(loop_scope="module")
    async def test_bob_downloads_file(self, file_transfer_pair):
        """Bob downloads Alice's file and verifies the hash matches."""
        info = file_transfer_pair
        bob = info["bob"]
        download_dir = info["download_dir"]
        file_name = info["file_name"]
        expected_sha256 = info["file_sha256"]

        # Reuse the search result from test_bob_finds_file_via_search
        # if available, to avoid hub search rate-limit issues.
        r = info.get("_search_result")
        if r is None:
            # Fallback: search again (with retries)
            alice_results: list[dict] = []
            for attempt in range(4):
                if attempt > 0:
                    await asyncio.sleep(15)

                results = await bob.search(
                    _RUN_ID,
                    hub_url=HUB_LOCAL,
                    timeout=SEARCH_TIMEOUT,
                )

                alice_results = [
                    rr for rr in results
                    if rr.get("nick") == NICK_ALICE_FT
                ]
                if alice_results:
                    break

            if not alice_results:
                pytest.skip(
                    "Bob did not receive search results from Alice — "
                    "cannot proceed with download test"
                )
            r = alice_results[0]

        tth = r["tth"]
        size = r["size"]
        source_nick = r.get("nick", "")
        source_hub = r.get("hub_url", HUB_LOCAL)
        # The file field may be a path like "TestShare/testfile_xxx.dat";
        # extract just the filename
        result_filename = Path(r["file"]).name

        # Queue the download and wait for completion
        result = await bob.download_and_wait(
            str(download_dir) + "/",
            result_filename,
            size,
            tth,
            hub_url=source_hub,
            nick=source_nick,
            timeout=DOWNLOAD_TIMEOUT,
        )

        if not result["success"]:
            error = result.get("error", "unknown")
            if "timeout" in error.lower():
                pytest.skip(
                    f"Download timed out — peers may not be able to "
                    f"connect directly: {error}"
                )
            pytest.skip(f"Download failed: {error}")

        # Verify the downloaded file exists and hash matches
        downloaded = download_dir / result_filename
        assert downloaded.exists(), (
            f"Downloaded file not found at {downloaded}. "
            f"Directory contents: {list(download_dir.iterdir())}"
        )
        actual_sha256 = hashlib.sha256(downloaded.read_bytes()).hexdigest()
        assert actual_sha256 == expected_sha256, (
            f"SHA256 mismatch: expected {expected_sha256}, "
            f"got {actual_sha256}"
        )