"""
FastAPI application factory for the eiskaltdcpp-py REST API.

Creates and configures the FastAPI app with all routes, middleware,
authentication, and optional DC client integration.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from eiskaltdcpp.api.auth import AuthManager, UserStore
from eiskaltdcpp.api.dependencies import configure
from eiskaltdcpp.api.routes import all_routers

logger = logging.getLogger(__name__)


def create_app(
    *,
    user_store: Optional[UserStore] = None,
    auth_manager: Optional[AuthManager] = None,
    dc_client=None,
    admin_username: Optional[str] = None,
    admin_password: Optional[str] = None,
    jwt_secret: Optional[str] = None,
    token_expire_minutes: int = 1440,
    users_file: Optional[str] = None,
    cors_origins: Optional[list[str]] = None,
    title: str = "eiskaltdcpp-py API",
    version: str = "1.0.0",
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        user_store: Pre-configured UserStore (created if None)
        auth_manager: Pre-configured AuthManager (created if None)
        dc_client: AsyncDCClient instance (None for standalone/testing)
        admin_username: Initial admin username (env: EISKALTDCPP_ADMIN_USER)
        admin_password: Initial admin password (env: EISKALTDCPP_ADMIN_PASS)
        jwt_secret: JWT signing key (env: EISKALTDCPP_JWT_SECRET)
        token_expire_minutes: JWT token lifetime
        users_file: Path to persist users JSON file
        cors_origins: Allowed CORS origins
        title: API title for OpenAPI docs
        version: API version for OpenAPI docs

    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title=title,
        version=version,
        description=(
            "REST API for controlling a running eiskaltdcpp-py DC client instance. "
            "Supports JWT authentication with admin and read-only roles."
        ),
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # CORS
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Set up auth
    if user_store is None:
        user_store = UserStore(persist_path=users_file)
    if auth_manager is None:
        auth_manager = AuthManager(
            user_store=user_store,
            secret_key=jwt_secret,
            token_expire_minutes=token_expire_minutes,
        )

    # Ensure admin user exists
    auth_manager.ensure_admin_exists(admin_username, admin_password)

    # Configure dependency injection
    start_time = time.time()
    configure(
        auth_manager=auth_manager,
        dc_client=dc_client,
        start_time=start_time,
    )

    # Register all routers
    for router in all_routers:
        app.include_router(router)

    logger.info(
        "eiskaltdcpp-py API ready — %d routes, DC client: %s",
        len(app.routes),
        "connected" if dc_client else "not configured",
    )

    return app
