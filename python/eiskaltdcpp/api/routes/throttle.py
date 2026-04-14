"""
Bandwidth throttle API routes.

GET /api/throttle  — Get current bandwidth limits
PUT /api/throttle  — Set bandwidth limits
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from eiskaltdcpp.api.auth import UserRecord
from eiskaltdcpp.api.dependencies import get_dc_client, require_admin, require_readonly
from eiskaltdcpp.api.models import SuccessResponse, ThrottleStatus, ThrottleUpdate

router = APIRouter(prefix="/api/throttle", tags=["throttle"])


def _require_client(client):
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DC client not initialized",
        )
    return client


@router.get(
    "",
    response_model=ThrottleStatus,
    summary="Get current bandwidth limits",
)
async def get_throttle(
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> ThrottleStatus:
    client = _require_client(client)
    tm = client.throttle
    return ThrottleStatus(
        upload_limit=tm.getUpLimit(),
        download_limit=tm.getDownLimit(),
    )


@router.put(
    "",
    response_model=SuccessResponse,
    summary="Set bandwidth limits",
)
async def set_throttle(
    body: ThrottleUpdate,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    client = _require_client(client)
    sm = client.settings
    from eiskaltdcpp import dc_core
    if body.upload_limit is not None:
        sm.set(dc_core.SettingsManager.MAX_UPLOAD_SPEED_MAIN, body.upload_limit)
    if body.download_limit is not None:
        sm.set(dc_core.SettingsManager.MAX_DOWNLOAD_SPEED_MAIN, body.download_limit)
    return SuccessResponse(message="Bandwidth limits updated")
