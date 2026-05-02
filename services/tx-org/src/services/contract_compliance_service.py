"""
ContractComplianceService — 劳动合同合规服务

劳动合同法第10条：建立劳动关系应当订立书面劳动合同。
逾期不签罚款风险：2N 人均 1.6 万。

功能:
  - 员工合同档案管理（查询）
  - 到期合同预警（expiring_soon）
  - 续签提醒发送
  - 合同合规率统计
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ContractRecord:
    """劳动合同记录。"""
    id: str
    tenant_id: str
    employee_id: str
    contract_type: str
    signed_at: date | None
    expires_at: date | None
    file_path: str | None
    status: str
    reminder_sent: bool
    created_at: datetime


CONTRACT_STATUS_VALUES = frozenset({
    "active", "expiring_soon", "expired", "terminated",
})

CONTRACT_TYPE_VALUES = frozenset({
    "fixed_term", "open_ended", "probation",
})


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _serialize_row(row: Any) -> dict[str, Any]:
    """将 SQLAlchemy 行转为可 JSON 序列化的 dict。"""
    item = dict(row._mapping)
    for key in ("signed_at", "expires_at"):
        if isinstance(item.get(key), date):
            item[key] = item[key].isoformat()
    for key in ("created_at",):
        if isinstance(item.get(key), datetime):
            item[key] = item[key].isoformat()
    return item


# ---------------------------------------------------------------------------
# 服务函数
# ---------------------------------------------------------------------------


async def get_employee_contracts(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str,
) -> list[dict[str, Any]]:
    """查询员工的所有劳动合同。

    Returns:
        该员工的所有合同记录，按创建时间倒序
    """
    await _set_tenant(db, tenant_id)

    try:
        rows = await db.execute(
            text("""
                SELECT id, tenant_id, employee_id, contract_type,
                       signed_at, expires_at, file_path, status,
                       reminder_sent, created_at
                FROM employee_labor_contracts
                WHERE tenant_id = :tenant_id
                  AND employee_id = :employee_id
                  AND is_deleted = FALSE
                ORDER BY created_at DESC
            """),
            {"tenant_id": tenant_id, "employee_id": employee_id},
        )
        return [_serialize_row(r) for r in rows]

    except SQLAlchemyError as exc:
        logger.error(
            "get_employee_contracts_failed",
            tenant_id=tenant_id,
            employee_id=employee_id,
            error=str(exc),
            exc_info=True,
        )
        return []


async def check_expiring_contracts(
    db: AsyncSession,
    tenant_id: str,
    days: int = 30,
) -> list[dict[str, Any]]:
    """查询未来 N 天内到期的合同。

    将状态为 active 且 expires_at 在 days 天内的合同标记为 expiring_soon。

    Returns:
        即将到期的合同列表
    """
    await _set_tenant(db, tenant_id)

    try:
        # 1. 查出即将到期的合同
        rows = await db.execute(
            text("""
                SELECT id, tenant_id, employee_id, contract_type,
                       signed_at, expires_at, file_path, status,
                       reminder_sent, created_at
                FROM employee_labor_contracts
                WHERE tenant_id = :tenant_id
                  AND status = 'active'
                  AND expires_at IS NOT NULL
                  AND expires_at <= CURRENT_DATE + :days
                  AND expires_at >= CURRENT_DATE
                  AND is_deleted = FALSE
                ORDER BY expires_at ASC
            """),
            {"tenant_id": tenant_id, "days": days},
        )
        contracts = [_serialize_row(r) for r in rows]

        # 2. 将 active 标记为 expiring_soon
        contract_ids = [c["id"] for c in contracts]
        if contract_ids:
            await db.execute(
                text("""
                    UPDATE employee_labor_contracts
                    SET status = 'expiring_soon'
                    WHERE id = ANY(:ids)
                      AND tenant_id = :tenant_id
                      AND status = 'active'
                """),
                {"ids": contract_ids, "tenant_id": tenant_id},
            )
            await db.commit()
            logger.info(
                "contracts_marked_expiring",
                count=len(contract_ids),
                days=days,
            )

        return contracts

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "check_expiring_contracts_failed",
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        return []


async def send_reminder(
    db: AsyncSession,
    tenant_id: str,
    contract_id: str,
) -> bool:
    """发送续签提醒（标记 reminder_sent）。

    实际发送逻辑（短信/企微通知）由调用方实现，
    本函数仅更新数据库标记。

    Returns:
        True 提醒发送成功，False 合同不存在
    """
    await _set_tenant(db, tenant_id)

    try:
        result = await db.execute(
            text("""
                UPDATE employee_labor_contracts
                SET reminder_sent = TRUE
                WHERE id = :contract_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """),
            {"contract_id": contract_id, "tenant_id": tenant_id},
        )
        await db.commit()

        if result.rowcount == 0:
            logger.warning("send_reminder_contract_not_found", contract_id=contract_id)
            return False

        logger.info("contract_reminder_sent", contract_id=contract_id)
        return True

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "send_reminder_failed",
            contract_id=contract_id,
            error=str(exc),
            exc_info=True,
        )
        return False


async def check_compliance_rate(
    db: AsyncSession,
    tenant_id: str,
) -> dict[str, Any]:
    """合同合规率统计。

    统计指标:
    - total_employees: 有合同的员工总数
    - active: 正常合同数
    - expiring_soon: 即将到期数
    - expired: 已过期数
    - terminated: 已终止数
    - compliance_rate: 合规率（active / total * 100）
    - no_contract: 无合同员工数（需配合 employee 表查询）

    Returns:
        合规率统计 dict
    """
    await _set_tenant(db, tenant_id)

    try:
        # 按状态统计
        rows = await db.execute(
            text("""
                SELECT status, COUNT(*) AS cnt
                FROM employee_labor_contracts
                WHERE tenant_id = :tenant_id
                  AND is_deleted = FALSE
                GROUP BY status
            """),
            {"tenant_id": tenant_id},
        )
        status_counts: dict[str, int] = {}
        for r in rows:
            status_counts[r.status] = r.cnt

        active = status_counts.get("active", 0)
        expiring_soon = status_counts.get("expiring_soon", 0)
        expired = status_counts.get("expired", 0)
        terminated = status_counts.get("terminated", 0)
        total = active + expiring_soon + expired + terminated

        compliance_rate = round(active / total * 100, 1) if total > 0 else 0.0

        return {
            "total_contracts": total,
            "active": active,
            "expiring_soon": expiring_soon,
            "expired": expired,
            "terminated": terminated,
            "compliance_rate": compliance_rate,
        }

    except SQLAlchemyError as exc:
        logger.error(
            "check_compliance_rate_failed",
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        return {
            "total_contracts": 0,
            "active": 0,
            "expiring_soon": 0,
            "expired": 0,
            "terminated": 0,
            "compliance_rate": 0.0,
            "error": str(exc),
        }
