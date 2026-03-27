"""Hub管理路由 — 屯象科技运维管理端

跨租户操作，需要 platform-admin 级别认证。
"""
from typing import Optional

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/hub", tags=["hub"])


@router.get("/merchants")
async def list_merchants(status: Optional[str] = None, page: int = 1, size: int = 20):
    """列出所有商户"""
    return {"ok": True, "data": {"items": [
        {"id": "m1", "name": "尝在一起", "template": "standard", "stores": 5, "status": "active"},
        {"id": "m2", "name": "徐记海鲜", "template": "pro", "stores": 100, "status": "active"},
        {"id": "m3", "name": "最黔线", "template": "standard", "stores": 8, "status": "trial"},
        {"id": "m4", "name": "尚宫厨", "template": "lite", "stores": 3, "status": "active"},
    ], "total": 4}}


@router.get("/platform/stats")
async def platform_stats():
    """平台运营数据"""
    return {"ok": True, "data": {
        "total_merchants": 4,
        "total_stores": 116,
        "mode": "monolith",
    }}
