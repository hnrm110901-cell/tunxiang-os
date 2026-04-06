"""tx-menu — 域B 商品菜单微服务"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.banquet_menu_routes import router as banquet_menu_router
from .api.brand_publish_routes import router as brand_publish_router
from .api.channel_mapping_routes import router as channel_mapping_router
from .api.combo_routes import router as combo_router
from .api.dish_lifecycle_routes import lifecycle_router as dish_lifecycle_manage_router
from .api.dish_lifecycle_routes import router as dish_lifecycle_router
from .api.dishes import router as dish_router
from .api.live_edit_routes import router as live_edit_router
from .api.live_seafood_query_routes import router as live_seafood_query_router

# 徐记海鲜专属模块
from .api.live_seafood_routes import router as live_seafood_router
from .api.menu_approval_routes import router as menu_approval_router
from .api.dish_intel_routes import router as dish_intel_router
from .api.menu_routes import router as menu_center_router
from .api.menu_version_routes import router as menu_version_router
from .api.practice_routes import router as practice_router
from .api.pricing_routes import router as pricing_router
from .api.publish import router as publish_router
from .api.scheme_routes import router as scheme_router

app = FastAPI(title="TunxiangOS tx-menu", version="3.0.0")
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
app.include_router(live_seafood_router)        # 徐记：活鲜海鲜（称重/条头/鱼缸）
app.include_router(live_seafood_query_router)  # 徐记：活鲜查询（前端点单专用）
app.include_router(banquet_menu_router)   # 徐记：宴席菜单（多档次/分节/场次管理）
app.include_router(scheme_router)         # 菜谱方案批量下发（集团→门店）

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-menu", "version": "3.0.0"}}
