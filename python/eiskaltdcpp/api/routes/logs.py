"""
Log API routes.

GET /api/logs/path/{area}  — Get log file path for an area
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from eiskaltdcpp.api.auth import UserRecord
from eiskaltdcpp.api.dependencies import get_dc_client, require_readonly
from eiskaltdcpp.api.models import LogPath

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _require_client(client):
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DC client not initialized",
        )
    return client


@router.get(
    "/path/{area}",
    response_model=LogPath,
    summary="Get log file path for a log area",
)
async def get_log_path(
    area: int,
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> LogPath:
    client = _require_client(client)
    lm = client.logs
    path = lm.getPath(area)
    return LogPath(area=str(area), path=path)
