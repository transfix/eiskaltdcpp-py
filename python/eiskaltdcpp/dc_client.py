"""
High-level Python wrapper for the eiskaltdcpp DC client core.

This module provides a Pythonic interface to the C++ DCBridge via SWIG bindings,
following the same pattern as verlihub's core.py wrapper.

Usage:
    from eiskaltdcpp import DCClient

    client = DCClient('/tmp/dc-config')
    client.on('chat_message', lambda hub, nick, msg: print(f'<{nick}> {msg}'))
    client.connect('dchub://example.com:411')

    # Or as context manager:
    with DCClient('/tmp/dc-config') as client:
        client.connect('dchub://example.com:411')
        import time; time.sleep(30)
    # shutdown() called automatically
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Optional

# Import SWIG module (built by CMake)
try:
    from eiskaltdcpp import dc_core
except ImportError as e:
    raise ImportError(
        "dc_core SWIG module not found. "
        "Build with CMake first: cmake --build build/"
    ) from e

logger = logging.getLogger(__name__)


# ============================================================================
# Event types
# ============================================================================

EVENT_TYPES = frozenset({
    # Hub events
    "hub_connecting",
    "hub_connected",
    "hub_disconnected",
    "hub_redirect",
    "hub_get_password",
    "hub_updated",
    "hub_nick_taken",
    "hub_full",
    # Chat events
    "chat_message",
    "private_message",
    "status_message",
    # User events
    "user_connected",
    "user_disconnected",
    "user_updated",
    # Search events
    "search_result",
    # Queue events
    "queue_item_added",
    "queue_item_finished",
    "queue_item_removed",
    # Transfer events
    "download_starting",
    "download_complete",
    "download_failed",
    "upload_starting",
    "upload_complete",
    # Hash events
    "hash_progress",
})


# ============================================================================
# Callback router — bridges SWIG director calls to Python event handlers
# ============================================================================

class _CallbackRouter(dc_core.DCClientCallback):
    """
    Internal SWIG director class that receives C++ callbacks and dispatches
    them to registered Python handlers.

    Must be kept alive as long as the bridge is active (prevent GC).
    """

    def __init__(self) -> None:
        super().__init__()
        self._handlers: dict[str, list[Callable[..., Any]]] = {
            event: [] for event in EVENT_TYPES
        }
        self._lock = threading.Lock()

    def register(self, event: str, handler: Callable[..., Any]) -> None:
        """Register a handler for an event type."""
        if event not in EVENT_TYPES:
            raise ValueError(
                f"Unknown event type: '{event}'. "
                f"Valid types: {sorted(EVENT_TYPES)}"
            )
        with self._lock:
            self._handlers[event].append(handler)

    def unregister(self, event: str, handler: Callable[..., Any]) -> None:
        """Unregister a previously registered handler."""
        with self._lock:
            try:
                self._handlers[event].remove(handler)
            except (KeyError, ValueError):
                pass

    def _dispatch(self, event: str, *args: Any) -> None:
        """Dispatch an event to all registered handlers."""
        with self._lock:
            handlers = self._handlers.get(event, [])[:]
        for handler in handlers:
            try:
                handler(*args)
            except Exception:
                logger.exception("Error in event handler for '%s'", event)

    # -------------------------------------------------------------------
    # C++ callback overrides (called from C++ threads via SWIG directors)
    # -------------------------------------------------------------------

    # Hub events
    def onHubConnecting(self, hubUrl: str) -> None:
        self._dispatch("hub_connecting", hubUrl)

    def onHubConnected(self, hubUrl: str, hubName: str) -> None:
        self._dispatch("hub_connected", hubUrl, hubName)

    def onHubDisconnected(self, hubUrl: str, reason: str) -> None:
        self._dispatch("hub_disconnected", hubUrl, reason)

    def onHubRedirect(self, hubUrl: str, newUrl: str) -> None:
        self._dispatch("hub_redirect", hubUrl, newUrl)

    def onHubGetPassword(self, hubUrl: str) -> None:
        self._dispatch("hub_get_password", hubUrl)

    def onHubUpdated(self, hubUrl: str, hubName: str) -> None:
        self._dispatch("hub_updated", hubUrl, hubName)

    def onHubNickTaken(self, hubUrl: str) -> None:
        self._dispatch("hub_nick_taken", hubUrl)

    def onHubFull(self, hubUrl: str) -> None:
        self._dispatch("hub_full", hubUrl)

    # Chat events
    def onChatMessage(self, hubUrl: str, nick: str, message: str) -> None:
        self._dispatch("chat_message", hubUrl, nick, message)

    def onPrivateMessage(self, hubUrl: str, nick: str, message: str) -> None:
        self._dispatch("private_message", hubUrl, nick, message)

    def onStatusMessage(self, hubUrl: str, message: str) -> None:
        self._dispatch("status_message", hubUrl, message)

    # User events
    def onUserConnected(self, hubUrl: str, user: dc_core.UserInfo) -> None:
        self._dispatch("user_connected", hubUrl, user)

    def onUserDisconnected(self, hubUrl: str, user: dc_core.UserInfo) -> None:
        self._dispatch("user_disconnected", hubUrl, user)

    def onUserUpdated(self, hubUrl: str, user: dc_core.UserInfo) -> None:
        self._dispatch("user_updated", hubUrl, user)

    # Search events
    def onSearchResult(self, result: dc_core.SearchResultInfo) -> None:
        self._dispatch("search_result", result)

    # Queue events
    def onQueueItemAdded(self, item: dc_core.QueueItemInfo) -> None:
        self._dispatch("queue_item_added", item)

    def onQueueItemFinished(self, item: dc_core.QueueItemInfo) -> None:
        self._dispatch("queue_item_finished", item)

    def onQueueItemRemoved(self, target: str) -> None:
        self._dispatch("queue_item_removed", target)

    # Transfer events
    def onDownloadStarting(self, transfer: dc_core.TransferInfo) -> None:
        self._dispatch("download_starting", transfer)

    def onDownloadComplete(self, transfer: dc_core.TransferInfo) -> None:
        self._dispatch("download_complete", transfer)

    def onDownloadFailed(
        self, transfer: dc_core.TransferInfo, reason: str
    ) -> None:
        self._dispatch("download_failed", transfer, reason)

    def onUploadStarting(self, transfer: dc_core.TransferInfo) -> None:
        self._dispatch("upload_starting", transfer)

    def onUploadComplete(self, transfer: dc_core.TransferInfo) -> None:
        self._dispatch("upload_complete", transfer)

    # Hash events
    def onHashProgress(
        self, currentFile: str, filesLeft: int, bytesLeft: int
    ) -> None:
        self._dispatch("hash_progress", currentFile, filesLeft, bytesLeft)


# ============================================================================
# DCClient — High-level Pythonic wrapper
# ============================================================================

class DCClient:
    """
    High-level Python DC client wrapping libeiskaltdcpp.

    Provides a Pythonic interface with event handlers, context manager
    support, and snake_case naming conventions.

    Args:
        config_dir: Configuration directory for DCPlusPlus settings.
                    Defaults to ~/.eiskaltdcpp-py/

    Example:
        client = DCClient('/tmp/dc-config')

        @client.on('chat_message')
        def on_chat(hub_url, nick, message):
            print(f'<{nick}> {message}')

        client.connect('dchub://example.com:411')
        # ... later ...
        client.disconnect('dchub://example.com:411')
        client.shutdown()
    """

    def __init__(self, config_dir: str | Path = "") -> None:
        self._bridge = dc_core.DCBridge()
        self._router = _CallbackRouter()
        self._config_dir = str(config_dir) if config_dir else ""
        self._initialized = False

    def initialize(self) -> bool:
        """Initialize the DC core library. Must be called before any other ops."""
        if self._initialized:
            return True
        ok = self._bridge.initialize(self._config_dir)
        if ok:
            self._bridge.setCallback(self._router)
            self._initialized = True
        return ok

    def shutdown(self) -> None:
        """Shut down the DC core — disconnects all hubs, saves state."""
        if self._initialized:
            self._bridge.shutdown()
            self._initialized = False

    @property
    def is_initialized(self) -> bool:
        """Whether the core has been initialized."""
        return self._initialized

    @property
    def version(self) -> str:
        """Get libeiskaltdcpp version string."""
        return dc_core.DCBridge.getVersion()

    # ------------------------------------------------------------------
    # Event registration
    # ------------------------------------------------------------------

    def on(
        self, event: str, handler: Optional[Callable[..., Any]] = None
    ) -> Callable:
        """
        Register an event handler. Can be used as a decorator or method call.

        As decorator:
            @client.on('chat_message')
            def handle_chat(hub_url, nick, message):
                print(f'<{nick}> {message}')

        As method:
            client.on('chat_message', my_handler)

        Args:
            event: Event type (see EVENT_TYPES)
            handler: Callback function (optional when used as decorator)
        """
        if handler is not None:
            self._router.register(event, handler)
            return handler

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._router.register(event, fn)
            return fn
        return decorator

    def off(self, event: str, handler: Callable[..., Any]) -> None:
        """Unregister an event handler."""
        self._router.unregister(event, handler)

    # ------------------------------------------------------------------
    # Hub connections
    # ------------------------------------------------------------------

    def connect(self, url: str, encoding: str = "") -> None:
        """Connect to a hub. Auto-initializes if needed."""
        if not self._initialized:
            self.initialize()
        self._bridge.connectHub(url, encoding)

    def disconnect(self, url: str) -> None:
        """Disconnect from a hub."""
        self._bridge.disconnectHub(url)

    def list_hubs(self) -> list:
        """List connected hubs and their status."""
        return list(self._bridge.listHubs())

    def is_connected(self, url: str) -> bool:
        """Check if connected to a specific hub."""
        return self._bridge.isHubConnected(url)

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def send_message(self, hub_url: str, message: str) -> None:
        """Send a public chat message to a hub."""
        self._bridge.sendMessage(hub_url, message)

    def send_pm(self, hub_url: str, nick: str, message: str) -> None:
        """Send a private message to a user on a hub."""
        self._bridge.sendPM(hub_url, nick, message)

    def get_chat_history(
        self, hub_url: str, max_lines: int = 100
    ) -> list[str]:
        """Get recent chat history for a hub."""
        return list(self._bridge.getChatHistory(hub_url, max_lines))

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def get_users(self, hub_url: str) -> list:
        """Get list of users on a hub."""
        return list(self._bridge.getHubUsers(hub_url))

    def get_user(self, nick: str, hub_url: str) -> Any:
        """Get information about a specific user."""
        return self._bridge.getUserInfo(nick, hub_url)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        file_type: int = 0,
        size_mode: int = 0,
        size: int = 0,
        hub_url: str = "",
    ) -> bool:
        """
        Start a search across connected hubs.

        Args:
            query: Search string
            file_type: 0=any, 1=audio, 2=compressed, 3=document,
                       4=executable, 5=picture, 6=video, 7=folder, 8=TTH
            size_mode: 0=any, 1=at least, 2=at most, 3=exact
            size: Size filter in bytes (0 = no filter)
            hub_url: Optional - search only this hub
        """
        return self._bridge.search(query, file_type, size_mode, size, hub_url)

    def get_search_results(self, hub_url: str = "") -> list:
        """Get accumulated search results."""
        return list(self._bridge.getSearchResults(hub_url))

    def clear_search_results(self, hub_url: str = "") -> None:
        """Clear search results."""
        self._bridge.clearSearchResults(hub_url)

    # ------------------------------------------------------------------
    # Download queue
    # ------------------------------------------------------------------

    def download(
        self,
        directory: str,
        name: str,
        size: int,
        tth: str,
    ) -> bool:
        """Add a file to the download queue."""
        return self._bridge.addToQueue(directory, name, size, tth)

    def download_magnet(
        self, magnet: str, download_dir: str = ""
    ) -> bool:
        """Add a magnet link to the download queue."""
        return self._bridge.addMagnet(magnet, download_dir)

    def remove_download(self, target: str) -> None:
        """Remove an item from the download queue."""
        self._bridge.removeFromQueue(target)

    def move_download(self, source: str, target: str) -> None:
        """Move a queued download to a new location."""
        self._bridge.moveQueueItem(source, target)

    def set_priority(self, target: str, priority: int) -> None:
        """Set download priority (0=paused, 1=lowest..5=highest)."""
        self._bridge.setPriority(target, priority)

    def list_queue(self) -> list:
        """List all items in the download queue."""
        return list(self._bridge.listQueue())

    def clear_queue(self) -> None:
        """Clear the entire download queue."""
        self._bridge.clearQueue()

    # ------------------------------------------------------------------
    # File lists
    # ------------------------------------------------------------------

    def request_file_list(
        self, hub_url: str, nick: str, match_queue: bool = False
    ) -> bool:
        """Request a user's file list."""
        return self._bridge.requestFileList(hub_url, nick, match_queue)

    def list_local_file_lists(self) -> list[str]:
        """List locally stored file lists."""
        return list(self._bridge.listLocalFileLists())

    def open_file_list(self, file_list_id: str) -> bool:
        """Open/parse a local file list."""
        return self._bridge.openFileList(file_list_id)

    def browse_file_list(
        self, file_list_id: str, directory: str = "/"
    ) -> list:
        """Browse a directory in an opened file list."""
        return list(self._bridge.browseFileList(file_list_id, directory))

    def download_from_list(
        self,
        file_list_id: str,
        file_path: str,
        download_to: str = "",
    ) -> bool:
        """Download a file from a file list."""
        return self._bridge.downloadFileFromList(
            file_list_id, file_path, download_to
        )

    def download_dir_from_list(
        self,
        file_list_id: str,
        dir_path: str,
        download_to: str = "",
    ) -> bool:
        """Download an entire directory from a file list."""
        return self._bridge.downloadDirFromList(
            file_list_id, dir_path, download_to
        )

    def close_file_list(self, file_list_id: str) -> None:
        """Close an opened file list."""
        self._bridge.closeFileList(file_list_id)

    def close_all_file_lists(self) -> None:
        """Close all opened file lists."""
        self._bridge.closeAllFileLists()

    # ------------------------------------------------------------------
    # Sharing
    # ------------------------------------------------------------------

    def add_share(self, real_path: str, virtual_name: str) -> bool:
        """Add a directory to share."""
        return self._bridge.addShareDir(real_path, virtual_name)

    def remove_share(self, real_path: str) -> bool:
        """Remove a directory from share."""
        return self._bridge.removeShareDir(real_path)

    def rename_share(self, real_path: str, new_name: str) -> bool:
        """Rename a shared directory's virtual name."""
        return self._bridge.renameShareDir(real_path, new_name)

    def list_shares(self) -> list:
        """List all shared directories."""
        return list(self._bridge.listShare())

    def refresh_share(self) -> None:
        """Refresh shared file lists."""
        self._bridge.refreshShare()

    @property
    def share_size(self) -> int:
        """Total share size in bytes."""
        return self._bridge.getShareSize()

    @property
    def shared_files(self) -> int:
        """Total number of shared files."""
        return self._bridge.getSharedFileCount()

    # ------------------------------------------------------------------
    # Transfers
    # ------------------------------------------------------------------

    @property
    def transfer_stats(self) -> Any:
        """Get aggregate transfer statistics."""
        return self._bridge.getTransferStats()

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------

    @property
    def hash_status(self) -> Any:
        """Get file hashing status."""
        return self._bridge.getHashStatus()

    def pause_hashing(self, pause: bool = True) -> None:
        """Pause or resume file hashing."""
        self._bridge.pauseHashing(pause)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def get_setting(self, name: str) -> str:
        """Get a DC client setting by name."""
        return self._bridge.getSetting(name)

    def set_setting(self, name: str, value: str) -> None:
        """Set a DC client setting."""
        self._bridge.setSetting(name, value)

    def reload_config(self) -> None:
        """Reload configuration from disk."""
        self._bridge.reloadConfig()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "DCClient":
        if not self._initialized:
            self.initialize()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.shutdown()

    def __repr__(self) -> str:
        state = "initialized" if self._initialized else "not initialized"
        return f"DCClient({self._config_dir!r}, {state})"
