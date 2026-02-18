"""Route package — registers all API routers."""
from __future__ import annotations

from eiskaltdcpp.api.routes.auth import router as auth_router
from eiskaltdcpp.api.routes.chat import router as chat_router
from eiskaltdcpp.api.routes.hubs import router as hubs_router
from eiskaltdcpp.api.routes.queue import router as queue_router
from eiskaltdcpp.api.routes.search import router as search_router
from eiskaltdcpp.api.routes.settings import router as settings_router
from eiskaltdcpp.api.routes.shares import router as shares_router
from eiskaltdcpp.api.routes.status import router as status_router
from eiskaltdcpp.api.dashboard import router as dashboard_router
from eiskaltdcpp.api.websocket import router as ws_router

all_routers = [
    auth_router,
    hubs_router,
    chat_router,
    search_router,
    queue_router,
    shares_router,
    settings_router,
    status_router,
    ws_router,
    dashboard_router,
]
