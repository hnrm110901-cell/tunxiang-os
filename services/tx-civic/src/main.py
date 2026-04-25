"""tx-civic — 餐饮城市监管平台对接中间层 (:8014)

统一对接全国各城市政府监管平台:
- 食品安全追溯 (沪食安/浙食链/粤食安...)
- 明厨亮灶 (阳光餐饮/智慧监管...)
- 环保合规 (油烟监测/餐厨垃圾...)
- 消防安全 (设备/巡检/燃气...)
- 证照管理 (食品许可/健康证/排水许可...)
"""

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

try:
    from shared.feature_flags import is_enabled

    _FLAG_SDK_AVAILABLE = True
except ImportError:
    _FLAG_SDK_AVAILABLE = False

    def is_enabled(flag, context=None):
        return True


logger = structlog.get_logger(__name__)

# 导入路由
from .api.adapter_admin_routes import router as adapter_admin_router
from .api.civic_dashboard import router as dashboard_router
from .api.env_routes import router as env_router
from .api.fire_routes import router as fire_router
from .api.kitchen_routes import router as kitchen_router
from .api.license_routes import health_router
from .api.license_routes import router as license_router
from .api.submission_routes import router as submission_router
from .api.traceability_routes import router as trace_router

app = FastAPI(title="TunxiangOS tx-civic", version="1.0.0", description="餐饮城市监管平台对接中间层")

# Prometheus
from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(trace_router)
app.include_router(kitchen_router)
app.include_router(env_router)
app.include_router(license_router)
app.include_router(health_router)
app.include_router(fire_router)
app.include_router(submission_router)
app.include_router(dashboard_router)
app.include_router(adapter_admin_router)


# 启动时初始化适配器注册表
@app.on_event("startup")
async def startup():
    from .adapters.registry import CityAdapterRegistry

    CityAdapterRegistry.auto_discover()
    logger.info("tx_civic_started", supported_cities=CityAdapterRegistry.list_supported_cities(), version="1.0.0")


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-civic", "version": "1.0.0"}}
