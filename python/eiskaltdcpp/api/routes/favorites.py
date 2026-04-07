"""
Favorites management API routes.

GET    /api/favorites/hubs          — List favorite hubs
POST   /api/favorites/hubs          — Add a favorite hub
DELETE /api/favorites/hubs           — Remove a favorite hub
GET    /api/favorites/dirs           — List favorite directories
POST   /api/favorites/dirs           — Add a favorite directory
DELETE /api/favorites/dirs           — Remove a favorite directory
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from eiskaltdcpp.api.auth import UserRecord
from eiskaltdcpp.api.dependencies import get_dc_client, require_admin, require_readonly
from eiskaltdcpp.api.models import (
    FavoriteDirAdd,
    FavoriteDirInfo,
    FavoriteDirList,
    FavoriteHubAdd,
    FavoriteHubInfo,
    FavoriteHubList,
    SuccessResponse,
)

router = APIRouter(prefix="/api/favorites", tags=["favorites"])


def _require_client(client):
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DC client not initialized",
        )
    return client


# ── Favorite hubs ────────────────────────────────────────────────────────

@router.get(
    "/hubs",
    response_model=FavoriteHubList,
    summary="List favorite hubs",
)
async def list_favorite_hubs(
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> FavoriteHubList:
    client = _require_client(client)
    fm = client.favorites
    raw = fm.getFavoriteHubs()
    hubs = []
    for entry in raw:
        hubs.append(FavoriteHubInfo(
            name=entry.getName(),
            server=entry.getServer(),
            description=entry.getHubDescription(),
            nick=entry.getNick(),
            password=entry.getPassword(),
            encoding=entry.getEncoding(),
            group=entry.getGroup(),
            connect=entry.getConnect(),
        ))
    return FavoriteHubList(hubs=hubs, total=len(hubs))


@router.post(
    "/hubs",
    response_model=SuccessResponse,
    summary="Add a favorite hub",
)
async def add_favorite_hub(
    body: FavoriteHubAdd,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    client = _require_client(client)
    fm = client.favorites
    # Check if already exists
    if fm.isFavoriteHub(body.server):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Hub already in favorites: {body.server}",
        )
    # Get an existing entry to use as template, or create via bridge
    # FavoriteHubEntry requires DCContext& — use the bridge's add method
    from eiskaltdcpp import dc_core
    entry = dc_core.FavoriteHubEntry()
    entry.setName(body.name)
    entry.setServer(body.server)
    entry.setHubDescription(body.description)
    if body.nick:
        entry.setNick(body.nick)
    if body.password:
        entry.setPassword(body.password)
    if body.encoding:
        entry.setEncoding(body.encoding)
    if body.group:
        entry.setGroup(body.group)
    fm.addFavorite(entry)
    return SuccessResponse(message=f"Added favorite hub: {body.server}")


@router.delete(
    "/hubs",
    response_model=SuccessResponse,
    summary="Remove a favorite hub",
)
async def remove_favorite_hub(
    server: str,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    client = _require_client(client)
    fm = client.favorites
    entry = fm.getFavoriteHubEntry(server)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Favorite hub not found: {server}",
        )
    fm.removeFavorite(entry)
    return SuccessResponse(message=f"Removed favorite hub: {server}")


# ── Favorite directories ─────────────────────────────────────────────────

@router.get(
    "/dirs",
    response_model=FavoriteDirList,
    summary="List favorite directories",
)
async def list_favorite_dirs(
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> FavoriteDirList:
    client = _require_client(client)
    fm = client.favorites
    raw = fm.getFavoriteDirs()
    dirs = []
    for pair in raw:
        dirs.append(FavoriteDirInfo(
            path=pair[0] if hasattr(pair, '__getitem__') else getattr(pair, 'first', ''),
            name=pair[1] if hasattr(pair, '__getitem__') else getattr(pair, 'second', ''),
        ))
    return FavoriteDirList(dirs=dirs, total=len(dirs))


@router.post(
    "/dirs",
    response_model=SuccessResponse,
    summary="Add a favorite directory",
)
async def add_favorite_dir(
    body: FavoriteDirAdd,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    client = _require_client(client)
    fm = client.favorites
    ok = fm.addFavoriteDir(body.path, body.name)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to add favorite directory: {body.path}",
        )
    return SuccessResponse(message=f"Added favorite directory: {body.name}")


@router.delete(
    "/dirs",
    response_model=SuccessResponse,
    summary="Remove a favorite directory",
)
async def remove_favorite_dir(
    name: str,
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    client = _require_client(client)
    fm = client.favorites
    ok = fm.removeFavoriteDir(name)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Favorite directory not found: {name}",
        )
    return SuccessResponse(message=f"Removed favorite directory: {name}")
