"""
Hub connection management API routes.

POST   /api/hubs/connect    — Connect to a hub (admin)
POST   /api/hubs/disconnect — Disconnect from a hub (admin)
GET    /api/hubs            — List connected hubs (readonly+)
GET    /api/hubs/{url}/users — List users on a hub (readonly+)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from urllib.parse import unquote

from eiskaltdcpp.api.auth import UserRecord
from eiskaltdcpp.api.dependencies import get_dc_client, require_admin, require_readonly
from eiskaltdcpp.api.models import (
    DCUserInfo,
    DCUserList,
    ErrorResponse,
    HubConnect,
    HubDisconnect,
    HubList,
    HubStatus,
    SuccessResponse,
)

router = APIRouter(prefix="/api/hubs", tags=["hubs"])


def _require_client(client):
    """Raise 503 if DC client is not available."""
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DC client not initialized",
        )
    return client


@router.post(
    "/connect",
    response_model=SuccessResponse,
    summary="Connect to a hub",
)
async def connect_hub(
    body: HubConnect,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Connect to a DC hub (admin only)."""
    client = _require_client(client)
    await client.connect(body.url, body.encoding)
    return SuccessResponse(message=f"Connecting to {body.url}")


@router.post(
    "/disconnect",
    response_model=SuccessResponse,
    summary="Disconnect from a hub",
)
async def disconnect_hub(
    body: HubDisconnect,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Disconnect from a DC hub (admin only)."""
    client = _require_client(client)
    await client.disconnect(body.url)
    return SuccessResponse(message=f"Disconnecting from {body.url}")


@router.get(
    "",
    response_model=HubList,
    summary="List connected hubs",
)
async def list_hubs(
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> HubList:
    """List all connected hubs (any authenticated user)."""
    client = _require_client(client)
    raw_hubs = client.list_hubs()
    hubs = []
    for h in raw_hubs:
        hubs.append(HubStatus(
            url=getattr(h, "url", str(h)),
            name=getattr(h, "name", ""),
            connected=getattr(h, "connected", True),
            user_count=getattr(h, "userCount", 0),
        ))
    return HubList(hubs=hubs, total=len(hubs))


@router.get(
    "/users",
    response_model=DCUserList,
    summary="List users on a hub",
)
async def list_hub_users(
    hub_url: str,
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> DCUserList:
    """List users on a specific hub (any authenticated user).

    Pass ``hub_url`` as a query parameter.
    """
    client = _require_client(client)
    url = unquote(hub_url)
    raw_users = client.get_users(url)
    users = []
    for u in raw_users:
        users.append(DCUserInfo(
            nick=getattr(u, "nick", str(u)),
            share_size=getattr(u, "shareSize", 0),
            description=getattr(u, "description", ""),
            tag=getattr(u, "tag", ""),
            connection=getattr(u, "connection", ""),
            email=getattr(u, "email", ""),
            hub_url=url,
        ))
    return DCUserList(hub_url=url, users=users, total=len(users))
