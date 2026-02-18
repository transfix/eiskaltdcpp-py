"""
Authentication and user management API routes.

POST /api/auth/login        — Get JWT token (public)
GET  /api/auth/me           — Current user info (authenticated)
POST /api/auth/users        — Create user (admin)
GET  /api/auth/users        — List users (admin)
GET  /api/auth/users/{name} — Get user info (admin)
PUT  /api/auth/users/{name} — Update user (admin)
DELETE /api/auth/users/{name} — Delete user (admin)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from eiskaltdcpp.api.auth import AuthManager, UserRecord, UserStore
from eiskaltdcpp.api.dependencies import (
    get_auth_manager,
    get_current_user,
    get_user_store,
    require_admin,
)
from eiskaltdcpp.api.models import (
    ErrorResponse,
    SuccessResponse,
    TokenRequest,
    TokenResponse,
    UserCreate,
    UserInfo,
    UserList,
    UserUpdate,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ============================================================================
# Public endpoints
# ============================================================================

@router.post(
    "/login",
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse}},
    summary="Login and get JWT token",
)
async def login(
    body: TokenRequest,
    auth: AuthManager = Depends(get_auth_manager),
) -> TokenResponse:
    """Authenticate with username/password and receive a JWT bearer token."""
    result = auth.login(body.username, body.password)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token, expires_in, role = result
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        role=role,
    )


# ============================================================================
# Authenticated endpoints
# ============================================================================

@router.get(
    "/me",
    response_model=UserInfo,
    summary="Get current user info",
)
async def get_me(
    user: UserRecord = Depends(get_current_user),
) -> UserInfo:
    """Return the currently authenticated user's information."""
    return user.to_info()


# ============================================================================
# Admin user management
# ============================================================================

@router.post(
    "/users",
    response_model=UserInfo,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
    summary="Create a new API user",
)
async def create_user(
    body: UserCreate,
    _admin: UserRecord = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> UserInfo:
    """Create a new API user (admin only)."""
    try:
        rec = store.create_user(body.username, body.password, body.role)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    return rec.to_info()


@router.get(
    "/users",
    response_model=UserList,
    summary="List all API users",
)
async def list_users(
    _admin: UserRecord = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> UserList:
    """List all API users (admin only)."""
    users = store.list_users()
    return UserList(
        users=[u.to_info() for u in users],
        total=len(users),
    )


@router.get(
    "/users/{username}",
    response_model=UserInfo,
    responses={404: {"model": ErrorResponse}},
    summary="Get a specific user's info",
)
async def get_user(
    username: str,
    _admin: UserRecord = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> UserInfo:
    """Get a specific user's information (admin only)."""
    rec = store.get_user(username)
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' not found",
        )
    return rec.to_info()


@router.put(
    "/users/{username}",
    response_model=UserInfo,
    responses={404: {"model": ErrorResponse}},
    summary="Update a user",
)
async def update_user(
    username: str,
    body: UserUpdate,
    _admin: UserRecord = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> UserInfo:
    """Update a user's password and/or role (admin only)."""
    try:
        rec = store.update_user(username, password=body.password, role=body.role)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' not found",
        )
    return rec.to_info()


@router.delete(
    "/users/{username}",
    response_model=SuccessResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Delete a user",
)
async def delete_user(
    username: str,
    admin: UserRecord = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> SuccessResponse:
    """Delete an API user (admin only). Cannot delete yourself."""
    if username == admin.username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )
    try:
        store.delete_user(username)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' not found",
        )
    return SuccessResponse(message=f"User '{username}' deleted")
