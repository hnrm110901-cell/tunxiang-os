"""
BFF 考试中心聚合路由

  GET /api/v1/bff/hr/exam-center/{employee_id}
    一次请求返回三列：pending / in_progress / completed

设计原则：
  - 聚合读写分离：只读不改
  - 子调用失败不阻塞整屏 → 降级返回空列表
  - 不缓存（考试进行中需要秒级新鲜度），老板/HR 批量扫描频率低
"""

from __future__ import annotations

from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException

from ..core.dependencies import get_db
from ..services.exam_center_service import ExamCenterService

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/bff/hr", tags=["BFF-考试中心"])


@router.get("/exam-center/{employee_id}")
async def get_my_exam_center(employee_id: str, db=Depends(get_db)) -> Dict[str, Any]:
    """返回某员工的考试中心三列看板数据。"""
    if not employee_id or not employee_id.strip():
        raise HTTPException(status_code=400, detail="employee_id 不能为空")
    try:
        data = await ExamCenterService.get_my_exam_center(db, employee_id)
    except Exception as e:  # noqa: BLE001
        logger.error("bff.exam_center.failed", employee_id=employee_id, err=str(e))
        # 降级返回空结构，不让前端整屏崩
        data = {"pending": [], "in_progress": [], "completed": []}
    return {"success": True, "data": data}
