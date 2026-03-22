"""tx-menu — 域B 商品菜单微服务

菜品管理、BOM配方、菜单排名、动态定价、四象限分类
来源：37 个 service 文件迁移自 tunxiang V2.x
"""
from fastapi import FastAPI
from .api.dishes import router as dish_router

app = FastAPI(title="TunxiangOS tx-menu", version="3.0.0")
app.include_router(dish_router)

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-menu", "version": "3.0.0"}}
