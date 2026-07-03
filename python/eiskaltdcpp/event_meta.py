"""
Shared event metadata constants.

Defines ``EVENT_ARG_NAMES`` — the canonical mapping from event type to its
positional argument names.  This module is intentionally dependency-free
so it can be imported by both the server (``api.websocket``) and the
standalone client (``api.client``) without pulling in FastAPI, SWIG, etc.
"""
from __future__ import annotations

# Argument names for each event type (positional order).
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
