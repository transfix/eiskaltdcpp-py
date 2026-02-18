"""
Share management API routes.

POST   /api/shares          — Add share directory (admin)
DELETE /api/shares           — Remove share directory (admin)
GET    /api/shares           — List shared directories (readonly+)
POST   /api/shares/refresh   — Refresh file hash list (admin)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from eiskaltdcpp.api.auth import UserRecord
from eiskaltdcpp.api.dependencies import get_dc_client, require_admin, require_readonly
from eiskaltdcpp.api.models import (
    ShareAdd,
    ShareInfo,
    ShareList,
    SuccessResponse,
)

router = APIRouter(prefix="/api/shares", tags=["shares"])


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
    summary="Add a directory to share",
)
async def add_share(
    body: ShareAdd,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Add a directory to share (admin only)."""
    client = _require_client(client)
    ok = client.add_share(body.real_path, body.virtual_name)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to add share: {body.real_path}",
        )
    return SuccessResponse(
        message=f"Shared {body.real_path} as '{body.virtual_name}'"
    )


@router.delete(
    "",
    response_model=SuccessResponse,
    summary="Remove a directory from share",
)
async def remove_share(
    real_path: str,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Remove a directory from share (admin only)."""
    client = _require_client(client)
    ok = client.remove_share(real_path)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to remove share: {real_path}",
        )
    return SuccessResponse(message=f"Unshared {real_path}")


@router.get(
    "",
    response_model=ShareList,
    summary="List shared directories",
)
async def list_shares(
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> ShareList:
    """List all shared directories (any authenticated user)."""
    client = _require_client(client)
    raw = client.list_shares()
    shares = []
    for s in raw:
        shares.append(ShareInfo(
            real_path=getattr(s, "realPath", str(s)),
            virtual_name=getattr(s, "virtualName", ""),
            size=getattr(s, "size", 0),
        ))
    return ShareList(
        shares=shares,
        total=len(shares),
        total_size=client.share_size,
        total_files=client.shared_files,
    )


@router.post(
    "/refresh",
    response_model=SuccessResponse,
    summary="Refresh shared file lists",
)
async def refresh_share(
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Refresh shared file hash lists (admin only)."""
    client = _require_client(client)
    client.refresh_share()
    return SuccessResponse(message="Share refresh started")
