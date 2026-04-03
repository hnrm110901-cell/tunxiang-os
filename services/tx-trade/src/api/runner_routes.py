"""传菜员(Runner)工作流 API

所有接口需要 X-Tenant-ID header。

路由：
  GET  /runner/{store_id}/queue         - 传菜员待取菜列表（ready状态，按桌聚合）
  POST /runner/task/{task_id}/pickup    - 传菜员领取菜品（→ delivering）
  POST /runner/task/{task_id}/served    - 送达确认（→ served，全桌上齐时推送通知）
  GET  /runner/{store_id}/history       - 今日传菜记录（served状态）
  POST /runner/task/{task_id}/ready     - KDS完成出品后标记ready（→ ready）
  POST /runner/task/register            - 注册传菜任务（KDS分单时调用）
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.runner_service import (
    confirm_served,
    get_runner_history,
    get_runner_queue,
    mark_ready,
    pickup_dish,
    register_runner_task,
)

router = APIRouter(prefix="/api/v1/runner", tags=["runner"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求模型 ───

class RegisterTaskReq(BaseModel):
    task_id: str
    store_id: str
    table_number: str
    order_id: str
    dish_name: str


# ─── 队列与历史 ───

@router.get("/{store_id}/queue")
async def api_runner_queue(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """传菜员待取菜列表 — 所有 ready 状态菜品，按出品时间升序

    返回按桌号可聚合的任务列表，前端负责桌号分组展示。
    """
    tenant_id = _get_tenant_id(request)
    items = await get_runner_queue(store_id, tenant_id)
    return {"ok": True, "data": {"items": items, "total": len(items)}}


@router.get("/{store_id}/history")
async def api_runner_history(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """今日传菜记录 — 今日 served 状态任务，按送达时间降序"""
    tenant_id = _get_tenant_id(request)
    items = await get_runner_history(store_id, tenant_id)
    return {"ok": True, "data": {"items": items, "total": len(items)}}


# ─── 任务操作 ───

@router.post("/task/{task_id}/ready")
async def api_mark_ready(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """KDS完成出品后将任务标记为 ready，推送到 RunnerStation"""
    operator_id = request.headers.get("X-Operator-ID", "unknown")
    result = await mark_ready(task_id, operator_id)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result.get("error", "操作失败"))
    return result


@router.post("/task/{task_id}/pickup")
async def api_pickup(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """传菜员领取菜品，状态 ready → delivering"""
    runner_id = request.headers.get("X-Operator-ID", "unknown")
    result = await pickup_dish(task_id, runner_id)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result.get("error", "操作失败"))
    return result


@router.post("/task/{task_id}/served")
async def api_served(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """送达确认，状态 delivering → served

    若同一订单所有菜品全部 served，自动推送"全桌上齐"通知到 web-crew。
    """
    runner_id = request.headers.get("X-Operator-ID", "unknown")
    result = await confirm_served(task_id, runner_id)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result.get("error", "操作失败"))
    return result


@router.post("/task/register")
async def api_register_task(
    body: RegisterTaskReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """注册传菜任务（KDS分单时由 kds_dispatch 调用）

    创建初始 pending 状态的传菜任务记录，与 KDS task 同 ID。
    """
    tenant_id = _get_tenant_id(request)
    result = await register_runner_task(
        task_id=body.task_id,
        store_id=body.store_id,
        table_number=body.table_number,
        order_id=body.order_id,
        tenant_id=tenant_id,
        dish_name=body.dish_name,
    )
    return result
