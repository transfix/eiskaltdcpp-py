"""
Lua scripting API routes.

GET  /api/lua/status     — Check Lua availability (readonly+)
GET  /api/lua/scripts    — List Lua scripts (readonly+)
POST /api/lua/eval       — Evaluate Lua code (admin)
POST /api/lua/eval-file  — Evaluate a Lua script file (admin)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from eiskaltdcpp.api.auth import UserRecord
from eiskaltdcpp.api.dependencies import get_dc_client, require_admin, require_readonly
from eiskaltdcpp.api.models import (
    LuaEvalFileRequest,
    LuaEvalRequest,
    LuaEvalResponse,
    LuaScriptsResponse,
    LuaStatusResponse,
)
from eiskaltdcpp.exceptions import LuaError

router = APIRouter(prefix="/api/lua", tags=["lua"])


def _require_client(client):
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DC client not initialized",
        )
    return client


@router.get(
    "/status",
    response_model=LuaStatusResponse,
    summary="Check Lua scripting availability",
)
async def lua_status(
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> LuaStatusResponse:
    """Check if Lua scripting is available in the running DC client."""
    client = _require_client(client)
    available = client.lua_is_available()
    scripts_path = client.lua_get_scripts_path() if available else ""
    return LuaStatusResponse(available=available, scripts_path=scripts_path)


@router.get(
    "/scripts",
    response_model=LuaScriptsResponse,
    summary="List Lua scripts",
)
async def lua_list_scripts(
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> LuaScriptsResponse:
    """List Lua script files in the scripts directory."""
    client = _require_client(client)
    return LuaScriptsResponse(
        scripts_path=client.lua_get_scripts_path(),
        scripts=client.lua_list_scripts(),
    )


@router.post(
    "/eval",
    response_model=LuaEvalResponse,
    summary="Evaluate Lua code",
)
async def lua_eval(
    body: LuaEvalRequest,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> LuaEvalResponse:
    """Evaluate a Lua code chunk (admin only)."""
    client = _require_client(client)
    if not client.lua_is_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lua scripting not available (library not compiled with LUA_SCRIPT)",
        )
    try:
        client.lua_eval(body.code)
        return LuaEvalResponse(ok=True, error="")
    except LuaError as exc:
        return LuaEvalResponse(
            ok=False,
            error=str(exc),
            error_type=type(exc).__name__,
        )


@router.post(
    "/eval-file",
    response_model=LuaEvalResponse,
    summary="Evaluate a Lua script file",
)
async def lua_eval_file(
    body: LuaEvalFileRequest,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> LuaEvalResponse:
    """Evaluate a Lua script file by path (admin only)."""
    client = _require_client(client)
    if not client.lua_is_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lua scripting not available (library not compiled with LUA_SCRIPT)",
        )
    try:
        client.lua_eval_file(body.path)
        return LuaEvalResponse(ok=True, error="")
    except LuaError as exc:
        return LuaEvalResponse(
            ok=False,
            error=str(exc),
            error_type=type(exc).__name__,
        )
