"""expo_routes.py — Expo传菜督导API

传菜督导（ExpoStation）是同桌同出协调引擎的前端接口。
实时显示每桌出品进度，全绿（all_ready）时亮起传菜信号。

所有接口需要 X-Tenant-ID header。

端点：
  GET  /expo/{store_id}/overview      - 所有桌的协调状态（传菜督导主视图）
  POST /expo/{plan_id}/served         - 确认传菜完成
  GET  /expo/{plan_id}/status         - 单桌协调状态
  POST /expo/dispatch/{order_id}/fire - 分单并创建TableFire计划（集成入口）
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.table_production_plan import TableFireCoordinator
from ..services.cooking_scheduler import create_table_fire_plan
from ..services.kds_dispatch import dispatch_order_to_kds
from ..models.table_production_plan import TableProductionPlan
from sqlalchemy import select, and_
import uuid

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/expo", tags=["expo"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求模型 ───

class DispatchAndFireItem(BaseModel):
    dish_id: str
    item_name: str
    quantity: int = 1
    order_item_id: Optional[str] = None
    notes: Optional[str] = None


class DispatchAndFireReq(BaseModel):
    """分单并创建TableFire协调计划的请求体"""
    items: list[DispatchAndFireItem]
    table_number: Optional[str] = None
    order_no: Optional[str] = None
    store_id: str


# ═════════════════════════════════════════════
# GET /expo/{store_id}/overview
# ═════════════════════════════════════════════

@router.get("/{store_id}/overview")
async def expo_overview(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """传菜督导主视图：该门店所有活跃桌的出品进度

    返回所有 coordinating / all_ready 状态的桌位进度条。
    status=all_ready 的票据表示可以传菜。

    Response:
        {
            "ok": true,
            "data": {
                "tickets": [ExpoTicket, ...],
                "total": int,
                "all_ready_count": int
            }
        }
    """
    tenant_id = _get_tenant_id(request)
    log = logger.bind(store_id=store_id, tenant_id=tenant_id)

    coordinator = TableFireCoordinator()
    try:
        tickets = await coordinator.get_expo_view(
            store_id=store_id,
            tenant_id=tenant_id,
            db=db,
        )
    except (ValueError, AttributeError) as exc:
        log.error("expo_routes.overview.error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="获取传菜督导视图失败")

    all_ready_count = sum(1 for t in tickets if t["status"] == "all_ready")

    return {
        "ok": True,
        "data": {
            "tickets": tickets,
            "total": len(tickets),
            "all_ready_count": all_ready_count,
        },
    }


# ═════════════════════════════════════════════
# POST /expo/{plan_id}/served
# ═════════════════════════════════════════════

@router.post("/{plan_id}/served")
async def expo_mark_served(
    plan_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """确认传菜完成，将协调计划状态更新为 served

    传菜员在实际送餐到桌后调用此接口，
    计划进入 served 状态后不再显示在督导视图中。

    Response:
        {"ok": true, "data": {"plan_id": str, "status": "served"}}
    """
    tenant_id = _get_tenant_id(request)
    log = logger.bind(plan_id=plan_id, tenant_id=tenant_id)

    coordinator = TableFireCoordinator()
    try:
        updated = await coordinator.mark_served(
            plan_id=plan_id,
            tenant_id=tenant_id,
            db=db,
        )
    except (ValueError, AttributeError) as exc:
        log.error("expo_routes.served.error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="更新传菜状态失败")

    if not updated:
        raise HTTPException(status_code=404, detail=f"计划 {plan_id} 不存在或已完成")

    await db.commit()

    return {"ok": True, "data": {"plan_id": plan_id, "status": "served"}}


# ═════════════════════════════════════════════
# GET /expo/{plan_id}/status
# ═════════════════════════════════════════════

@router.get("/{plan_id}/status")
async def expo_plan_status(
    plan_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """查询单桌协调状态

    返回该桌所有档口的就绪进度和预计完成时间。

    Response:
        {
            "ok": true,
            "data": {
                "plan_id": str,
                "table_no": str,
                "status": str,
                "dept_readiness": {dept_id: bool},
                "dept_delays": {dept_id: seconds},
                "target_completion": str,
                "ready_depts": int,
                "total_depts": int
            }
        }
    """
    tenant_id = _get_tenant_id(request)
    log = logger.bind(plan_id=plan_id, tenant_id=tenant_id)

    try:
        stmt = select(TableProductionPlan).where(
            and_(
                TableProductionPlan.id == uuid.UUID(plan_id),
                TableProductionPlan.tenant_id == uuid.UUID(tenant_id),
                TableProductionPlan.is_deleted == False,  # noqa: E712
            )
        )
        result = await db.execute(stmt)
        plan = result.scalar_one_or_none()
    except (ValueError, AttributeError) as exc:
        log.error("expo_routes.plan_status.error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=400, detail="无效的 plan_id 格式")

    if not plan:
        raise HTTPException(status_code=404, detail=f"计划 {plan_id} 不存在")

    readiness = plan.dept_readiness or {}
    total = len(readiness)
    ready = sum(1 for v in readiness.values() if v)

    return {
        "ok": True,
        "data": {
            "plan_id": str(plan.id),
            "order_id": str(plan.order_id),
            "table_no": plan.table_no,
            "store_id": str(plan.store_id),
            "status": plan.status,
            "dept_readiness": readiness,
            "dept_delays": plan.dept_delays or {},
            "target_completion": (
                plan.target_completion.isoformat() if plan.target_completion else None
            ),
            "ready_depts": ready,
            "total_depts": total,
        },
    }


# ═════════════════════════════════════════════
# POST /expo/dispatch/{order_id}/fire
# ═════════════════════════════════════════════

@router.post("/dispatch/{order_id}/fire")
async def expo_dispatch_and_fire(
    order_id: str,
    body: DispatchAndFireReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """分单并创建TableFire同出协调计划（集成入口）

    在标准 KDS 分单基础上，额外创建 TableProductionPlan，
    为各档口计算延迟开始时间，实现同桌同出协调。

    此接口是 TableFire 的主要入口，适合新订单上桌时调用。

    Response:
        {
            "ok": true,
            "data": {
                "dept_tasks": [...],
                "table_fire": {
                    "plan_id": str,
                    "dept_delays": {dept_id: seconds},
                    "target_completion": str
                }
            }
        }
    """
    tenant_id = _get_tenant_id(request)
    log = logger.bind(order_id=order_id, tenant_id=tenant_id)

    items = [item.model_dump() for item in body.items]

    # ── 1. 标准分单 ──
    try:
        dispatch_result = await dispatch_order_to_kds(
            order_id,
            items,
            tenant_id,
            db,
            table_number=body.table_number or "",
            order_no=body.order_no or "",
        )
    except (ValueError, AttributeError) as exc:
        log.error("expo_routes.dispatch_fire.dispatch_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="KDS分单失败")

    dept_tasks = dispatch_result.get("dept_tasks", [])

    # ── 2. 创建TableFire协调计划 ──
    table_fire_result: dict | None = None
    try:
        table_fire_result = await create_table_fire_plan(
            order_id=order_id,
            table_no=body.table_number or "",
            store_id=body.store_id,
            tenant_id=tenant_id,
            dept_tasks=dept_tasks,
            db=db,
        )
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 创建失败不阻断分单，最外层兜底
        # TableFire 创建失败不阻断分单流程，记录日志后继续
        log.error(
            "expo_routes.dispatch_fire.table_fire_failed",
            error=str(exc),
            exc_info=True,
        )

    await db.commit()

    log.info(
        "expo_routes.dispatch_fire.done",
        dept_count=len(dept_tasks),
        table_fire_created=table_fire_result is not None,
    )

    return {
        "ok": True,
        "data": {
            "dept_tasks": dept_tasks,
            "table_fire": table_fire_result,
        },
    }
