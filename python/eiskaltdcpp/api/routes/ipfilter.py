"""
IP filter API routes.

POST   /api/ipfilter/check  — Test an IP against filter rules
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from eiskaltdcpp.api.auth import UserRecord
from eiskaltdcpp.api.dependencies import get_dc_client, require_admin, require_readonly
from eiskaltdcpp.api.models import IPFilterCheck, IPFilterCheckResult, SuccessResponse

router = APIRouter(prefix="/api/ipfilter", tags=["ipfilter"])


def _require_client(client):
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DC client not initialized",
        )
    return client


@router.post(
    "/check",
    response_model=IPFilterCheckResult,
    summary="Check an IP against filter rules",
)
async def check_ip(
    body: IPFilterCheck,
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> IPFilterCheckResult:
    client = _require_client(client)
    ipf = client.ip_filter
    allowed = ipf.OK(body.ip, body.direction)
    return IPFilterCheckResult(ip=body.ip, allowed=allowed)
