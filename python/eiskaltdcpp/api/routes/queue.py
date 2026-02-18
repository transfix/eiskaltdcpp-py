"""
Download queue management API routes.

POST   /api/queue           — Add file to download queue (admin)
POST   /api/queue/magnet    — Add magnet link (admin)
GET    /api/queue           — List download queue (readonly+)
DELETE /api/queue/{target}  — Remove from queue (admin)
PUT    /api/queue/{target}/priority — Set priority (admin)
DELETE /api/queue           — Clear entire queue (admin)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from urllib.parse import unquote

from eiskaltdcpp.api.auth import UserRecord
from eiskaltdcpp.api.dependencies import get_dc_client, require_admin, require_readonly
from eiskaltdcpp.api.models import (
    MagnetAdd,
    PriorityUpdate,
    QueueAdd,
    QueueItemInfo,
    QueueList,
    SuccessResponse,
)

router = APIRouter(prefix="/api/queue", tags=["queue"])


def _require_client(client):
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DC client not initialized",
        )
    return client


@router.post(
    "",
    response_model=SuccessResponse,
    summary="Add file to download queue",
)
async def add_to_queue(
    body: QueueAdd,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Add a file to the download queue (admin only)."""
    client = _require_client(client)
    ok = client.download(
        body.directory, body.name, body.size, body.tth,
        hub_url=body.hub_url, nick=body.nick,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to add to queue",
        )
    return SuccessResponse(message=f"Added {body.name} to queue")


@router.post(
    "/magnet",
    response_model=SuccessResponse,
    summary="Add magnet link to queue",
)
async def add_magnet(
    body: MagnetAdd,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Add a magnet link to the download queue (admin only)."""
    client = _require_client(client)
    ok = client.download_magnet(body.magnet, body.download_dir)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to add magnet link",
        )
    return SuccessResponse(message="Magnet link added to queue")


@router.get(
    "",
    response_model=QueueList,
    summary="List download queue",
)
async def list_queue(
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> QueueList:
    """List all items in the download queue (any authenticated user)."""
    client = _require_client(client)
    raw = client.list_queue()
    items = []
    for q in raw:
        items.append(QueueItemInfo(
            target=getattr(q, "target", str(q)),
            size=getattr(q, "size", 0),
            downloaded=getattr(q, "downloadedBytes", 0),
            priority=getattr(q, "priority", 0),
            tth=getattr(q, "tth", ""),
        ))
    return QueueList(items=items, total=len(items))


@router.delete(
    "",
    response_model=SuccessResponse,
    summary="Clear entire download queue",
)
async def clear_queue(
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Clear the entire download queue (admin only)."""
    client = _require_client(client)
    client.clear_queue()
    return SuccessResponse(message="Queue cleared")


@router.delete(
    "/{target:path}",
    response_model=SuccessResponse,
    summary="Remove item from queue",
)
async def remove_from_queue(
    target: str,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Remove a specific item from the download queue (admin only)."""
    client = _require_client(client)
    decoded = unquote(target)
    client.remove_download(decoded)
    return SuccessResponse(message=f"Removed {decoded} from queue")


@router.put(
    "/{target:path}/priority",
    response_model=SuccessResponse,
    summary="Set download priority",
)
async def set_priority(
    target: str,
    body: PriorityUpdate,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Set download priority for a queue item (admin only)."""
    client = _require_client(client)
    decoded = unquote(target)
    client._sync_client.set_priority(decoded, body.priority)
    return SuccessResponse(
        message=f"Priority set to {body.priority} for {decoded}"
    )
