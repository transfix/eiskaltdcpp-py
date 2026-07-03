"""
Connectivity and port mapping API routes.

GET  /api/connectivity/status        — Connection detection status
POST /api/connectivity/detect        — Run connection detection
POST /api/connectivity/setup         — Apply changed settings
GET  /api/connectivity/mapping       — Port mapping status
POST /api/connectivity/mapping/open  — Open ports (UPnP)
POST /api/connectivity/mapping/close — Close ports
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from eiskaltdcpp.api.auth import UserRecord
from eiskaltdcpp.api.dependencies import get_dc_client, require_admin, require_readonly
from eiskaltdcpp.api.models import ConnectivityStatus, SuccessResponse

router = APIRouter(prefix="/api/connectivity", tags=["connectivity"])


def _require_client(client):
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DC client not initialized",
        )
    return client


@router.get(
    "/status",
    response_model=ConnectivityStatus,
    summary="Get connection detection status",
)
async def get_connectivity_status(
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> ConnectivityStatus:
    client = _require_client(client)
    cm = client.connectivity
    mm = client.connectivity  # MappingManager accessed via mapping_manager
    return ConnectivityStatus(
        running=cm.isRunning(),
        mapping_opened=False,  # MappingManager.getOpened() returns string
    )


@router.post(
    "/detect",
    response_model=SuccessResponse,
    summary="Run connection detection",
)
async def detect_connection(
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    client = _require_client(client)
    client.connectivity.detectConnection()
    return SuccessResponse(message="Connection detection started")


@router.post(
    "/setup",
    response_model=SuccessResponse,
    summary="Apply changed connection settings",
)
async def setup_connectivity(
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    client = _require_client(client)
    client.connectivity.setup(True)
    return SuccessResponse(message="Connection settings applied")
