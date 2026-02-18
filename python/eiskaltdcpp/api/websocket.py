"""
WebSocket manager for real-time event streaming.

Provides:
- ConnectionManager: tracks active WebSocket connections per channel
- Event bridge: forwards AsyncDCClient events to subscribed WebSocket clients
- Channels: events, chat, search, transfers, hubs

Clients authenticate via a JWT token passed as a query parameter.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from starlette.websockets import WebSocketState

from eiskaltdcpp.api.auth import AuthManager, UserRecord
from eiskaltdcpp.api.dependencies import get_auth_manager, get_dc_client
from eiskaltdcpp.api.models import UserRole

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


# ============================================================================
# Channel definitions
# ============================================================================

class Channel(str, Enum):
    """WebSocket subscription channels."""
    events = "events"      # All DC client events
    chat = "chat"          # Chat messages only
    search = "search"      # Search results only
    transfers = "transfers" # Transfer/queue events
    hubs = "hubs"          # Hub connection events
    status = "status"      # Periodic status updates


# Event type → channel mapping
EVENT_CHANNELS: dict[str, set[Channel]] = {
    # Hub events
    "hub_connecting": {Channel.hubs, Channel.events},
    "hub_connected": {Channel.hubs, Channel.events},
    "hub_disconnected": {Channel.hubs, Channel.events},
    "hub_redirect": {Channel.hubs, Channel.events},
    "hub_get_password": {Channel.hubs, Channel.events},
    "hub_updated": {Channel.hubs, Channel.events},
    "hub_nick_taken": {Channel.hubs, Channel.events},
    "hub_full": {Channel.hubs, Channel.events},
    # Chat events
    "chat_message": {Channel.chat, Channel.events},
    "private_message": {Channel.chat, Channel.events},
    "status_message": {Channel.chat, Channel.events},
    # User events
    "user_connected": {Channel.hubs, Channel.events},
    "user_disconnected": {Channel.hubs, Channel.events},
    "user_updated": {Channel.hubs, Channel.events},
    # Search events
    "search_result": {Channel.search, Channel.events},
    # Queue events
    "queue_item_added": {Channel.transfers, Channel.events},
    "queue_item_finished": {Channel.transfers, Channel.events},
    "queue_item_removed": {Channel.transfers, Channel.events},
    # Transfer events
    "download_starting": {Channel.transfers, Channel.events},
    "download_complete": {Channel.transfers, Channel.events},
    "download_failed": {Channel.transfers, Channel.events},
    "upload_starting": {Channel.transfers, Channel.events},
    "upload_complete": {Channel.transfers, Channel.events},
    # Hash events
    "hash_progress": {Channel.transfers, Channel.events},
}

# Argument names for each event type (for serialization)
EVENT_ARG_NAMES: dict[str, tuple[str, ...]] = {
    "hub_connecting": ("hub_url",),
    "hub_connected": ("hub_url", "hub_name"),
    "hub_disconnected": ("hub_url", "reason"),
    "hub_redirect": ("hub_url", "new_url"),
    "hub_get_password": ("hub_url",),
    "hub_updated": ("hub_url", "hub_name"),
    "hub_nick_taken": ("hub_url",),
    "hub_full": ("hub_url",),
    "chat_message": ("hub_url", "nick", "message", "third_person"),
    "private_message": ("hub_url", "from_nick", "to_nick", "message"),
    "status_message": ("hub_url", "message"),
    "user_connected": ("hub_url", "nick"),
    "user_disconnected": ("hub_url", "nick"),
    "user_updated": ("hub_url", "nick"),
    "search_result": ("hub_url", "file", "size", "free_slots", "total_slots",
                       "tth", "nick", "is_directory"),
    "queue_item_added": ("target", "size", "tth"),
    "queue_item_finished": ("target", "size"),
    "queue_item_removed": ("target",),
    "download_starting": ("target", "nick", "size"),
    "download_complete": ("target", "nick", "size", "speed"),
    "download_failed": ("target", "reason"),
    "upload_starting": ("file", "nick", "size"),
    "upload_complete": ("file", "nick", "size"),
    "hash_progress": ("current_file", "files_left", "bytes_left"),
}


def _serialize_event(event_type: str, args: tuple) -> dict:
    """Convert an event and its positional args into a JSON-safe dict."""
    names = EVENT_ARG_NAMES.get(event_type, ())
    data = {}
    for i, name in enumerate(names):
        if i < len(args):
            data[name] = args[i]
    return {
        "type": "event",
        "event": event_type,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================================
# Connection Manager
# ============================================================================

class _ClientConnection:
    """Track a single WebSocket client with its subscriptions."""
    __slots__ = ("ws", "user", "channels", "connected_at")

    def __init__(self, ws: WebSocket, user: UserRecord,
                 channels: set[Channel]) -> None:
        self.ws = ws
        self.user = user
        self.channels = channels
        self.connected_at = time.time()


class ConnectionManager:
    """
    Manages WebSocket connections and broadcasts events to subscribers.

    Thread-safe — can be called from the DC client event dispatch thread.
    """

    def __init__(self) -> None:
        self._connections: list[_ClientConnection] = []
        self._lock = asyncio.Lock()
        self._event_stream_task: Optional[asyncio.Task] = None
        self._status_task: Optional[asyncio.Task] = None

    async def connect(self, ws: WebSocket, user: UserRecord,
                      channels: set[Channel]) -> _ClientConnection:
        """Accept a WebSocket and register it."""
        await ws.accept()
        conn = _ClientConnection(ws, user, channels)
        async with self._lock:
            self._connections.append(conn)
        logger.info("WS connected: user=%s channels=%s (total=%d)",
                    user.username, [c.value for c in channels],
                    len(self._connections))
        return conn

    async def disconnect(self, conn: _ClientConnection) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            if conn in self._connections:
                self._connections.remove(conn)
        logger.info("WS disconnected: user=%s (total=%d)",
                    conn.user.username, len(self._connections))

    async def broadcast(self, message: dict, channels: set[Channel],
                        require_admin: bool = False) -> None:
        """Send a message to all connections subscribed to any of the channels."""
        text = json.dumps(message)
        async with self._lock:
            targets = list(self._connections)

        dead: list[_ClientConnection] = []
        for conn in targets:
            if not conn.channels.intersection(channels):
                continue
            if require_admin and conn.user.role != UserRole.admin:
                continue
            try:
                if conn.ws.client_state == WebSocketState.CONNECTED:
                    await conn.ws.send_text(text)
            except Exception:
                dead.append(conn)

        if dead:
            async with self._lock:
                for d in dead:
                    if d in self._connections:
                        self._connections.remove(d)

    async def send_personal(self, conn: _ClientConnection,
                            message: dict) -> None:
        """Send a message to a single connection."""
        try:
            if conn.ws.client_state == WebSocketState.CONNECTED:
                await conn.ws.send_text(json.dumps(message))
        except Exception:
            pass

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def start_event_bridge(self, dc_client) -> None:
        """
        Start listening to DC client events and forwarding to WebSocket clients.
        Must be called from an async context.
        """
        if self._event_stream_task is not None:
            return
        self._event_stream_task = asyncio.create_task(
            self._event_bridge_loop(dc_client)
        )
        self._status_task = asyncio.create_task(
            self._status_broadcast_loop(dc_client)
        )
        logger.info("WebSocket event bridge started")

    def stop_event_bridge(self) -> None:
        """Stop the event bridge tasks."""
        if self._event_stream_task:
            self._event_stream_task.cancel()
            self._event_stream_task = None
        if self._status_task:
            self._status_task.cancel()
            self._status_task = None

    async def _event_bridge_loop(self, dc_client) -> None:
        """Read from the DC client event stream and broadcast to WebSockets."""
        try:
            stream = dc_client.events(maxsize=5000)
            async for event_name, args in stream:
                channels = EVENT_CHANNELS.get(event_name, {Channel.events})
                message = _serialize_event(event_name, args)
                await self.broadcast(message, channels)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Event bridge loop error")

    async def _status_broadcast_loop(self, dc_client) -> None:
        """Periodically broadcast system status to status channel subscribers."""
        try:
            while True:
                await asyncio.sleep(5)
                try:
                    hubs = dc_client.list_hubs()
                    queue = dc_client.list_queue()
                    stats = dc_client.transfer_stats
                    message = {
                        "type": "status",
                        "data": {
                            "connected_hubs": len(hubs),
                            "queue_size": len(queue),
                            "share_size": dc_client.share_size,
                            "shared_files": dc_client.shared_files,
                            "download_speed": getattr(stats, "downloadSpeed", 0),
                            "upload_speed": getattr(stats, "uploadSpeed", 0),
                        },
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    await self.broadcast(message, {Channel.status, Channel.events})
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass


# Global connection manager
ws_manager = ConnectionManager()


# ============================================================================
# WebSocket authentication
# ============================================================================

async def _authenticate_ws(
    ws: WebSocket,
    token: str,
    auth: AuthManager,
) -> Optional[UserRecord]:
    """Validate a JWT token for WebSocket auth. Returns user or None."""
    if not token:
        return None
    payload = auth.verify_token(token)
    if payload is None:
        return None
    username = payload.get("sub")
    user = auth.user_store.get_user(username)
    return user


# ============================================================================
# WebSocket endpoint
# ============================================================================

@router.websocket("/ws/events")
async def websocket_events(
    ws: WebSocket,
    token: str = Query(""),
    channels: str = Query("events"),
):
    """
    WebSocket endpoint for real-time event streaming.

    Query params:
        token: JWT bearer token for authentication
        channels: Comma-separated list of channels to subscribe to.
                  Options: events, chat, search, transfers, hubs, status

    Messages sent (server → client):
        {"type": "event", "event": "<event_type>", "data": {...}, "timestamp": "..."}
        {"type": "status", "data": {...}, "timestamp": "..."}
        {"type": "pong"}
        {"type": "error", "message": "..."}

    Messages received (client → server):
        {"type": "ping"}
        {"type": "subscribe", "channels": ["chat", "search"]}
        {"type": "unsubscribe", "channels": ["search"]}
    """
    from eiskaltdcpp.api.dependencies import _auth_manager, _dc_client

    if _auth_manager is None:
        await ws.close(code=1008, reason="Server not configured")
        return

    # Authenticate
    user = await _authenticate_ws(ws, token, _auth_manager)
    if user is None:
        await ws.close(code=4001, reason="Invalid or missing token")
        return

    # Parse requested channels
    requested = set()
    for ch_name in channels.split(","):
        ch_name = ch_name.strip().lower()
        try:
            requested.add(Channel(ch_name))
        except ValueError:
            pass
    if not requested:
        requested = {Channel.events}

    # Restrict admin-only channels for readonly users
    # (currently all channels are available to all authenticated users)

    conn = await ws_manager.connect(ws, user, requested)

    # Start event bridge if DC client available and not already running
    if _dc_client is not None:
        ws_manager.start_event_bridge(_dc_client)

    # Send welcome message
    await ws_manager.send_personal(conn, {
        "type": "connected",
        "user": user.username,
        "role": user.role.value,
        "channels": [c.value for c in requested],
    })

    try:
        while True:
            try:
                raw = await ws.receive_text()
            except WebSocketDisconnect:
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws_manager.send_personal(conn, {
                    "type": "error",
                    "message": "Invalid JSON",
                })
                continue

            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await ws_manager.send_personal(conn, {"type": "pong"})

            elif msg_type == "subscribe":
                for ch_name in msg.get("channels", []):
                    try:
                        conn.channels.add(Channel(ch_name))
                    except ValueError:
                        pass
                await ws_manager.send_personal(conn, {
                    "type": "subscribed",
                    "channels": [c.value for c in conn.channels],
                })

            elif msg_type == "unsubscribe":
                for ch_name in msg.get("channels", []):
                    try:
                        conn.channels.discard(Channel(ch_name))
                    except ValueError:
                        pass
                await ws_manager.send_personal(conn, {
                    "type": "subscribed",
                    "channels": [c.value for c in conn.channels],
                })

            else:
                await ws_manager.send_personal(conn, {
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                })

    except Exception:
        logger.exception("WebSocket error for user %s", user.username)
    finally:
        await ws_manager.disconnect(conn)
