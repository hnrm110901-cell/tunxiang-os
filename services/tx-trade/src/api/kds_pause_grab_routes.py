"""KDS 停菜 & 抢单 API 路由"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..services.kds_pause_grab import grab_task, pause_task, resume_task

router = APIRouter(prefix="/api/v1/kds/tickets", tags=["kds-pause-grab"])


class PauseRequest(BaseModel):
    operator_id: Optional[str] = None


class GrabRequest(BaseModel):
    operator_id: str


@router.post("/{ticket_id}/pause")
async def api_pause_task(
    ticket_id: str,
    body: PauseRequest,
    db: AsyncSession = Depends(get_db),
):
    """停菜：标记任务暂缓出品（不影响正在制作的状态，仅加停菜标记）。

    适用于：半成品做好了但顾客示意稍等、后厨半成品过多需要控速。
    """
    try:
        result = await pause_task(
            task_id=ticket_id,
            operator_id=body.operator_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{ticket_id}/resume")
async def api_resume_task(
    ticket_id: str,
    body: PauseRequest,
    db: AsyncSession = Depends(get_db),
):
    """恢复停菜：解除暂停标记，任务重新进入出品队列。"""
    try:
        result = await resume_task(
            task_id=ticket_id,
            operator_id=body.operator_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{ticket_id}/grab")
async def api_grab_task(
    ticket_id: str,
    body: GrabRequest,
    db: AsyncSession = Depends(get_db),
):
    """抢单：厨师主动认领 pending 任务并立即开始制作。

    先到先得，乐观并发控制防止两人同时抢同一单。
    抢单归属记录到 grabbed_by，作为绩效计件依据。
    """
    try:
        result = await grab_task(
            task_id=ticket_id,
            operator_id=body.operator_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
