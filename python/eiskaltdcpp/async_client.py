"""
Async wrapper for the eiskaltdcpp DC client core.

Bridges the C++ threaded callback model to Python's asyncio event loop,
allowing non-blocking hub operations in async/await code.

Usage:
    import asyncio
    from eiskaltdcpp import AsyncDCClient

    async def main():
        async with AsyncDCClient('/tmp/dc-config') as client:
            await client.connect('nmdcs://hub.example.com:411')
            await client.wait_connected('nmdcs://hub.example.com:411')
            users = client.get_users('nmdcs://hub.example.com:411')
            print(f'{len(users)} users online')

    asyncio.run(main())
"""
from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from eiskaltdcpp import dc_core
from eiskaltdcpp.dc_client import EVENT_TYPES, DCClient

logger = logging.getLogger(__name__)


class AsyncDCClient:
    """
    Async wrapper around DCClient.

    Bridges the C++ threaded callback model (SWIG directors) to asyncio.
    All C++ callbacks are dispatched to the asyncio event loop via
    ``loop.call_soon_threadsafe``, ensuring handlers run in the event
    loop's thread without blocking.

    The underlying C++ library manages its own threads for network I/O,
    timers, and hashing. This wrapper does NOT run those in an executor —
    they already release the GIL via SWIG's ``%thread`` directive.

    Args:
        config_dir: Configuration directory for DC++ settings.
        loop: Event loop to dispatch callbacks to. Defaults to the
              running loop at initialization time.
    """

    def __init__(
        self,
        config_dir: str | Path = "",
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        self._sync_client = DCClient(config_dir)
        self._loop = loop
        self._handlers: dict[str, list[Callable[..., Any]]] = {
            ev: [] for ev in EVENT_TYPES
        }
        self._lock = threading.Lock()

        # Async events for waiting on state changes
        # hub_url → asyncio.Event
        self._connect_events: dict[str, asyncio.Event] = {}
        self._disconnect_events: dict[str, asyncio.Event] = {}

        # Async queues for streaming events
        self._event_queues: list[asyncio.Queue] = []

        # Private message queue for await-style consumption
        self._pm_queue: asyncio.Queue[tuple[str, str, str, str]] = asyncio.Queue()

        # Search result queue
        self._search_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        # Download complete / failed events
        self._download_events: dict[str, asyncio.Event] = {}
        self._download_results: dict[str, tuple[bool, str]] = {}

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """Get the event loop, falling back to the running loop."""
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        return self._loop

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> bool:
        """Initialize the DC core. Must be called before other operations."""
        loop = self._ensure_loop()

        # Wire up the internal sync client's callbacks to our async dispatch
        self._wire_callbacks()

        # initialize() does I/O (disk) so run in executor
        ok = await loop.run_in_executor(
            None, self._sync_client.initialize
        )
        return ok

    async def shutdown(self) -> None:
        """Shut down the DC core — disconnects all hubs, saves state."""
        loop = self._ensure_loop()
        await loop.run_in_executor(None, self._sync_client.shutdown)

    @property
    def is_initialized(self) -> bool:
        return self._sync_client.is_initialized

    @property
    def version(self) -> str:
        return self._sync_client.version

    async def __aenter__(self) -> "AsyncDCClient":
        await self.initialize()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.shutdown()

    # ------------------------------------------------------------------
    # Event registration (async-aware)
    # ------------------------------------------------------------------

    def on(
        self, event: str, handler: Optional[Callable[..., Any]] = None
    ) -> Callable:
        """
        Register an async or sync event handler.

        Works exactly like DCClient.on() but dispatches in the event loop
        thread. Async handlers are scheduled as tasks.

        As decorator:
            @client.on('chat_message')
            async def handle_chat(hub_url, nick, message):
                print(f'<{nick}> {message}')

        As method:
            client.on('chat_message', my_handler)
        """
        if event not in EVENT_TYPES:
            raise ValueError(
                f"Unknown event type: '{event}'. "
                f"Valid types: {sorted(EVENT_TYPES)}"
            )

        if handler is not None:
            with self._lock:
                self._handlers[event].append(handler)
            return handler

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            with self._lock:
                self._handlers[event].append(fn)
            return fn
        return decorator

    def off(self, event: str, handler: Callable[..., Any]) -> None:
        """Unregister an event handler."""
        with self._lock:
            try:
                self._handlers[event].remove(handler)
            except (KeyError, ValueError):
                pass

    def _dispatch_event(self, event: str, *args: Any) -> None:
        """
        Called from C++ callback threads. Schedules handler execution
        in the asyncio event loop thread via call_soon_threadsafe.
        """
        try:
            loop = self._ensure_loop()
        except RuntimeError:
            # No running loop — fall back to synchronous dispatch
            self._dispatch_sync(event, *args)
            return

        loop.call_soon_threadsafe(self._run_handlers, event, args)

    def _run_handlers(self, event: str, args: tuple) -> None:
        """Run handlers in the event loop thread."""
        with self._lock:
            handlers = self._handlers.get(event, [])[:]

        for handler in handlers:
            try:
                result = handler(*args)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            except Exception:
                logger.exception("Error in async handler for '%s'", event)

        # Also push to any subscribed queues
        for q in self._event_queues:
            try:
                q.put_nowait((event, args))
            except asyncio.QueueFull:
                pass

    def _dispatch_sync(self, event: str, *args: Any) -> None:
        """Fallback synchronous dispatch (no event loop)."""
        with self._lock:
            handlers = self._handlers.get(event, [])[:]
        for handler in handlers:
            try:
                handler(*args)
            except Exception:
                logger.exception("Error in sync handler for '%s'", event)

    # ------------------------------------------------------------------
    # Internal callback wiring
    # ------------------------------------------------------------------

    def _wire_callbacks(self) -> None:
        """Wire the sync client's events to our async dispatch."""

        @self._sync_client.on("hub_connected")
        def _on_connected(hub_url, hub_name):
            self._dispatch_event("hub_connected", hub_url, hub_name)
            # Signal any waiters
            try:
                loop = self._ensure_loop()
                ev = self._connect_events.get(hub_url)
                if ev:
                    loop.call_soon_threadsafe(ev.set)
            except RuntimeError:
                pass

        @self._sync_client.on("hub_disconnected")
        def _on_disconnected(hub_url, reason):
            self._dispatch_event("hub_disconnected", hub_url, reason)
            try:
                loop = self._ensure_loop()
                ev = self._disconnect_events.get(hub_url)
                if ev:
                    loop.call_soon_threadsafe(ev.set)
                # Also signal connect waiters (so they don't hang)
                cev = self._connect_events.get(hub_url)
                if cev:
                    loop.call_soon_threadsafe(cev.set)
            except RuntimeError:
                pass

        @self._sync_client.on("hub_connecting")
        def _on_connecting(hub_url):
            self._dispatch_event("hub_connecting", hub_url)

        @self._sync_client.on("hub_redirect")
        def _on_redirect(hub_url, new_url):
            self._dispatch_event("hub_redirect", hub_url, new_url)

        @self._sync_client.on("hub_get_password")
        def _on_password(hub_url):
            self._dispatch_event("hub_get_password", hub_url)

        @self._sync_client.on("hub_updated")
        def _on_updated(hub_url, hub_name):
            self._dispatch_event("hub_updated", hub_url, hub_name)

        @self._sync_client.on("hub_nick_taken")
        def _on_nick_taken(hub_url):
            self._dispatch_event("hub_nick_taken", hub_url)

        @self._sync_client.on("hub_full")
        def _on_full(hub_url):
            self._dispatch_event("hub_full", hub_url)

        @self._sync_client.on("chat_message")
        def _on_chat(hub_url, nick, message, third_person):
            self._dispatch_event(
                "chat_message", hub_url, nick, message, third_person
            )

        @self._sync_client.on("private_message")
        def _on_pm(hub_url, from_nick, to_nick, message):
            self._dispatch_event(
                "private_message", hub_url, from_nick, to_nick, message
            )
            try:
                loop = self._ensure_loop()
                loop.call_soon_threadsafe(
                    self._pm_queue.put_nowait,
                    (hub_url, from_nick, to_nick, message),
                )
            except RuntimeError:
                pass

        @self._sync_client.on("status_message")
        def _on_status(hub_url, message):
            self._dispatch_event("status_message", hub_url, message)

        @self._sync_client.on("user_connected")
        def _on_user_conn(hub_url, nick):
            self._dispatch_event("user_connected", hub_url, nick)

        @self._sync_client.on("user_disconnected")
        def _on_user_disc(hub_url, nick):
            self._dispatch_event("user_disconnected", hub_url, nick)

        @self._sync_client.on("user_updated")
        def _on_user_upd(hub_url, nick):
            self._dispatch_event("user_updated", hub_url, nick)

        @self._sync_client.on("search_result")
        def _on_search(hub_url, file, size, free, total, tth, nick, is_dir):
            self._dispatch_event(
                "search_result", hub_url, file, size, free, total,
                tth, nick, is_dir,
            )
            try:
                loop = self._ensure_loop()
                loop.call_soon_threadsafe(
                    self._search_queue.put_nowait,
                    {
                        "hub_url": hub_url, "file": file, "size": size,
                        "freeSlots": free, "totalSlots": total,
                        "tth": tth, "nick": nick, "isDirectory": is_dir,
                    },
                )
            except RuntimeError:
                pass

        @self._sync_client.on("queue_item_added")
        def _on_qa(target, size, tth):
            self._dispatch_event("queue_item_added", target, size, tth)

        @self._sync_client.on("queue_item_finished")
        def _on_qf(target, size):
            self._dispatch_event("queue_item_finished", target, size)
            ev = self._download_events.get(target)
            if ev:
                self._download_results[target] = (True, "")
                try:
                    loop = self._ensure_loop()
                    loop.call_soon_threadsafe(ev.set)
                except RuntimeError:
                    pass

        @self._sync_client.on("queue_item_removed")
        def _on_qr(target):
            self._dispatch_event("queue_item_removed", target)

        @self._sync_client.on("download_starting")
        def _on_ds(target, nick, size):
            self._dispatch_event("download_starting", target, nick, size)

        @self._sync_client.on("download_complete")
        def _on_dc(target, nick, size, speed):
            self._dispatch_event(
                "download_complete", target, nick, size, speed
            )
            ev = self._download_events.get(target)
            if ev:
                self._download_results[target] = (True, "")
                try:
                    loop = self._ensure_loop()
                    loop.call_soon_threadsafe(ev.set)
                except RuntimeError:
                    pass

        @self._sync_client.on("download_failed")
        def _on_df(target, reason):
            self._dispatch_event("download_failed", target, reason)
            ev = self._download_events.get(target)
            if ev:
                self._download_results[target] = (False, reason)
                try:
                    loop = self._ensure_loop()
                    loop.call_soon_threadsafe(ev.set)
                except RuntimeError:
                    pass

        @self._sync_client.on("upload_starting")
        def _on_us(file, nick, size):
            self._dispatch_event("upload_starting", file, nick, size)

        @self._sync_client.on("upload_complete")
        def _on_uc(file, nick, size):
            self._dispatch_event("upload_complete", file, nick, size)

        @self._sync_client.on("hash_progress")
        def _on_hash(current_file, files_left, bytes_left):
            self._dispatch_event(
                "hash_progress", current_file, files_left, bytes_left
            )

    # ------------------------------------------------------------------
    # Hub connections (async)
    # ------------------------------------------------------------------

    async def connect(
        self,
        url: str,
        encoding: str = "",
        *,
        wait: bool = False,
        timeout: float = 30.0,
    ) -> None:
        """
        Connect to a hub.

        Args:
            url: Hub URL (e.g. 'nmdcs://hub.example.com:411')
            encoding: Character encoding (default: UTF-8)
            wait: If True, await connection completion
            timeout: Timeout in seconds when wait=True
        """
        if not self._sync_client.is_initialized:
            await self.initialize()

        self._sync_client.connect(url, encoding)

        if wait:
            await self.wait_connected(url, timeout=timeout)

    async def wait_connected(
        self, url: str, *, timeout: float = 30.0
    ) -> None:
        """Wait until connected to a specific hub."""
        if self._sync_client.is_connected(url):
            return

        ev = asyncio.Event()
        self._connect_events[url] = ev
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
            if not self._sync_client.is_connected(url):
                raise ConnectionError(
                    f"Connection to {url} failed (disconnected)"
                )
        finally:
            self._connect_events.pop(url, None)

    async def disconnect(self, url: str) -> None:
        """Disconnect from a hub."""
        self._sync_client.disconnect(url)

    async def wait_disconnected(
        self, url: str, *, timeout: float = 10.0
    ) -> None:
        """Wait until disconnected from a specific hub."""
        if not self._sync_client.is_connected(url):
            return

        ev = asyncio.Event()
        self._disconnect_events[url] = ev
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
        finally:
            self._disconnect_events.pop(url, None)

    def is_connected(self, url: str) -> bool:
        """Check if connected to a specific hub."""
        return self._sync_client.is_connected(url)

    def list_hubs(self) -> list:
        """List connected hubs."""
        return self._sync_client.list_hubs()

    # ------------------------------------------------------------------
    # Chat (async)
    # ------------------------------------------------------------------

    def send_message(self, hub_url: str, message: str) -> None:
        """Send a public chat message."""
        self._sync_client.send_message(hub_url, message)

    def send_pm(self, hub_url: str, nick: str, message: str) -> None:
        """Send a private message."""
        self._sync_client.send_pm(hub_url, nick, message)

    async def wait_pm(
        self,
        *,
        from_nick: Optional[str] = None,
        timeout: float = 20.0,
    ) -> tuple[str, str, str, str]:
        """
        Wait for and return a private message.

        Args:
            from_nick: If specified, only return PMs from this nick
            timeout: Timeout in seconds

        Returns:
            Tuple of (hub_url, from_nick, to_nick, message)
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    f"No PM received within {timeout}s"
                    + (f" from {from_nick}" if from_nick else "")
                )
            try:
                pm = await asyncio.wait_for(
                    self._pm_queue.get(), timeout=remaining
                )
                if from_nick is None or pm[1] == from_nick:
                    return pm
                # Put it back? No — just keep draining. PMs from other
                # nicks are still dispatched to event handlers.
            except asyncio.TimeoutError:
                raise asyncio.TimeoutError(
                    f"No PM received within {timeout}s"
                    + (f" from {from_nick}" if from_nick else "")
                )

    def get_chat_history(
        self, hub_url: str, max_lines: int = 100
    ) -> list[str]:
        """Get recent chat history."""
        return self._sync_client.get_chat_history(hub_url, max_lines)

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def get_users(self, hub_url: str) -> list:
        """Get list of users on a hub."""
        return self._sync_client.get_users(hub_url)

    def get_user(self, nick: str, hub_url: str) -> Any:
        """Get info about a specific user."""
        return self._sync_client.get_user(nick, hub_url)

    async def wait_user(
        self,
        hub_url: str,
        nick: str,
        *,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
    ) -> Any:
        """
        Wait until a user appears in the user list.

        Args:
            hub_url: Hub URL to check
            nick: Nick to wait for
            timeout: Timeout in seconds
            poll_interval: How often to check (seconds)

        Returns:
            UserInfo for the found user
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            users = self.get_users(hub_url)
            for u in users:
                if u.nick == nick:
                    return u
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    f"User '{nick}' not found on {hub_url} "
                    f"within {timeout}s"
                )
            await asyncio.sleep(min(poll_interval, remaining))

    # ------------------------------------------------------------------
    # Search (async)
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        file_type: int = 0,
        size_mode: int = 0,
        size: int = 0,
        hub_url: str = "",
    ) -> bool:
        """Start a search."""
        return self._sync_client.search(
            query, file_type, size_mode, size, hub_url
        )

    async def search_and_wait(
        self,
        query: str,
        *,
        file_type: int = 0,
        size_mode: int = 0,
        size: int = 0,
        hub_url: str = "",
        timeout: float = 30.0,
        min_results: int = 1,
    ) -> list[dict[str, Any]]:
        """
        Search and wait for results.

        Args:
            query: Search string
            timeout: How long to wait for results
            min_results: Minimum number of results before returning

        Returns:
            List of search result dicts
        """
        self._sync_client.clear_search_results(hub_url)
        # Drain the queue
        while not self._search_queue.empty():
            try:
                self._search_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        self.search(query, file_type, size_mode, size, hub_url)

        results: list[dict[str, Any]] = []
        deadline = asyncio.get_event_loop().time() + timeout

        while len(results) < min_results:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                r = await asyncio.wait_for(
                    self._search_queue.get(), timeout=remaining
                )
                results.append(r)
            except asyncio.TimeoutError:
                break

        return results

    def get_search_results(self, hub_url: str = "") -> list:
        """Get accumulated search results."""
        return self._sync_client.get_search_results(hub_url)

    def clear_search_results(self, hub_url: str = "") -> None:
        """Clear search results."""
        self._sync_client.clear_search_results(hub_url)

    # ------------------------------------------------------------------
    # Download queue (async)
    # ------------------------------------------------------------------

    def download(
        self, directory: str, name: str, size: int, tth: str
    ) -> bool:
        """Add a file to the download queue."""
        return self._sync_client.download(directory, name, size, tth)

    def download_magnet(
        self, magnet: str, download_dir: str = ""
    ) -> bool:
        """Add a magnet link to the download queue."""
        return self._sync_client.download_magnet(magnet, download_dir)

    async def download_and_wait(
        self,
        directory: str,
        name: str,
        size: int,
        tth: str,
        *,
        timeout: float = 60.0,
    ) -> tuple[bool, str]:
        """
        Queue a download and wait for completion.

        Returns:
            Tuple of (success, error_message)
        """
        target = str(Path(directory) / name)
        ev = asyncio.Event()
        self._download_events[target] = ev
        self._download_results[target] = (False, "timeout")

        try:
            self.download(directory, name, size, tth)
            await asyncio.wait_for(ev.wait(), timeout=timeout)
            return self._download_results.get(target, (False, "unknown"))
        except asyncio.TimeoutError:
            return (False, f"Download timed out after {timeout}s")
        finally:
            self._download_events.pop(target, None)
            self._download_results.pop(target, None)

    def remove_download(self, target: str) -> None:
        """Remove from download queue."""
        self._sync_client.remove_download(target)

    def list_queue(self) -> list:
        """List download queue."""
        return self._sync_client.list_queue()

    def clear_queue(self) -> None:
        """Clear download queue."""
        self._sync_client.clear_queue()

    # ------------------------------------------------------------------
    # File lists (async)
    # ------------------------------------------------------------------

    def request_file_list(
        self, hub_url: str, nick: str, match_queue: bool = False
    ) -> bool:
        """Request a user's file list."""
        return self._sync_client.request_file_list(
            hub_url, nick, match_queue
        )

    async def request_and_browse_file_list(
        self,
        hub_url: str,
        nick: str,
        *,
        timeout: float = 60.0,
        poll_interval: float = 1.0,
    ) -> tuple[str, list]:
        """
        Request a file list and wait for it to download, then open and
        browse the root directory.

        Returns:
            Tuple of (file_list_id, root_entries)
        """
        self.request_file_list(hub_url, nick)

        # Wait for the file list to appear locally
        deadline = asyncio.get_event_loop().time() + timeout
        fl_id = None
        while True:
            lists = self._sync_client.list_local_file_lists()
            matches = [fl for fl in lists if nick in fl]
            if matches:
                fl_id = matches[0]
                break
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    f"File list from {nick} not received within {timeout}s"
                )
            await asyncio.sleep(min(poll_interval, remaining))

        # Open and browse
        ok = self._sync_client.open_file_list(fl_id)
        if not ok:
            raise RuntimeError(f"Failed to open file list {fl_id}")

        entries = list(
            self._sync_client.browse_file_list(fl_id, "/")
        )
        return (fl_id, entries)

    def browse_file_list(
        self, file_list_id: str, directory: str = "/"
    ) -> list:
        """Browse a directory in an opened file list."""
        return self._sync_client.browse_file_list(file_list_id, directory)

    def close_file_list(self, file_list_id: str) -> None:
        """Close an opened file list."""
        self._sync_client.close_file_list(file_list_id)

    def close_all_file_lists(self) -> None:
        """Close all opened file lists."""
        self._sync_client.close_all_file_lists()

    # ------------------------------------------------------------------
    # Sharing
    # ------------------------------------------------------------------

    def add_share(self, real_path: str, virtual_name: str) -> bool:
        return self._sync_client.add_share(real_path, virtual_name)

    def remove_share(self, real_path: str) -> bool:
        return self._sync_client.remove_share(real_path)

    def list_shares(self) -> list:
        return self._sync_client.list_shares()

    def refresh_share(self) -> None:
        self._sync_client.refresh_share()

    @property
    def share_size(self) -> int:
        return self._sync_client.share_size

    @property
    def shared_files(self) -> int:
        return self._sync_client.shared_files

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def get_setting(self, name: str) -> str:
        return self._sync_client.get_setting(name)

    def set_setting(self, name: str, value: str) -> None:
        self._sync_client.set_setting(name, value)

    # ------------------------------------------------------------------
    # Transfers & Hashing
    # ------------------------------------------------------------------

    @property
    def transfer_stats(self) -> Any:
        return self._sync_client.transfer_stats

    @property
    def hash_status(self) -> Any:
        return self._sync_client.hash_status

    def pause_hashing(self, pause: bool = True) -> None:
        self._sync_client.pause_hashing(pause)

    # ------------------------------------------------------------------
    # Event stream (async iterator)
    # ------------------------------------------------------------------

    def events(self, maxsize: int = 1000) -> "EventStream":
        """
        Create an async iterator that yields all events.

        Usage:
            async for event_name, args in client.events():
                print(f'{event_name}: {args}')
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._event_queues.append(q)
        return EventStream(q, self._event_queues)

    # ------------------------------------------------------------------
    # repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        state = "initialized" if self.is_initialized else "not initialized"
        return f"AsyncDCClient({state})"


class EventStream:
    """
    Async iterator that yields (event_name, args) tuples.

    Usage:
        stream = client.events()
        async for event, args in stream:
            ...
        await stream.close()
    """

    def __init__(
        self,
        queue: asyncio.Queue,
        registry: list[asyncio.Queue],
    ) -> None:
        self._queue = queue
        self._registry = registry

    def __aiter__(self) -> "EventStream":
        return self

    async def __anext__(self) -> tuple[str, tuple]:
        try:
            return await self._queue.get()
        except asyncio.CancelledError:
            raise StopAsyncIteration

    async def close(self) -> None:
        """Stop receiving events."""
        try:
            self._registry.remove(self._queue)
        except ValueError:
            pass
