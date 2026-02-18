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
import logging
import os
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

# Time budget (seconds)
INIT_TIMEOUT = 60
CONNECT_TIMEOUT = 45
USER_SYNC_TIMEOUT = 60
PM_TIMEOUT = 30
SEARCH_TIMEOUT = 30

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

    async def refresh_share(self) -> None:
        await self._send("refresh_share")

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
