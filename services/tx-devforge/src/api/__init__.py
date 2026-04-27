"""tx-devforge API 路由集合。"""

from .app_routes import router as application_router
from .health_routes import router as health_router

__all__ = ["application_router", "health_router"]
