"""
ADL search API routes.

GET    /api/adl/searches            — List ADL search entries
POST   /api/adl/searches            — Add an ADL search entry
DELETE /api/adl/searches/{index}    — Remove an ADL search entry
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from eiskaltdcpp.api.auth import UserRecord
from eiskaltdcpp.api.dependencies import get_dc_client, require_admin, require_readonly
from eiskaltdcpp.api.models import ADLSearchAdd, ADLSearchEntry, ADLSearchList, SuccessResponse

router = APIRouter(prefix="/api/adl", tags=["adl"])


def _require_client(client):
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DC client not initialized",
        )
    return client


@router.get(
    "/searches",
    response_model=ADLSearchList,
    summary="List ADL search entries",
)
async def list_adl_searches(
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> ADLSearchList:
    client = _require_client(client)
    am = client.adl_search
    raw = am.collection
    searches = []
    for entry in raw:
        searches.append(ADLSearchEntry(
            search_string=entry.searchString,
            is_active=entry.isActive,
            source_type=entry.sourceType,
            dest_directory=entry.destDirectory,
            min_file_size=entry.minFileSize,
            max_file_size=entry.maxFileSize,
        ))
    return ADLSearchList(searches=searches, total=len(searches))


@router.post(
    "/searches",
    response_model=SuccessResponse,
    summary="Add an ADL search entry",
)
async def add_adl_search(
    body: ADLSearchAdd,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    client = _require_client(client)
    from eiskaltdcpp import dc_core
    entry = dc_core.ADLSearch()
    entry.searchString = body.search_string
    entry.isActive = body.is_active
    entry.sourceType = body.source_type
    entry.destDirectory = body.dest_directory
    entry.minFileSize = body.min_file_size
    entry.maxFileSize = body.max_file_size
    am = client.adl_search
    am.collection.append(entry)
    am.save()
    return SuccessResponse(message=f"Added ADL search: {body.search_string}")


@router.delete(
    "/searches/{index}",
    response_model=SuccessResponse,
    summary="Remove an ADL search entry by index",
)
async def remove_adl_search(
    index: int,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    client = _require_client(client)
    am = client.adl_search
    collection = am.collection
    if index < 0 or index >= len(collection):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ADL search index out of range: {index}",
        )
    # Remove by rebuilding — SWIG vectors don't support arbitrary erase
    del collection[index]
    am.save()
    return SuccessResponse(message=f"Removed ADL search at index {index}")
