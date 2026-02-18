"""
Remote API client wrapper for eiskaltdcpp-py.

Provides ``RemoteDCClient`` — a drop-in replacement for ``DCClient`` /
``AsyncDCClient`` that communicates with the REST API + WebSocket instead
of the C++ SWIG bindings directly.

Usage::

    from eiskaltdcpp.api.client import RemoteDCClient

    async with RemoteDCClient("http://localhost:8080",
                               username="admin",
                               password="secret") as client:
        await client.connect("dchub://hub.example.com:411")
        hubs = client.list_hubs()
        for hub in hubs:
            print(hub.url, hub.name)

        # Real-time events via WebSocket
        async for event, data in client.events():
            print(event, data)
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Optional
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)


# ============================================================================
# Data classes mimicking DC client objects
# ============================================================================

@dataclass
class HubInfo:
    """Hub connection info (mirrors HubStatus model)."""
    url: str
    name: str = ""
    connected: bool = False
    user_count: int = 0
    userCount: int = 0  # alias for compat

    def __post_init__(self):
        self.userCount = self.user_count


@dataclass
class UserInfo:
    """DC user info on a hub."""
    nick: str
    share_size: int = 0
    shareSize: int = 0
    description: str = ""
    tag: str = ""
    connection: str = ""
    email: str = ""
    hub_url: str = ""

    def __post_init__(self):
        self.shareSize = self.share_size


@dataclass
class SearchResultInfo:
    """A search result."""
    hub_url: str = ""
    hubUrl: str = ""
    file: str = ""
    size: int = 0
    free_slots: int = 0
    freeSlots: int = 0
    total_slots: int = 0
    totalSlots: int = 0
    tth: str = ""
    nick: str = ""
    is_directory: bool = False
    isDirectory: bool = False

    def __post_init__(self):
        self.hubUrl = self.hub_url
        self.freeSlots = self.free_slots
        self.totalSlots = self.total_slots
        self.isDirectory = self.is_directory


@dataclass
class QueueItemInfo:
    """A queued download."""
    target: str = ""
    size: int = 0
    downloaded: int = 0
    downloadedBytes: int = 0
    priority: int = 0
    tth: str = ""

    def __post_init__(self):
        self.downloadedBytes = self.downloaded


@dataclass
class ShareInfoData:
    """A shared directory."""
    real_path: str = ""
    realPath: str = ""
    virtual_name: str = ""
    virtualName: str = ""
    size: int = 0

    def __post_init__(self):
        self.realPath = self.real_path
        self.virtualName = self.virtual_name


@dataclass
class TransferStats:
    """Aggregate transfer stats."""
    download_speed: int = 0
    downloadSpeed: int = 0
    upload_speed: int = 0
    uploadSpeed: int = 0
    downloaded: int = 0
    uploaded: int = 0

    def __post_init__(self):
        self.downloadSpeed = self.download_speed
        self.uploadSpeed = self.upload_speed


@dataclass
class HashStatus:
    """File hashing status."""
    current_file: str = ""
    currentFile: str = ""
    files_left: int = 0
    filesLeft: int = 0
    bytes_left: int = 0
    bytesLeft: int = 0
    is_paused: bool = False
    isPaused: bool = False

    def __post_init__(self):
        self.currentFile = self.current_file
        self.filesLeft = self.files_left
        self.bytesLeft = self.bytes_left
        self.isPaused = self.is_paused


# ============================================================================
# WebSocket event stream
# ============================================================================

class RemoteEventStream:
    """
    Async iterator over WebSocket events from the API server.

    Yields ``(event_name, data_dict)`` tuples, matching the
    ``AsyncDCClient.events()`` interface.
    """

    def __init__(self, ws_url: str, token: str,
                 channels: str = "events") -> None:
        self._ws_url = ws_url
        self._token = token
        self._channels = channels
        self._ws: Optional[Any] = None
        self._closed = False
        self._queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue(maxsize=5000)
        self._task: Optional[asyncio.Task] = None

    async def _connect(self) -> None:
        """Connect the underlying WebSocket."""
        try:
            import websockets
            url = f"{self._ws_url}?token={self._token}&channels={self._channels}"
            self._ws = await websockets.connect(url)
            self._task = asyncio.create_task(self._read_loop())
        except ImportError:
            raise ImportError(
                "websockets package required for RemoteEventStream. "
                "Install with: pip install websockets"
            )

    async def _read_loop(self) -> None:
        """Read messages from WebSocket and queue events."""
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "event":
                    event_name = msg.get("event", "unknown")
                    data = msg.get("data", {})
                    try:
                        self._queue.put_nowait((event_name, data))
                    except asyncio.QueueFull:
                        pass
                elif msg.get("type") == "status":
                    try:
                        self._queue.put_nowait(("_status", msg.get("data", {})))
                    except asyncio.QueueFull:
                        pass
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("WebSocket read loop error")

    def __aiter__(self) -> RemoteEventStream:
        return self

    async def __anext__(self) -> tuple[str, dict]:
        if self._closed:
            raise StopAsyncIteration
        if self._ws is None:
            await self._connect()
        try:
            return await self._queue.get()
        except asyncio.CancelledError:
            raise StopAsyncIteration

    async def close(self) -> None:
        """Close the WebSocket connection."""
        self._closed = True
        if self._task:
            self._task.cancel()
            self._task = None
        if self._ws:
            await self._ws.close()
            self._ws = None


# ============================================================================
# Remote DC Client
# ============================================================================

class RemoteDCClient:
    """
    API client that mirrors the ``DCClient`` / ``AsyncDCClient`` interface
    but communicates via the REST API and WebSocket.

    All methods that modify state require admin role.
    Read-only methods work with any authenticated role.

    Example::

        client = RemoteDCClient("http://localhost:8080")
        await client.login("admin", "password")

        await client.connect("dchub://hub.example.com:411")
        hubs = client.list_hubs()

        async for event, data in client.events():
            print(event, data)

        await client.close()
    """

    def __init__(
        self,
        base_url: str,
        *,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._token = token
        self._timeout = timeout
        self._http: Optional[httpx.AsyncClient] = None
        self._handlers: dict[str, list[Callable]] = {}
        self._version: Optional[str] = None
        self._initialized = False

    # ---- Lifecycle ----

    async def __aenter__(self) -> RemoteDCClient:
        await self._ensure_http()
        if self._token is None and self._username and self._password:
            await self.login(self._username, self._password)
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def _ensure_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
            )
        return self._http

    def _headers(self) -> dict[str, str]:
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    async def _get(self, path: str, **params) -> dict:
        http = await self._ensure_http()
        resp = await http.get(path, headers=self._headers(), params=params)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, body: Optional[dict] = None,
                    **params) -> dict:
        http = await self._ensure_http()
        resp = await http.post(path, headers=self._headers(),
                               json=body, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _put(self, path: str, body: dict) -> dict:
        http = await self._ensure_http()
        resp = await http.put(path, headers=self._headers(), json=body)
        resp.raise_for_status()
        return resp.json()

    async def _delete(self, path: str, **params) -> dict:
        http = await self._ensure_http()
        resp = await http.delete(path, headers=self._headers(), params=params)
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    # ---- Auth ----

    async def login(self, username: str, password: str) -> str:
        """Authenticate and store JWT token. Returns the token."""
        http = await self._ensure_http()
        resp = await http.post("/api/auth/login", json={
            "username": username, "password": password,
        })
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._username = username
        return self._token

    # ---- Properties ----

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def version(self) -> str:
        return self._version or "unknown"

    # ---- Hubs ----

    async def connect(self, url: str, encoding: str = "") -> None:
        """Connect to a DC hub."""
        await self._post("/api/hubs/connect",
                         {"url": url, "encoding": encoding})

    async def disconnect(self, url: str) -> None:
        """Disconnect from a DC hub."""
        await self._post("/api/hubs/disconnect", {"url": url})

    def list_hubs(self) -> list[HubInfo]:
        """List connected hubs (sync wrapper, call from async with await)."""
        raise TypeError(
            "list_hubs() is async on RemoteDCClient. "
            "Use 'hubs = await client.list_hubs_async()' instead."
        )

    async def list_hubs_async(self) -> list[HubInfo]:
        """List connected hubs."""
        data = await self._get("/api/hubs")
        return [HubInfo(**h) for h in data.get("hubs", [])]

    def is_connected(self, url: str) -> bool:
        raise TypeError("Use await is_connected_async()")

    async def is_connected_async(self, url: str) -> bool:
        """Check if connected to a hub."""
        hubs = await self.list_hubs_async()
        return any(h.url == url and h.connected for h in hubs)

    # ---- Chat ----

    def send_message(self, hub_url: str, message: str) -> None:
        raise TypeError("Use await send_message_async()")

    async def send_message_async(self, hub_url: str, message: str) -> None:
        """Send a public chat message."""
        await self._post("/api/chat/message",
                         {"hub_url": hub_url, "message": message})

    def send_pm(self, hub_url: str, nick: str, message: str) -> None:
        raise TypeError("Use await send_pm_async()")

    async def send_pm_async(self, hub_url: str, nick: str,
                            message: str) -> None:
        """Send a private message."""
        await self._post("/api/chat/pm",
                         {"hub_url": hub_url, "nick": nick,
                          "message": message})

    def get_chat_history(self, hub_url: str,
                         max_lines: int = 100) -> list[str]:
        raise TypeError("Use await get_chat_history_async()")

    async def get_chat_history_async(self, hub_url: str,
                                     max_lines: int = 100) -> list[str]:
        """Get chat history for a hub."""
        data = await self._get("/api/chat/history",
                               hub_url=hub_url, max_lines=max_lines)
        return data.get("messages", [])

    # ---- Users ----

    def get_users(self, hub_url: str) -> list[UserInfo]:
        raise TypeError("Use await get_users_async()")

    async def get_users_async(self, hub_url: str) -> list[UserInfo]:
        """Get users on a hub."""
        data = await self._get("/api/hubs/users", hub_url=hub_url)
        return [UserInfo(**u) for u in data.get("users", [])]

    # ---- Search ----

    def search(self, query: str, file_type: int = 0, size_mode: int = 0,
               size: int = 0, hub_url: str = "") -> bool:
        raise TypeError("Use await search_async()")

    async def search_async(self, query: str, file_type: int = 0,
                           size_mode: int = 0, size: int = 0,
                           hub_url: str = "") -> bool:
        """Start a search."""
        try:
            await self._post("/api/search", {
                "query": query, "file_type": file_type,
                "size_mode": size_mode, "size": size, "hub_url": hub_url,
            })
            return True
        except httpx.HTTPStatusError:
            return False

    def get_search_results(self, hub_url: str = "") -> list[SearchResultInfo]:
        raise TypeError("Use await get_search_results_async()")

    async def get_search_results_async(
        self, hub_url: str = "",
    ) -> list[SearchResultInfo]:
        """Get accumulated search results."""
        data = await self._get("/api/search/results", hub_url=hub_url)
        return [SearchResultInfo(**r) for r in data.get("results", [])]

    def clear_search_results(self, hub_url: str = "") -> None:
        raise TypeError("Use await clear_search_results_async()")

    async def clear_search_results_async(self, hub_url: str = "") -> None:
        """Clear search results."""
        await self._delete("/api/search/results", hub_url=hub_url)

    # ---- Queue ----

    def download(self, directory: str, name: str, size: int, tth: str,
                 hub_url: str = "", nick: str = "") -> bool:
        raise TypeError("Use await download_async()")

    async def download_async(self, directory: str, name: str, size: int,
                             tth: str, hub_url: str = "",
                             nick: str = "") -> bool:
        """Add a file to the download queue."""
        try:
            await self._post("/api/queue", {
                "directory": directory, "name": name, "size": size,
                "tth": tth, "hub_url": hub_url, "nick": nick,
            })
            return True
        except httpx.HTTPStatusError:
            return False

    def download_magnet(self, magnet: str, download_dir: str = "") -> bool:
        raise TypeError("Use await download_magnet_async()")

    async def download_magnet_async(self, magnet: str,
                                    download_dir: str = "") -> bool:
        """Add a magnet link to the download queue."""
        try:
            await self._post("/api/queue/magnet",
                             {"magnet": magnet, "download_dir": download_dir})
            return True
        except httpx.HTTPStatusError:
            return False

    def remove_download(self, target: str) -> None:
        raise TypeError("Use await remove_download_async()")

    async def remove_download_async(self, target: str) -> None:
        """Remove a download from the queue."""
        await self._delete(f"/api/queue/{target}")

    def list_queue(self) -> list[QueueItemInfo]:
        raise TypeError("Use await list_queue_async()")

    async def list_queue_async(self) -> list[QueueItemInfo]:
        """List the download queue."""
        data = await self._get("/api/queue")
        return [QueueItemInfo(**q) for q in data.get("items", [])]

    def clear_queue(self) -> None:
        raise TypeError("Use await clear_queue_async()")

    async def clear_queue_async(self) -> None:
        """Clear the entire download queue."""
        await self._delete("/api/queue")

    def set_priority(self, target: str, priority: int) -> None:
        raise TypeError("Use await set_priority_async()")

    async def set_priority_async(self, target: str, priority: int) -> None:
        """Set download priority."""
        await self._put(f"/api/queue/{target}/priority",
                        {"priority": priority})

    # ---- Shares ----

    def add_share(self, real_path: str, virtual_name: str) -> bool:
        raise TypeError("Use await add_share_async()")

    async def add_share_async(self, real_path: str,
                              virtual_name: str) -> bool:
        """Add a directory to share."""
        try:
            await self._post("/api/shares",
                             {"real_path": real_path,
                              "virtual_name": virtual_name})
            return True
        except httpx.HTTPStatusError:
            return False

    def remove_share(self, real_path: str) -> bool:
        raise TypeError("Use await remove_share_async()")

    async def remove_share_async(self, real_path: str) -> bool:
        """Remove a directory from share."""
        try:
            await self._delete("/api/shares", real_path=real_path)
            return True
        except httpx.HTTPStatusError:
            return False

    def list_shares(self) -> list[ShareInfoData]:
        raise TypeError("Use await list_shares_async()")

    async def list_shares_async(self) -> list[ShareInfoData]:
        """List shared directories."""
        data = await self._get("/api/shares")
        return [ShareInfoData(**s) for s in data.get("shares", [])]

    def refresh_share(self) -> None:
        raise TypeError("Use await refresh_share_async()")

    async def refresh_share_async(self) -> None:
        """Refresh shared file lists."""
        await self._post("/api/shares/refresh")

    @property
    def share_size(self) -> int:
        raise TypeError("Use await get_share_size()")

    async def get_share_size(self) -> int:
        """Get total share size."""
        data = await self._get("/api/shares")
        return data.get("total_size", 0)

    @property
    def shared_files(self) -> int:
        raise TypeError("Use await get_shared_files()")

    async def get_shared_files(self) -> int:
        """Get total shared files count."""
        data = await self._get("/api/shares")
        return data.get("total_files", 0)

    # ---- Settings ----

    def get_setting(self, name: str) -> str:
        raise TypeError("Use await get_setting_async()")

    async def get_setting_async(self, name: str) -> str:
        """Get a DC client setting."""
        data = await self._get(f"/api/settings/{name}")
        return data.get("value", "")

    def set_setting(self, name: str, value: str) -> None:
        raise TypeError("Use await set_setting_async()")

    async def set_setting_async(self, name: str, value: str) -> None:
        """Set a DC client setting."""
        await self._put(f"/api/settings/{name}",
                        {"name": name, "value": value})

    def reload_config(self) -> None:
        raise TypeError("Use await reload_config_async()")

    async def reload_config_async(self) -> None:
        """Reload DC client configuration."""
        await self._post("/api/settings/reload")

    def start_networking(self) -> None:
        raise TypeError("Use await start_networking_async()")

    async def start_networking_async(self) -> None:
        """Rebind network listeners."""
        await self._post("/api/settings/networking")

    # ---- Transfers & Hashing ----

    @property
    def transfer_stats(self) -> TransferStats:
        raise TypeError("Use await get_transfer_stats()")

    async def get_transfer_stats(self) -> TransferStats:
        """Get transfer statistics."""
        data = await self._get("/api/status/transfers")
        return TransferStats(**data)

    @property
    def hash_status(self) -> HashStatus:
        raise TypeError("Use await get_hash_status()")

    async def get_hash_status(self) -> HashStatus:
        """Get hashing status."""
        data = await self._get("/api/status/hashing")
        return HashStatus(**data)

    def pause_hashing(self, pause: bool = True) -> None:
        raise TypeError("Use await pause_hashing_async()")

    async def pause_hashing_async(self, pause: bool = True) -> None:
        """Pause or resume file hashing."""
        await self._post("/api/status/hashing/pause", pause=pause)

    # ---- Status ----

    async def get_status(self) -> dict:
        """Get full system status."""
        data = await self._get("/api/status")
        self._version = data.get("version", "unknown")
        self._initialized = data.get("initialized", False)
        return data

    async def health_check(self) -> bool:
        """Check if the API server is healthy."""
        try:
            data = await self._get("/api/health")
            return data.get("ok", False)
        except Exception:
            return False

    async def shutdown(self) -> None:
        """Request a graceful server shutdown (admin only).

        Sends POST /api/shutdown which triggers SIGTERM on the server
        process for a clean shutdown.
        """
        try:
            await self._post("/api/shutdown")
        except httpx.RemoteProtocolError:
            # Server may close connection immediately — that's expected
            pass

    # ---- Event stream ----

    def events(self, channels: str = "events") -> RemoteEventStream:
        """
        Get a real-time event stream via WebSocket.

        Returns an async iterator yielding ``(event_name, data_dict)``
        tuples, matching the ``AsyncDCClient.events()`` interface.

        Args:
            channels: Comma-separated channel names
                      (events, chat, search, transfers, hubs, status)

        Example::

            async for event, data in client.events("chat,search"):
                if event == "chat_message":
                    print(f"<{data['nick']}> {data['message']}")
        """
        ws_base = self._base_url.replace("http://", "ws://").replace(
            "https://", "wss://")
        ws_url = f"{ws_base}/ws/events"
        return RemoteEventStream(ws_url, self._token or "", channels)

    # ---- Event handlers (for compatibility) ----

    def on(self, event: str, handler: Optional[Callable] = None):
        """
        Register an event handler (decorator compatible).

        Note: To receive events, you must also iterate ``client.events()``
        in a background task.
        """
        def decorator(fn):
            self._handlers.setdefault(event, []).append(fn)
            return fn
        if handler is not None:
            return decorator(handler)
        return decorator

    def off(self, event: str, handler: Callable) -> None:
        """Unregister an event handler."""
        handlers = self._handlers.get(event, [])
        if handler in handlers:
            handlers.remove(handler)

    # ---- User management ----

    async def create_user(self, username: str, password: str,
                          role: str = "readonly") -> dict:
        """Create a new API user (admin only)."""
        data = await self._post("/api/auth/users", {
            "username": username, "password": password, "role": role,
        })
        return data

    async def list_users(self) -> list[dict]:
        """List all API users (admin only)."""
        data = await self._get("/api/auth/users")
        return data.get("users", [])

    async def delete_user(self, username: str) -> None:
        """Delete an API user (admin only)."""
        await self._delete(f"/api/auth/users/{username}")

    async def update_user(self, username: str,
                          password: Optional[str] = None,
                          role: Optional[str] = None) -> dict:
        """Update an API user (admin only)."""
        body: dict[str, Any] = {}
        if password is not None:
            body["password"] = password
        if role is not None:
            body["role"] = role
        return await self._put(f"/api/auth/users/{username}", body)
