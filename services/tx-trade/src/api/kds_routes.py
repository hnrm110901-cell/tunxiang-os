"""KDS 出餐调度 API — 分单/队列/操作/超时预警

所有接口需要 X-Tenant-ID header。
"""
from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.kds_dispatch import dispatch_order_to_kds, get_dept_queue, get_store_kds_overview
from ..services.cooking_scheduler import calculate_cooking_order, estimate_cooking_time, get_dept_load
from ..services.kds_actions import (
    start_cooking, finish_cooking, request_rush, request_remake,
    report_shortage, get_task_timeline,
)
from ..services.cooking_timeout import check_timeouts, get_timeout_config

router = APIRouter(prefix="/api/v1/kds", tags=["kds"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求模型 ───

class DispatchItem(BaseModel):
    dish_id: str
    item_name: str
    quantity: int = 1
    order_item_id: Optional[str] = None


class DispatchReq(BaseModel):
    items: list[DispatchItem]


class RushReq(BaseModel):
    dish_id: str


class RemakeReq(BaseModel):
    reason: str


class ShortageReq(BaseModel):
    ingredient_id: str


# ─── 分单与队列 ───

@router.post("/dispatch/{order_id}")
async def api_dispatch_order(
    order_id: str,
    body: DispatchReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """分单 — 将订单菜品分配到对应档口"""
    tenant_id = _get_tenant_id(request)
    items = [item.model_dump() for item in body.items]
    result = await dispatch_order_to_kds(order_id, items, tenant_id, db)

    # 智能排序
    sorted_tasks = await calculate_cooking_order(result["dept_tasks"], db)

    return {"ok": True, "data": {"dept_tasks": sorted_tasks}}


@router.get("/queue/{dept_id}")
async def api_dept_queue(
    dept_id: str,
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """档口队列 — 获取某档口当前待出品任务"""
    tenant_id = _get_tenant_id(request)
    queue = await get_dept_queue(dept_id, store_id, tenant_id, db)
    return {"ok": True, "data": {"items": queue, "total": len(queue)}}


@router.get("/overview/{store_id}")
async def api_store_overview(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """全店概览 — 所有档口的实时负载"""
    tenant_id = _get_tenant_id(request)
    overview = await get_store_kds_overview(store_id, tenant_id, db)
    return {"ok": True, "data": {"depts": overview, "total": len(overview)}}


@router.get("/load/{dept_id}")
async def api_dept_load(
    dept_id: str,
    db: AsyncSession = Depends(get_db),
):
    """档口负载 — pending/in_progress/avg_wait"""
    load = await get_dept_load(dept_id, db)
    return {"ok": True, "data": load}


# ─── KDS 操作 ───

@router.post("/task/{task_id}/start")
async def api_start_cooking(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """开始制作"""
    operator_id = request.headers.get("X-Operator-ID", "unknown")
    result = await start_cooking(task_id, operator_id, db)
    return result


@router.post("/task/{task_id}/finish")
async def api_finish_cooking(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """完成出品"""
    operator_id = request.headers.get("X-Operator-ID", "unknown")
    result = await finish_cooking(task_id, operator_id, db)
    return result


@router.post("/task/{task_id}/rush")
async def api_rush(
    task_id: str,
    body: RushReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """催菜"""
    result = await request_rush(task_id, body.dish_id, db)
    return result


@router.post("/task/{task_id}/remake")
async def api_remake(
    task_id: str,
    body: RemakeReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """重做"""
    result = await request_remake(task_id, body.reason, db)
    return result


@router.post("/task/{task_id}/shortage")
async def api_shortage(
    task_id: str,
    body: ShortageReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """缺料上报"""
    result = await report_shortage(task_id, body.ingredient_id, db)
    return result


@router.get("/task/{task_id}/timeline")
async def api_task_timeline(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """任务时间线"""
    result = await get_task_timeline(task_id, db)
    return result


# ─── 超时预警 ───

@router.get("/timeouts/{store_id}")
async def api_check_timeouts(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """超时检查 — 列出所有 warning/critical 级别的待出品任务"""
    tenant_id = _get_tenant_id(request)
    items = await check_timeouts(store_id, tenant_id, db)
    return {
        "ok": True,
        "data": {
            "items": items,
            "total": len(items),
            "critical": len([i for i in items if i["status"] == "critical"]),
            "warning": len([i for i in items if i["status"] == "warning"]),
        },
    }


@router.get("/timeouts/{store_id}/config")
async def api_timeout_config(
    store_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取超时配置"""
    config = await get_timeout_config(store_id, db)
    return {"ok": True, "data": config}
