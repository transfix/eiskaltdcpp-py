"""
Chat and messaging API routes.

POST /api/chat/message — Send public chat message (admin)
POST /api/chat/pm      — Send private message (admin)
GET  /api/chat/history — Get chat history for a hub (readonly+)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from eiskaltdcpp.api.auth import UserRecord
from eiskaltdcpp.api.dependencies import get_dc_client, require_admin, require_readonly
from eiskaltdcpp.api.models import (
    ChatHistory,
    ChatMessage,
    PrivateMessage,
    SuccessResponse,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _require_client(client):
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DC client not initialized",
        )
    return client


@router.post(
    "/message",
    response_model=SuccessResponse,
    summary="Send a public chat message",
)
async def send_message(
    body: ChatMessage,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Send a public chat message to a hub (admin only)."""
    client = _require_client(client)
    client.send_message(body.hub_url, body.message)
    return SuccessResponse(message="Message sent")


@router.post(
    "/pm",
    response_model=SuccessResponse,
    summary="Send a private message",
)
async def send_pm(
    body: PrivateMessage,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Send a private message to a user on a hub (admin only)."""
    client = _require_client(client)
    client.send_pm(body.hub_url, body.nick, body.message)
    return SuccessResponse(message="PM sent")


@router.get(
    "/history",
    response_model=ChatHistory,
    summary="Get chat history",
)
async def get_chat_history(
    hub_url: str = Query(..., description="Hub URL"),
    max_lines: int = Query(100, ge=1, le=1000),
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> ChatHistory:
    """Get recent chat history for a hub (any authenticated user)."""
    client = _require_client(client)
    messages = client.get_chat_history(hub_url, max_lines)
    return ChatHistory(hub_url=hub_url, messages=messages)
