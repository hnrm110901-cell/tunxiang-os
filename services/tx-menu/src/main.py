"""tx-menu — 域B 商品菜单微服务"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.banquet_menu_routes import router as banquet_menu_router
from .api.brand_publish_routes import router as brand_publish_router
from .api.channel_mapping_routes import router as channel_mapping_router
from .api.channel_menu_override_routes import router as channel_menu_override_router  # Y-C4 多渠道菜单发布完善
from .api.combo_routes import router as combo_router
from .api.dish_intel_routes import router as dish_intel_router
from .api.dish_lifecycle_routes import lifecycle_router as dish_lifecycle_manage_router
from .api.dish_lifecycle_routes import router as dish_lifecycle_router
from .api.dish_ranking_engine_routes import router as dish_ranking_engine_router  # P3-04 5因子动态排名
from .api.dishes import router as dish_router
from .api.live_edit_routes import router as live_edit_router
from .api.live_seafood_query_routes import router as live_seafood_query_router

# 徐记海鲜专属模块
from .api.live_seafood_routes import router as live_seafood_router
from .api.menu_approval_routes import router as menu_approval_router
from .api.menu_routes import router as menu_center_router
from .api.menu_version_routes import router as menu_version_router
from .api.practice_routes import router as practice_router
from .api.pricing_routes import router as pricing_router
from .api.publish import router as publish_router
from .api.scheme_routes import router as scheme_router

app = FastAPI(title="TunxiangOS tx-menu", version="3.0.0")

from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(dish_router)
app.include_router(publish_router)
app.include_router(pricing_router)
app.include_router(menu_center_router)
app.include_router(practice_router)
app.include_router(combo_router)
app.include_router(menu_version_router)
app.include_router(dish_lifecycle_router, prefix="/api/v1/dish-lifecycle")
app.include_router(dish_lifecycle_manage_router)  # /api/v1/menu/lifecycle/* + /api/v1/dishes/{id}/lifecycle/*
app.include_router(channel_mapping_router)
app.include_router(menu_approval_router)
app.include_router(dish_intel_router)
app.include_router(live_edit_router)
app.include_router(brand_publish_router)  # 品牌→门店三级发布体系
app.include_router(live_seafood_router)  # 徐记：活鲜海鲜（称重/条头/鱼缸）
app.include_router(live_seafood_query_router)  # 徐记：活鲜查询（前端点单专用）
app.include_router(banquet_menu_router)  # 徐记：宴席菜单（多档次/分节/场次管理）
app.include_router(scheme_router)  # 菜谱方案批量下发（集团→门店）
app.include_router(dish_ranking_engine_router)  # P3-04 5因子动态排名引擎
app.include_router(channel_menu_override_router)  # Y-C4 多渠道菜单发布完善（门店差异价/上下架覆盖）
from .api.personalized_menu_routes import router as personalized_menu_router

app.include_router(personalized_menu_router)  # 千人千面个性化菜单
from .api.menu_display_routes import router as menu_display_router

app.include_router(menu_display_router)  # 菜单展示（POS/H5/Crew/TV通用）+ SpecSheet + 批量沽清
from .api.menu_recommendation_routes import router as menu_recommendation_router

app.include_router(menu_recommendation_router)  # AI智能排菜推荐（四象限/库存/季节/毛利优化）
from .api.menu_plan_routes import router as menu_plan_router

app.include_router(menu_plan_router)  # 模块3.4 菜谱方案版本管理+下发日志+门店差异化+批量操作
from .api.menu_plan_v2_routes import router as menu_plan_v2_router

app.include_router(menu_plan_v2_router)  # 菜谱方案批量下发V2+门店Override（天财对齐版）


# ── Sprint D3c 路由自动挂载（PR #84 合入后自动生效）──
from pathlib import Path as _Path  # noqa: E402

from shared.service_utils import auto_mount_routes, validate_result  # noqa: E402

_sprint_d3c_mount = auto_mount_routes(
    app,
    pkg=__package__,
    api_dir=_Path(__file__).parent / "api",
    modules=[
        ("dish_pricing_routes", "router"),  # D3c #84
    ],
)
validate_result(_sprint_d3c_mount)


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-menu", "version": "3.0.0"}}
