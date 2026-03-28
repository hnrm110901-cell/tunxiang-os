"""KDS 出餐调度 API — 分单/队列/操作/超时预警

所有接口需要 X-Tenant-ID header。
"""
from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.kds_dispatch import (
    dispatch_order_to_kds, get_dept_queue, get_store_kds_overview,
    resolve_dept_for_dish,
)
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
    notes: Optional[str] = None


class DispatchReq(BaseModel):
    items: list[DispatchItem]
    table_number: Optional[str] = None
    order_no: Optional[str] = None


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
    """分单 — 将订单菜品自动分配到对应档口

    自动完成菜品->出品部门映射，无需前端传 kitchen_station。
    分单后自动：
    1. 回写 OrderItem.kds_station
    2. 为每个档口生成厨打单并发送到打印机
    """
    tenant_id = _get_tenant_id(request)
    items = [item.model_dump() for item in body.items]
    result = await dispatch_order_to_kds(
        order_id,
        items,
        tenant_id,
        db,
        table_number=body.table_number or "",
        order_no=body.order_no or "",
    )

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


@router.get("/resolve-dept/{dish_id}")
async def api_resolve_dept(
    dish_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """查询菜品对应的出品档口（供加菜场景使用）"""
    tenant_id = _get_tenant_id(request)
    dept = await resolve_dept_for_dish(dish_id, tenant_id, db)
    if not dept:
        return {"ok": True, "data": None, "message": "该菜品未配置出品档口映射"}
    return {"ok": True, "data": dept}


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
    """催菜 — 自动推送催单到 KDS + 发送催菜厨打单到档口打印机"""
    tenant_id = _get_tenant_id(request)
    result = await request_rush(task_id, body.dish_id, db, tenant_id=tenant_id)
    return result


@router.post("/task/{task_id}/remake")
async def api_remake(
    task_id: str,
    body: RemakeReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """重做 — 自动推送重做通知到 KDS + 发送重做厨打单到档口打印机"""
    tenant_id = _get_tenant_id(request)
    result = await request_remake(task_id, body.reason, db, tenant_id=tenant_id)
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
    """超时检查 — 自动推送 warning/critical 到 KDS + 管理员手机"""
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
