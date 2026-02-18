"""
FastAPI dependency injection for the eiskaltdcpp-py REST API.

Provides:
- get_auth_manager: AuthManager singleton
- get_dc_client: AsyncDCClient singleton
- get_current_user: JWT token validation → UserRecord
- require_admin: Restrict endpoint to admin users
- require_readonly: Allow any authenticated user
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from eiskaltdcpp.api.auth import AuthManager, UserRecord, UserStore
from eiskaltdcpp.api.models import UserRole

# Security scheme — Bearer token
security = HTTPBearer(auto_error=False)

# ============================================================================
# Singletons — set during app startup via configure()
# ============================================================================

_auth_manager: Optional[AuthManager] = None
_dc_client = None  # AsyncDCClient or None
_start_time: float = 0.0


def configure(
    auth_manager: AuthManager,
    dc_client=None,
    start_time: float = 0.0,
) -> None:
    """Configure dependency singletons. Called once during app startup."""
    global _auth_manager, _dc_client, _start_time
    _auth_manager = auth_manager
    _dc_client = dc_client
    _start_time = start_time


def get_auth_manager() -> AuthManager:
    """Get the AuthManager singleton."""
    if _auth_manager is None:
        raise RuntimeError("AuthManager not configured — call configure() first")
    return _auth_manager


def get_user_store() -> UserStore:
    """Get the UserStore from the AuthManager."""
    return get_auth_manager().user_store


def get_dc_client():
    """Get the AsyncDCClient singleton (may be None if not configured)."""
    return _dc_client


def get_start_time() -> float:
    """Get server start timestamp."""
    return _start_time


# ============================================================================
# Authentication dependencies
# ============================================================================

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    auth: AuthManager = Depends(get_auth_manager),
) -> UserRecord:
    """
    Validate JWT Bearer token and return the authenticated user.

    Raises 401 if token is missing, invalid, or expired.
    Raises 401 if the user no longer exists in the store.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = auth.verify_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = payload.get("sub")
    user = auth.user_store.get_user(username)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def require_admin(
    user: UserRecord = Depends(get_current_user),
) -> UserRecord:
    """Require the current user to have admin role."""
    if user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


async def require_readonly(
    user: UserRecord = Depends(get_current_user),
) -> UserRecord:
    """Allow any authenticated user (admin or readonly)."""
    return user
