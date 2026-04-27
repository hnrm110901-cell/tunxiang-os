"""KDS 泳道模式 API 路由"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..services.kds_swimlane import (
    advance_step,
    get_steps_for_dept,
    get_swimlane_board,
    upsert_step,
)

router = APIRouter(prefix="/api/v1/kds/swimlane", tags=["kds-swimlane"])


class UpsertStepRequest(BaseModel):
    store_id: str
    dept_id: str
    step_name: str
    step_order: int
    color: str = "#4A90D9"
    step_id: Optional[str] = None


class AdvanceStepRequest(BaseModel):
    step_id: str
    operator_id: Optional[str] = None


@router.get("/board")
async def api_swimlane_board(
    dept_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取泳道看板：工序列表 + 各工序下的任务卡片。"""
    board = await get_swimlane_board(
        tenant_id=x_tenant_id,
        dept_id=dept_id,
        db=db,
    )
    return {"ok": True, "data": board}


@router.get("/steps")
async def api_get_steps(
    dept_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询档口的工序定义列表。"""
    steps = await get_steps_for_dept(
        tenant_id=x_tenant_id,
        dept_id=dept_id,
        db=db,
    )
    return {"ok": True, "data": {"items": steps}}


@router.post("/steps")
async def api_upsert_step(
    body: UpsertStepRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """新增或更新工序定义（管理员操作）。"""
    result = await upsert_step(
        tenant_id=x_tenant_id,
        store_id=body.store_id,
        dept_id=body.dept_id,
        step_name=body.step_name,
        step_order=body.step_order,
        color=body.color,
        step_id=body.step_id,
        db=db,
    )
    return {"ok": True, "data": result}


@router.post("/tasks/{task_id}/advance")
async def api_advance_step(
    task_id: str,
    body: AdvanceStepRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """推进工序：完成当前工序，自动激活下一道工序。"""
    try:
        result = await advance_step(
            tenant_id=x_tenant_id,
            task_id=task_id,
            step_id=body.step_id,
            operator_id=body.operator_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
