"""
Search API routes.

POST   /api/search         — Start a search (admin)
GET    /api/search/results  — Get search results (readonly+)
DELETE /api/search/results  — Clear search results (admin)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from eiskaltdcpp.api.auth import UserRecord
from eiskaltdcpp.api.dependencies import get_dc_client, require_admin, require_readonly
from eiskaltdcpp.api.models import (
    SearchRequest,
    SearchResult,
    SearchResults,
    SuccessResponse,
)

router = APIRouter(prefix="/api/search", tags=["search"])


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
    summary="Start a search",
)
async def start_search(
    body: SearchRequest,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Start a search across connected hubs (admin only)."""
    client = _require_client(client)
    ok = client.search(
        body.query,
        file_type=body.file_type,
        size_mode=body.size_mode,
        size=body.size,
        hub_url=body.hub_url,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search failed — not connected to any hub?",
        )
    return SuccessResponse(message=f"Search started: {body.query}")


@router.get(
    "/results",
    response_model=SearchResults,
    summary="Get search results",
)
async def get_results(
    hub_url: str = Query("", description="Filter by hub (empty=all)"),
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> SearchResults:
    """Get accumulated search results (any authenticated user)."""
    client = _require_client(client)
    raw = client.get_search_results(hub_url)
    results = []
    for r in raw:
        results.append(SearchResult(
            hub_url=getattr(r, "hubUrl", ""),
            file=getattr(r, "file", str(r)),
            size=getattr(r, "size", 0),
            free_slots=getattr(r, "freeSlots", 0),
            total_slots=getattr(r, "totalSlots", 0),
            tth=getattr(r, "tth", ""),
            nick=getattr(r, "nick", ""),
            is_directory=getattr(r, "isDirectory", False),
        ))
    return SearchResults(results=results, total=len(results))


@router.delete(
    "/results",
    response_model=SuccessResponse,
    summary="Clear search results",
)
async def clear_results(
    hub_url: str = Query("", description="Filter by hub (empty=all)"),
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    """Clear search results (admin only)."""
    client = _require_client(client)
    client.clear_search_results(hub_url)
    return SuccessResponse(message="Search results cleared")
