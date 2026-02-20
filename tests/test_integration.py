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
import hashlib
import json
import logging
import os
import random
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
HUBS = [HUB_WINTERMUTE]

# Unique nicks so parallel CI runs never collide
_RUN_ID = uuid.uuid4().hex[:6]
NICK = f"IntBot_{_RUN_ID}"
NICK_ALICE = f"IntBot_A_{_RUN_ID}"
NICK_BOB = f"IntBot_B_{_RUN_ID}"
NICK_ALICE_FT = f"IntBot_AF_{_RUN_ID}"
NICK_BOB_FT = f"IntBot_BF_{_RUN_ID}"

# Time budget (seconds)
INIT_TIMEOUT = 60
CONNECT_TIMEOUT = 45
USER_SYNC_TIMEOUT = 60
PM_TIMEOUT = 30
SEARCH_TIMEOUT = 30
FILE_LIST_TIMEOUT = 90
DOWNLOAD_TIMEOUT = 120
SHARE_REFRESH_WAIT = 30

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

    async def search(self, query: str, hub_url: str = "", timeout: float = SEARCH_TIMEOUT) -> list:
        return await self._send("search", {"query": query, "hub_url": hub_url, "timeout": timeout, "min_results": 0}, timeout=timeout + 10)

    async def add_share(self, real_path: str, virtual_name: str) -> bool:
        return await self._send("add_share", {"real_path": real_path, "virtual_name": virtual_name})

    async def start_networking(self) -> None:
        await self._send("start_networking")

    async def refresh_share(self) -> None:
        await self._send("refresh_share")

    async def get_share_size(self) -> int:
        return await self._send("get_share_size")

    async def resume_hashing(self) -> None:
        await self._send("resume_hashing")

    async def get_hash_status(self) -> dict:
        return await self._send("get_hash_status")

    # -- File list methods -------------------------------------------------

    async def request_file_list(self, hub_url: str, nick: str) -> bool:
        return await self._send("request_file_list", {"hub_url": hub_url, "nick": nick})

    async def request_and_browse_file_list(
        self, hub_url: str, nick: str, timeout: float = 60,
    ) -> dict:
        return await self._send(
            "request_and_browse_file_list",
            {"hub_url": hub_url, "nick": nick, "timeout": timeout},
            timeout=timeout + 15,
        )

    async def list_local_file_lists(self) -> list:
        return await self._send("list_local_file_lists")

    async def open_file_list(self, file_list_id: str) -> bool:
        return await self._send("open_file_list", {"file_list_id": file_list_id})

    async def browse_file_list(self, file_list_id: str, directory: str = "/") -> list:
        return await self._send("browse_file_list", {"file_list_id": file_list_id, "directory": directory})

    async def download_from_list(
        self, file_list_id: str, file_path: str, download_to: str = "",
    ) -> bool:
        return await self._send(
            "download_from_list",
            {"file_list_id": file_list_id, "file_path": file_path, "download_to": download_to},
        )

    async def download_and_wait(
        self, directory: str, name: str, size: int, tth: str, timeout: float = 120,
    ) -> dict:
        return await self._send(
            "download_and_wait",
            {"directory": directory, "name": name, "size": size, "tth": tth, "timeout": timeout},
            timeout=timeout + 15,
        )

    async def list_queue(self) -> list:
        return await self._send("list_queue")

    async def clear_queue(self) -> None:
        await self._send("clear_queue")

    async def close_file_list(self, file_list_id: str) -> None:
        await self._send("close_file_list", {"file_list_id": file_list_id})

    async def close_all_file_lists(self) -> None:
        await self._send("close_all_file_lists")

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


def _generate_test_file(path: Path, size: int, *, binary: bool = False) -> str:
    """
    Generate a deterministic test file and return its SHA-256 hex digest.

    Uses a seeded PRNG so the content is reproducible but non-trivial.
    """
    rng = random.Random(42)
    sha = hashlib.sha256()
    with open(path, "wb") as f:
        remaining = size
        while remaining > 0:
            chunk_size = min(remaining, 8192)
            if binary:
                chunk = bytes(rng.getrandbits(8) for _ in range(chunk_size))
            else:
                # Printable ASCII text with line breaks
                chars = []
                for _ in range(chunk_size):
                    if rng.random() < 0.05:
                        chars.append(ord("\n"))
                    else:
                        chars.append(rng.randint(32, 126))
                chunk = bytes(chars)
            f.write(chunk)
            sha.update(chunk)
            remaining -= chunk_size
    return sha.hexdigest()


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

        # Configure active mode with unique ports so clients can
        # establish direct connections for file list / file transfers.
        # Both run on the same host so they need different TCP/UDP/TLS
        # ports and must advertise 127.0.0.1.
        for client_obj, tcp_port in [(alice, "4200"), (bob, "4210")]:
            await client_obj.set_setting("IncomingConnections", "0")  # Active/Direct
            await client_obj.set_setting("InPort", tcp_port)           # TCP
            await client_obj.set_setting("UDPPort", tcp_port)          # UDP
            await client_obj.set_setting("TLSPort", str(int(tcp_port) + 1))  # TLS
            await client_obj.set_setting("ExternalIp", "127.0.0.1")
            await client_obj.set_setting("NoIpOverride", "1")
            await client_obj.set_setting("AutoDetectIncomingConnection", "0")
            await client_obj.set_setting("Slots", "3")

        # Apply the connection settings (opens TCP/UDP listeners)
        await alice.start_networking()
        await bob.start_networking()

        # Share directories
        assert await alice.add_share(str(alice_share) + "/", "AliceFiles")
        assert await bob.add_share(str(bob_share) + "/", "BobFiles")

        # Refresh to discover files & queue them for hashing.
        # NOTE: refresh() is non-blocking — it builds the directory tree but
        # only includes files whose TTH hash is already known.  New files are
        # queued for hashing in the background.
        await alice.refresh_share()
        await bob.refresh_share()

        # The hasher thread starts paused.  The TimerManager callback will
        # unpause it once HashingStartDelay elapses (we set it to 0 above)
        # AND ShareManager::isRefreshing() returns false.  To be safe,
        # sleep briefly for the refresh thread to finish, then explicitly
        # resume hashing so we don't depend on timer timing.
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
            # User list may not be populated immediately after connect;
            # poll until we see at least ourselves.
            for _ in range(30):
                refreshed = [
                    h for h in client.list_hubs() if h.url == hub_info.url
                ]
                if refreshed and refreshed[0].userCount >= 1:
                    break
                await asyncio.sleep(1)
            final = [h for h in client.list_hubs() if h.url == hub_info.url]
            assert final and final[0].userCount >= 1, (
                f"{hub_info.url}: userCount still 0 after 30s"
            )

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
            # Poll until userCount >= 2 (both clients may still be registering)
            deadline = asyncio.get_event_loop().time() + USER_SYNC_TIMEOUT
            user_count = 0
            while asyncio.get_event_loop().time() < deadline:
                hubs = await c.list_hubs()
                assert len(hubs) >= 1, f"{label}: no hubs"
                h = hubs[0]
                assert h["connected"], f"{label}: not connected"
                assert len(h["name"]) > 0, f"{label}: empty hub name"
                user_count = h["userCount"]
                if user_count >= 2:
                    break
                await asyncio.sleep(1)
            assert user_count >= 2, (
                f"{label}: {user_count} users, expected >=2"
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
            await bob.close_file_list(fl_id)

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
            await bob.close_file_list(fl_id)

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
            await alice.close_file_list(fl_id)
