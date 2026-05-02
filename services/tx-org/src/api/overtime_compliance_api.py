"""加班合规 API 路由

Sprint B1: 劳动法第41条 — 月加班不超过 36h。

端点清单：
  POST /api/v1/org/overtime/check          — 检查加班合规
  POST /api/v1/org/overtime/override        — 覆盖冻结（HRD/CEO 双签）
  GET  /api/v1/org/overtime/blocks          — 查询排班冻结

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.overtime_compliance_service import (
    check_and_block,
    get_blocks,
    get_monthly_overtime,
    override_block,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/org/overtime",
    tags=["overtime-compliance"],
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    from sqlalchemy import text
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class OvertimeCheckRequest(BaseModel):
    employee_id: str = Field(..., description="员工 ID")
    block_date: str = Field(
        ..., description="待检查的日期 (YYYY-MM-DD), 如需冻结则冻结此日"
    )


class OvertimeOverrideRequest(BaseModel):
    block_id: str = Field(..., description="冻结记录 ID")
    override_by: str = Field(..., description="审批人 ID（HRD 或 CEO）")
    reason: str = Field(..., description="覆盖原因", max_length=256)


class OvertimeSummaryResponse(BaseModel):
    employee_id: str
    year_month: str
    overtime_hours: float


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/check")
async def check_overtime_compliance(
    body: OvertimeCheckRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """检查加班合规，必要时自动冻结排班。

    流程：
    1. 查询员工当月累计加班小时
    2. >= 36h → 自动冻结该日排班，返回 blocked=True
    3. >= 32h → 返回 warning（不冻结）
    4. < 32h → 正常
    """
    await _set_tenant(db, x_tenant_id)

    try:
        parsed_date = date.fromisoformat(body.block_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"日期格式无效: {exc}")

    result = await check_and_block(
        db=db,
        tenant_id=x_tenant_id,
        employee_id=body.employee_id,
        block_date=parsed_date,
    )

    logger.info(
        "overtime_checked",
        employee_id=body.employee_id,
        overtime_hours=result.overtime_hours,
        blocked=result.blocked,
    )

    if not result.ok and result.blocked:
        # 触发冻结，返回 200（业务层面上是合规拦截，非系统错误）
        return _ok({
            "employee_id": body.employee_id,
            "block_date": body.block_date,
            "overtime_hours": result.overtime_hours,
            "blocked": True,
            "block_id": result.block_id,
            "warning": result.warning,
        })

    return _ok({
        "employee_id": body.employee_id,
        "block_date": body.block_date,
        "overtime_hours": result.overtime_hours,
        "blocked": False,
        "warning": result.warning,
    })


@router.post("/override")
async def override_overtime_block(
    body: OvertimeOverrideRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """HRD/CEO 双签覆盖排班冻结。

    需要 HRD 或 CEO 级别的审批权限（由调用方确保）。
    """
    await _set_tenant(db, x_tenant_id)

    success = await override_block(
        db=db,
        tenant_id=x_tenant_id,
        block_id=body.block_id,
        override_by=body.override_by,
        reason=body.reason,
    )

    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"冻结记录 {body.block_id} 不存在或已删除",
        )

    logger.info(
        "overtime_override_applied",
        block_id=body.block_id,
        override_by=body.override_by,
    )

    return _ok({
        "block_id": body.block_id,
        "overridden": True,
        "override_by": body.override_by,
    })


@router.get("/blocks")
async def list_overtime_blocks(
    employee_id: Optional[str] = Query(None, description="按员工筛选"),
    month: Optional[str] = Query(None, description="按月份筛选 (YYYY-MM)"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询排班冻结记录。

    可按员工 ID 和月份筛选。
    返回按冻结日期倒序排列的列表。
    """
    await _set_tenant(db, x_tenant_id)

    items = await get_blocks(
        db=db,
        tenant_id=x_tenant_id,
        employee_id=employee_id,
        month=month,
    )

    return _ok({
        "items": items,
        "total": len(items),
    })
