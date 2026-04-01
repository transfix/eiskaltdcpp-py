"""
Unified async protocol for DC client implementations.

Defines ``DCClientProtocol`` — the abstract interface that **both**
``AsyncDCClient`` (local SWIG) and ``RemoteDCClient`` (REST/WebSocket)
implement.  UI code should target this protocol so it works identically
with a local or remote backend:

    from eiskaltdcpp.protocol import DCClientProtocol

    async def show_users(client: DCClientProtocol, hub: str):
        users = await client.get_users(hub)
        for u in users:
            print(u.nick)

The protocol is a ``runtime_checkable`` ``Protocol`` so you can use
``isinstance(obj, DCClientProtocol)`` at runtime.

Every method in the protocol is ``async``.  ``AsyncDCClient`` wraps its
synchronous C++ calls in coroutines where needed.  ``RemoteDCClient``
naturally returns coroutines from HTTP calls.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Protocol, runtime_checkable


@runtime_checkable
class DCClientProtocol(Protocol):
    """Unified async interface for local and remote DC clients.

    All mutating operations and queries are async.  Properties that are
    cheap and always available (``is_initialized``, ``version``) are
    synchronous.
    """

    # ── Lifecycle ────────────────────────────────────────────────────

    @property
    def is_initialized(self) -> bool: ...

    @property
    def version(self) -> str: ...

    async def shutdown(self) -> None: ...

    # ── Hub connections ──────────────────────────────────────────────

    async def connect(self, url: str, encoding: str = "") -> None: ...

    async def disconnect(self, url: str) -> None: ...

    async def list_hubs(self) -> list: ...

    async def is_connected(self, url: str) -> bool: ...

    # ── Chat & messaging ─────────────────────────────────────────────

    async def send_message(self, hub_url: str, message: str) -> None: ...

    async def send_pm(
        self, hub_url: str, nick: str, message: str
    ) -> None: ...

    async def get_chat_history(
        self, hub_url: str, max_lines: int = 100
    ) -> list[str]: ...

    # ── Users ────────────────────────────────────────────────────────

    async def get_users(self, hub_url: str) -> list: ...

    # ── Search ───────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        file_type: int = 0,
        size_mode: int = 0,
        size: int = 0,
        hub_url: str = "",
    ) -> bool: ...

    async def get_search_results(self, hub_url: str = "") -> list: ...

    async def clear_search_results(self, hub_url: str = "") -> None: ...

    # ── Download queue ───────────────────────────────────────────────

    async def download(
        self, directory: str, name: str, size: int, tth: str
    ) -> bool: ...

    async def download_magnet(
        self, magnet: str, download_dir: str = ""
    ) -> bool: ...

    async def remove_download(self, target: str) -> None: ...

    async def set_priority(
        self, target: str, priority: int
    ) -> None: ...

    async def list_queue(self) -> list: ...

    async def clear_queue(self) -> None: ...

    # ── Sharing ──────────────────────────────────────────────────────

    async def add_share(
        self, real_path: str, virtual_name: str
    ) -> bool: ...

    async def remove_share(self, real_path: str) -> bool: ...

    async def list_shares(self) -> list: ...

    async def refresh_share(self) -> None: ...

    async def get_share_size(self) -> int: ...

    async def get_shared_files(self) -> int: ...

    # ── Settings ─────────────────────────────────────────────────────

    async def get_setting(self, name: str) -> str: ...

    async def set_setting(self, name: str, value: str) -> None: ...

    async def reload_config(self) -> None: ...

    async def start_networking(self) -> None: ...

    # ── Transfers & hashing ──────────────────────────────────────────

    async def get_transfer_stats(self) -> Any: ...

    async def get_hash_status(self) -> Any: ...

    async def pause_hashing(self, pause: bool = True) -> None: ...

    # ── Lua scripting ────────────────────────────────────────────────

    async def lua_is_available(self) -> bool: ...

    async def lua_eval(self, code: str) -> None: ...

    async def lua_eval_file(self, path: str) -> None: ...

    async def lua_get_scripts_path(self) -> str: ...

    async def lua_list_scripts(self) -> list[str]: ...

    # ── Events ───────────────────────────────────────────────────────

    def on(
        self, event: str, handler: Optional[Callable[..., Any]] = None
    ) -> Callable: ...

    def off(self, event: str, handler: Callable[..., Any]) -> None: ...
