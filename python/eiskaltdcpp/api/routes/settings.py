"""
DC client settings API routes.

GET  /api/settings/{name} — Get a setting (readonly+)
PUT  /api/settings/{name} — Set a setting (admin)
POST /api/settings/batch  — Set multiple settings (admin)
POST /api/settings/reload — Reload configuration from disk (admin)
POST /api/settings/networking — Rebind network listeners (admin)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from eiskaltdcpp.api.auth import UserRecord
from eiskaltdcpp.api.dependencies import get_dc_client, require_admin, require_readonly
from eiskaltdcpp.api.models import (
    SettingGet,
    SettingSet,
    SettingsBatch,
    SuccessResponse,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _require_client(client):
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DC client not initialized",
        )
    return client


@router.get(
    "/{name}",
    response_model=SettingGet,
    summary="Get a DC client setting",
)
async def get_setting(
    name: str,
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> SettingGet:
    """Get a DC client setting by name (any authenticated user)."""
    client = _require_client(client)
    value = client.get_setting(name)
    return SettingGet(name=name, value=value)


@router.put(
    "/{name}",
    response_model=SuccessResponse,
    summary="Set a DC client setting",
)
async def set_setting(
    name: str,
    body: SettingSet,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Set a DC client setting (admin only)."""
    client = _require_client(client)
    client.set_setting(name, body.value)
    return SuccessResponse(message=f"Setting '{name}' updated")


@router.post(
    "/batch",
    response_model=SuccessResponse,
    summary="Set multiple settings",
)
async def batch_settings(
    body: SettingsBatch,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Set multiple DC client settings at once (admin only)."""
    client = _require_client(client)
    for s in body.settings:
        client.set_setting(s.name, s.value)
    return SuccessResponse(
        message=f"Updated {len(body.settings)} settings"
    )


@router.post(
    "/reload",
    response_model=SuccessResponse,
    summary="Reload configuration from disk",
)
async def reload_config(
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Reload DC client configuration from disk (admin only)."""
    client = _require_client(client)
    client._sync_client.reload_config()
    return SuccessResponse(message="Configuration reloaded")


@router.post(
    "/networking",
    response_model=SuccessResponse,
    summary="Rebind network listeners",
)
async def restart_networking(
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Rebind incoming connection listeners (admin only).

    Call after changing connection settings (ports, external IP, etc.)
    """
    client = _require_client(client)
    client.start_networking()
    return SuccessResponse(message="Networking restarted")
