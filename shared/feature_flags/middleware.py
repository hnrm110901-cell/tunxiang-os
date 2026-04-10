"""
屯象OS Feature Flag FastAPI 中间件

从已有 auth 中间件设置的 request.state 中提取多维度上下文，
构造 FlagContext 注入到 request.state.flag_context。

使用方式：
    from shared.feature_flags.middleware import FeatureFlagMiddleware

    app = FastAPI(...)
    app.add_middleware(FeatureFlagMiddleware)

    # 在路由或依赖中使用
    @app.get("/endpoint")
    async def handler(request: Request):
        ctx = request.state.flag_context
        if is_enabled(GrowthFlags.JOURNEY_V2, ctx):
            ...
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from .flag_client import FlagContext


class FeatureFlagMiddleware(BaseHTTPMiddleware):
    """
    从 JWT / auth 中间件注入的 request.state 中提取上下文维度，
    构造 FlagContext 注入到 request.state.flag_context。

    前置依赖：
        - 需在此中间件之前执行 auth 中间件（设置 request.state.tenant_id 等字段）
        - auth 中间件位于各服务的 api/routes.py 或 main.py 的 middleware 注册处

    request.state 字段约定（由 auth 中间件写入）：
        - tenant_id:        str
        - brand_id:         str | None
        - region_id:        str | None
        - store_id:         str | None
        - role_code:        str | None   ("L1" / "L2" / "L3")
        - app_version:      str | None   (来自 X-App-Version header)
        - edge_node_group:  str | None   (来自 X-Edge-Node-Group header，边缘节点分组)
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        # 从 auth 中间件已设置的 request.state 中提取维度
        # 同时支持从 Header 直接读取（方便边缘节点/调试场景）
        context = FlagContext(
            tenant_id=getattr(request.state, "tenant_id", None)
            or request.headers.get("X-Tenant-ID"),
            brand_id=getattr(request.state, "brand_id", None)
            or request.headers.get("X-Brand-ID"),
            region_id=getattr(request.state, "region_id", None)
            or request.headers.get("X-Region-ID"),
            store_id=getattr(request.state, "store_id", None)
            or request.headers.get("X-Store-ID"),
            role_code=getattr(request.state, "role_code", None)
            or request.headers.get("X-Role-Code"),
            app_version=getattr(request.state, "app_version", None)
            or request.headers.get("X-App-Version"),
            edge_node_group=getattr(request.state, "edge_node_group", None)
            or request.headers.get("X-Edge-Node-Group"),
        )

        request.state.flag_context = context
        return await call_next(request)
