"""
Finished transfers API routes.

GET    /api/finished/downloads — Finished download targets
DELETE /api/finished/downloads — Clear finished downloads
GET    /api/finished/uploads   — Finished upload targets
DELETE /api/finished/uploads   — Clear finished uploads
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from eiskaltdcpp.api.auth import UserRecord
from eiskaltdcpp.api.dependencies import get_dc_client, require_admin, require_readonly
from eiskaltdcpp.api.models import SuccessResponse

router = APIRouter(prefix="/api/finished", tags=["finished"])


def _require_client(client):
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DC client not initialized",
        )
    return client


@router.delete(
    "/downloads",
    response_model=SuccessResponse,
    summary="Clear finished download history",
)
async def clear_finished_downloads(
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    client = _require_client(client)
    client.finished.removeAll()
    return SuccessResponse(message="Finished download history cleared")


@router.delete(
    "/uploads",
    response_model=SuccessResponse,
    summary="Clear finished upload history",
)
async def clear_finished_uploads(
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    client = _require_client(client)
    client.finished.removeAll()
    return SuccessResponse(message="Finished upload history cleared")
