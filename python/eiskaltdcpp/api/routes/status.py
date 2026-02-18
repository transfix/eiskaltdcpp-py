"""
System status and health API routes.

GET /api/status         — System status overview (readonly+)
GET /api/status/transfers — Transfer statistics (readonly+)
GET /api/status/hashing  — Hashing status (readonly+)
POST /api/status/hashing/pause — Pause/resume hashing (admin)
POST /api/shutdown       — Graceful server shutdown (admin)
GET /api/health          — Health check (public, no auth)
"""
from __future__ import annotations

import logging
import os
import signal
import time

from fastapi import APIRouter, Depends, HTTPException, status

from eiskaltdcpp.api.auth import UserRecord
from eiskaltdcpp.api.dependencies import (
    get_dc_client,
    get_start_time,
    require_admin,
    require_readonly,
)
from eiskaltdcpp.api.models import (
    HashStatusResponse,
    SuccessResponse,
    SystemStatus,
    TransferStatsResponse,
)

router = APIRouter(tags=["status"])


def _require_client(client):
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DC client not initialized",
        )
    return client


@router.get(
    "/api/health",
    response_model=SuccessResponse,
    summary="Health check",
)
async def health_check() -> SuccessResponse:
    """Health check endpoint (no authentication required)."""
    return SuccessResponse(message="ok")


@router.get(
    "/api/status",
    response_model=SystemStatus,
    summary="System status overview",
)
async def get_status(
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
    start_time: float = Depends(get_start_time),
) -> SystemStatus:
    """Get overall system status (any authenticated user)."""
    if client is None:
        return SystemStatus(
            version="unknown",
            initialized=False,
            connected_hubs=0,
            queue_size=0,
            share_size=0,
            shared_files=0,
            uptime_seconds=time.time() - start_time if start_time else 0,
        )

    hubs = client.list_hubs()
    queue = client.list_queue()
    return SystemStatus(
        version=client.version,
        initialized=client.is_initialized,
        connected_hubs=len(hubs),
        queue_size=len(queue),
        share_size=client.share_size,
        shared_files=client.shared_files,
        uptime_seconds=time.time() - start_time if start_time else 0,
    )


@router.get(
    "/api/status/transfers",
    response_model=TransferStatsResponse,
    summary="Transfer statistics",
)
async def get_transfers(
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> TransferStatsResponse:
    """Get aggregate transfer statistics (any authenticated user)."""
    client = _require_client(client)
    stats = client.transfer_stats
    return TransferStatsResponse(
        download_speed=getattr(stats, "downloadSpeed", 0),
        upload_speed=getattr(stats, "uploadSpeed", 0),
        downloaded=getattr(stats, "downloaded", 0),
        uploaded=getattr(stats, "uploaded", 0),
    )


@router.get(
    "/api/status/hashing",
    response_model=HashStatusResponse,
    summary="File hashing status",
)
async def get_hashing(
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> HashStatusResponse:
    """Get file hashing status (any authenticated user)."""
    client = _require_client(client)
    h = client.hash_status
    return HashStatusResponse(
        current_file=getattr(h, "currentFile", ""),
        files_left=getattr(h, "filesLeft", 0),
        bytes_left=getattr(h, "bytesLeft", 0),
        is_paused=getattr(h, "isPaused", False),
    )


@router.post(
    "/api/status/hashing/pause",
    response_model=SuccessResponse,
    summary="Pause or resume file hashing",
)
async def pause_hashing(
    pause: bool = True,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Pause or resume file hashing (admin only)."""
    client = _require_client(client)
    client.pause_hashing(pause)
    action = "paused" if pause else "resumed"
    return SuccessResponse(message=f"Hashing {action}")


logger = logging.getLogger(__name__)


@router.post(
    "/api/shutdown",
    response_model=SuccessResponse,
    summary="Graceful server shutdown",
)
async def shutdown(
    _admin: UserRecord = Depends(require_admin),
) -> SuccessResponse:
    """Initiate a graceful shutdown of the server process (admin only).

    Sends SIGTERM to the running process, which triggers the daemon's
    signal handler for a clean shutdown (disconnecting hubs, saving
    state, stopping the API server).
    """
    logger.info("Shutdown requested by admin via API")
    # Send SIGTERM to ourselves — the daemon/api signal handler
    # will catch it and perform a graceful shutdown.
    os.kill(os.getpid(), signal.SIGTERM)
    return SuccessResponse(message="Shutdown initiated")
