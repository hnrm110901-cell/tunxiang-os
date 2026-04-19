"""KDS 等叫三态 & 出单模式配置 API

# ROUTER REGISTRATION:
# from .api.kds_config_routes import router as kds_config_router
# app.include_router(kds_config_router, prefix="/api/v1/kds-config")

端点清单：
  GET  /calling/{store_id}           — 等叫队列
  POST /task/{task_id}/call          — 标记等叫（cooking → calling）
  POST /task/{task_id}/serve         — 确认上桌（calling → done）
  GET  /calling/{store_id}/stats     — 等叫统计
  GET  /push-mode/{store_id}         — 查询出单模式
  PUT  /push-mode/{store_id}         — 设置出单模式

所有端点需要 X-Tenant-ID header。
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.kds_call_service import KdsCallService
from ..services.order_push_config import OrderPushConfigService, OrderPushMode

router = APIRouter(tags=["kds-config"])


# ─── 公共依赖 ───


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求 / 响应 Schemas ───


class SetPushModeReq(BaseModel):
    mode: OrderPushMode


# ─── 等叫队列 ───


@router.get("/calling/{store_id}")
async def api_get_calling_tasks(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """返回当前门店所有 calling 状态的工单（等叫队列）。

    按 called_at 升序排列，等待最久的在最前。
    """
    tenant_id = _get_tenant_id(request)
    try:
        tasks = await KdsCallService.get_calling_tasks(store_id, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    items = [
        {
            "task_id": str(t.id),
            "status": t.status,
            "dept_id": str(t.dept_id) if t.dept_id else None,
            "order_item_id": str(t.order_item_id),
            "called_at": getattr(t, "called_at", None).isoformat() if getattr(t, "called_at", None) else None,
            "call_count": getattr(t, "call_count", 0),
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tasks
    ]
    return {"ok": True, "data": {"items": items, "total": len(items)}}


# ─── 标记等叫 ───


@router.post("/task/{task_id}/call")
async def api_mark_calling(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """厨师标记菜品已做好、等服务员叫菜（cooking → calling）。"""
    tenant_id = _get_tenant_id(request)
    try:
        task = await KdsCallService.mark_calling(task_id, tenant_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "ok": True,
        "data": {
            "task_id": str(task.id),
            "status": task.status,
            "called_at": getattr(task, "called_at", None).isoformat() if getattr(task, "called_at", None) else None,
            "call_count": getattr(task, "call_count", 0),
        },
    }


# ─── 确认上桌 ───


@router.post("/task/{task_id}/serve")
async def api_confirm_served(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """服务员确认菜品已上桌（calling → done）。"""
    tenant_id = _get_tenant_id(request)
    try:
        task = await KdsCallService.confirm_served(task_id, tenant_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "ok": True,
        "data": {
            "task_id": str(task.id),
            "status": task.status,
            "served_at": getattr(task, "served_at", None).isoformat() if getattr(task, "served_at", None) else None,
        },
    }


# ─── 等叫统计 ───


@router.get("/calling/{store_id}/stats")
async def api_calling_stats(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """等叫队列统计：calling 数量 + 平均等待时长（分钟）。"""
    tenant_id = _get_tenant_id(request)
    try:
        stats = await KdsCallService.get_calling_stats(store_id, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "ok": True,
        "data": {
            "calling_count": stats.calling_count,
            "avg_waiting_minutes": stats.avg_waiting_minutes,
        },
    }


# ─── 出单模式查询 ───


@router.get("/push-mode/{store_id}")
async def api_get_push_mode(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """查询门店出单推送模式。"""
    tenant_id = _get_tenant_id(request)
    try:
        mode = await OrderPushConfigService.get_store_mode(store_id, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "push_mode": mode.value,
            "description": "下单即推送" if mode == OrderPushMode.IMMEDIATE else "收银核销后推送",
        },
    }


# ─── 出单模式设置 ───


@router.put("/push-mode/{store_id}")
async def api_set_push_mode(
    store_id: str,
    body: SetPushModeReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """设置门店出单推送模式（IMMEDIATE / POST_PAYMENT）。"""
    tenant_id = _get_tenant_id(request)
    try:
        await OrderPushConfigService.set_store_mode(store_id, body.mode, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "push_mode": body.mode.value,
        },
    }
