"""劳动合同合规 API 路由

Sprint B4: 劳动合同法第10条 — 逾期不签 2N 罚款风险。

端点清单：
  GET  /api/v1/org/contracts/{employee_id}        — 查询员工合同
  GET  /api/v1/org/contracts/expiring             — 到期预警
  POST /api/v1/org/contracts/{contract_id}/remind — 发送续签提醒

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.contract_compliance_service import (
    check_compliance_rate,
    check_expiring_contracts,
    get_employee_contracts,
    send_reminder,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/org/contracts",
    tags=["contract-compliance"],
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
# Routes
# ---------------------------------------------------------------------------


@router.get("/{employee_id}")
async def list_employee_contracts(
    employee_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询指定员工的所有劳动合同。

    返回该员工的所有合同记录（固定期限、无固定期限、试用期），
    按创建时间倒序排列。
    """
    await _set_tenant(db, x_tenant_id)

    contracts = await get_employee_contracts(
        db=db,
        tenant_id=x_tenant_id,
        employee_id=employee_id,
    )

    logger.info(
        "employee_contracts_queried",
        employee_id=employee_id,
        count=len(contracts),
    )

    return _ok({
        "employee_id": employee_id,
        "contracts": contracts,
        "total": len(contracts),
    })


@router.get("/expiring")
async def list_expiring_contracts(
    days: int = Query(default=30, ge=1, le=365, description="预警天数"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询即将到期的劳动合同。

    返回未来指定天数内到期的合同列表（按到期日升序），
    同时将状态自动更新为 expiring_soon。
    """
    await _set_tenant(db, x_tenant_id)

    contracts = await check_expiring_contracts(
        db=db,
        tenant_id=x_tenant_id,
        days=days,
    )

    logger.info(
        "expiring_contracts_queried",
        days=days,
        count=len(contracts),
    )

    return _ok({
        "days": days,
        "contracts": contracts,
        "total": len(contracts),
    })


@router.post("/{contract_id}/remind")
async def remind_contract_renewal(
    contract_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """发送合同续签提醒。

    标记该合同的 reminder_sent = True。
    实际通知发送（短信、企微消息等）需由调用方实现。
    """
    await _set_tenant(db, x_tenant_id)

    success = await send_reminder(
        db=db,
        tenant_id=x_tenant_id,
        contract_id=contract_id,
    )

    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"合同 {contract_id} 不存在或已删除",
        )

    logger.info("contract_reminder_triggered", contract_id=contract_id)

    return _ok({
        "contract_id": contract_id,
        "reminder_sent": True,
    })
