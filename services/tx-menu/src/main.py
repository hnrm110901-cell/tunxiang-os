"""tx-menu — 域B 商品菜单微服务"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.dishes import router as dish_router
from .api.publish import router as publish_router
from .api.pricing_routes import router as pricing_router
from .api.menu_routes import router as menu_center_router
from .api.practice_routes import router as practice_router
from .api.combo_routes import router as combo_router

app = FastAPI(title="TunxiangOS tx-menu", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(dish_router)
app.include_router(publish_router)
app.include_router(pricing_router)
app.include_router(menu_center_router)
app.include_router(practice_router)
app.include_router(combo_router)

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-menu", "version": "3.0.0"}}
