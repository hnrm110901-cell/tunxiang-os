"""运营路由 — 排班/考勤/薪酬/损耗

Sprint 5-8 逐步填充真实逻辑。
"""
from fastapi import APIRouter

from ...shared.response import ok

router = APIRouter(prefix="/api/v1/ops", tags=["ops"])


@router.get("/employees")
async def list_employees(store_id: str | None = None, page: int = 1, size: int = 20):
    """员工列表"""
    return ok({"items": [], "total": 0, "page": page, "size": size})


@router.get("/schedule")
async def get_schedule(store_id: str | None = None, week: str | None = None):
    """排班表"""
    return ok({"schedule": [], "store_id": store_id, "week": week})
