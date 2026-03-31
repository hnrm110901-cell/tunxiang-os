"""tx-menu — 域B 商品菜单微服务"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.dishes import router as dish_router
from .api.publish import router as publish_router
from .api.pricing_routes import router as pricing_router
from .api.menu_routes import router as menu_center_router
from .api.practice_routes import router as practice_router
from .api.combo_routes import router as combo_router
from .api.menu_version_routes import router as menu_version_router
from .api.dish_lifecycle_routes import router as dish_lifecycle_router
from .api.dish_lifecycle_routes import lifecycle_router as dish_lifecycle_manage_router
from .api.channel_mapping_routes import router as channel_mapping_router
from .api.menu_approval_routes import router as menu_approval_router
from .api.live_edit_routes import router as live_edit_router

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
app.include_router(live_edit_router)

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-menu", "version": "3.0.0"}}
