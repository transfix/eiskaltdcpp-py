"""
Pydantic models for the eiskaltdcpp-py REST API.

Defines request/response schemas for authentication, hub management,
search, downloads, shares, and settings.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================================
# Auth / User models
# ============================================================================

class UserRole(str, Enum):
    """User access levels."""
    admin = "admin"
    readonly = "readonly"


class TokenRequest(BaseModel):
    """Login request — username + password."""
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    """Login response — JWT access token."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Token lifetime in seconds")
    role: UserRole


class UserCreate(BaseModel):
    """Create a new API user (admin only)."""
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=8, max_length=256)
    role: UserRole = UserRole.readonly


class UserUpdate(BaseModel):
    """Update an existing API user (admin only)."""
    password: Optional[str] = Field(None, min_length=8, max_length=256)
    role: Optional[UserRole] = None


class UserInfo(BaseModel):
    """Public user information (password excluded)."""
    username: str
    role: UserRole
    created_at: datetime
    last_login: Optional[datetime] = None


class UserList(BaseModel):
    """List of API users."""
    users: list[UserInfo]
    total: int


# ============================================================================
# Hub models
# ============================================================================

class HubConnect(BaseModel):
    """Request to connect to a hub."""
    url: str = Field(..., description="Hub URL (e.g. dchub://example.com:411)")
    encoding: str = Field("", description="Character encoding (default UTF-8)")


class HubDisconnect(BaseModel):
    """Request to disconnect from a hub."""
    url: str


class HubStatus(BaseModel):
    """Status of a single hub connection."""
    url: str
    name: str = ""
    connected: bool = False
    user_count: int = 0


class HubList(BaseModel):
    """List of hub connections."""
    hubs: list[HubStatus]
    total: int


# ============================================================================
# Chat models
# ============================================================================

class ChatMessage(BaseModel):
    """Send a chat message."""
    hub_url: str
    message: str = Field(..., min_length=1)


class PrivateMessage(BaseModel):
    """Send a private message."""
    hub_url: str
    nick: str
    message: str = Field(..., min_length=1)


class ChatHistory(BaseModel):
    """Chat history response."""
    hub_url: str
    messages: list[str]


# ============================================================================
# User (DC user on hub) models
# ============================================================================

class DCUserInfo(BaseModel):
    """Information about a DC user on a hub."""
    nick: str
    share_size: int = 0
    description: str = ""
    tag: str = ""
    connection: str = ""
    email: str = ""
    hub_url: str = ""


class DCUserList(BaseModel):
    """List of DC users on a hub."""
    hub_url: str
    users: list[DCUserInfo]
    total: int


# ============================================================================
# Search models
# ============================================================================

class SearchRequest(BaseModel):
    """Start a search."""
    query: str = Field(..., min_length=1)
    file_type: int = Field(0, ge=0, le=8,
                           description="0=any,1=audio,2=compressed,"
                                       "3=document,4=exe,5=picture,"
                                       "6=video,7=folder,8=TTH")
    size_mode: int = Field(0, ge=0, le=3,
                           description="0=any,1=at least,2=at most,3=exact")
    size: int = Field(0, ge=0, description="Size filter in bytes")
    hub_url: str = Field("", description="Search only this hub (empty=all)")


class SearchResult(BaseModel):
    """A single search result."""
    hub_url: str
    file: str
    size: int
    free_slots: int
    total_slots: int
    tth: str
    nick: str
    is_directory: bool


class SearchResults(BaseModel):
    """Accumulated search results."""
    results: list[SearchResult]
    total: int


# ============================================================================
# Queue / Download models
# ============================================================================

class QueueAdd(BaseModel):
    """Add a file to the download queue."""
    directory: str
    name: str
    size: int = Field(..., ge=0)
    tth: str
    hub_url: str = ""
    nick: str = ""


class MagnetAdd(BaseModel):
    """Add a magnet link to the download queue."""
    magnet: str
    download_dir: str = ""


class QueueItemInfo(BaseModel):
    """Information about a queued download."""
    target: str
    size: int = 0
    downloaded: int = 0
    priority: int = 0
    tth: str = ""


class QueueList(BaseModel):
    """Download queue listing."""
    items: list[QueueItemInfo]
    total: int


class PriorityUpdate(BaseModel):
    """Update download priority."""
    priority: int = Field(..., ge=0, le=5,
                          description="0=paused,1=lowest..5=highest")


# ============================================================================
# Share models
# ============================================================================

class ShareAdd(BaseModel):
    """Add a directory to share."""
    real_path: str
    virtual_name: str


class ShareInfo(BaseModel):
    """Information about a shared directory."""
    real_path: str
    virtual_name: str
    size: int = 0


class ShareList(BaseModel):
    """List of shared directories."""
    shares: list[ShareInfo]
    total: int
    total_size: int = 0
    total_files: int = 0


# ============================================================================
# Settings models
# ============================================================================

class SettingGet(BaseModel):
    """A single setting value."""
    name: str
    value: str


class SettingSet(BaseModel):
    """Set a setting value."""
    name: str
    value: str


class SettingsBatch(BaseModel):
    """Batch get/set settings."""
    settings: list[SettingSet]


# ============================================================================
# Transfer / Status models
# ============================================================================

class TransferStatsResponse(BaseModel):
    """Aggregate transfer statistics."""
    download_speed: int = 0
    upload_speed: int = 0
    downloaded: int = 0
    uploaded: int = 0


class HashStatusResponse(BaseModel):
    """File hashing status."""
    current_file: str = ""
    files_left: int = 0
    bytes_left: int = 0
    is_paused: bool = False


class SystemStatus(BaseModel):
    """Overall system status."""
    version: str
    initialized: bool
    connected_hubs: int
    queue_size: int
    share_size: int
    shared_files: int
    uptime_seconds: float = 0


# ============================================================================
# Generic response models
# ============================================================================

class SuccessResponse(BaseModel):
    """Generic success response."""
    ok: bool = True
    message: str = ""


class ErrorResponse(BaseModel):
    """Generic error response."""
    ok: bool = False
    error: str
    detail: str = ""
