"""V1 API routes."""

from app.routes.v1.analysis import router as analysis_router
from app.routes.v1.conversations import router as conversations_router
from app.routes.v1.health import router as health_router

__all__ = [
    "health_router",
    "analysis_router",
    "conversations_router",
]
