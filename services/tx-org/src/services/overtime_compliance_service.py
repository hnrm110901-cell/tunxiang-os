"""
OvertimeComplianceService — 加班合规管控

硬约束：月累计加班不超过 36h。
超过 32h 时触发预警，超过 36h 时自动冻结排班。
HRD+CEO 双签可覆盖冻结。

劳动法依据：劳动法第四十一条。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

OVERTIME_WARNING_THRESHOLD = 32  # 预警阈值（小时）
OVERTIME_BLOCK_THRESHOLD = 36  # 冻结阈值（小时）


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ComplianceResult:
    """加班合规检查结果。"""
    ok: bool
    blocked: bool
    warning: str | None
    overtime_hours: float
    block_id: str | None = None


@dataclass
class OvertimeSummary:
    employee_id: str
    year_month: date
    total_overtime_hours: float
    last_calculated_at: datetime


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


async def get_monthly_overtime(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str,
    year_month: date,
) -> float:
    """查询员工指定月份的累计加班小时数。

    先从 monthly_overtime_summary 查询，若无记录则返回 0。
    """
    await _set_tenant(db, tenant_id)
    try:
        result = await db.execute(
            text("""
                SELECT total_overtime_hours
                FROM monthly_overtime_summary
                WHERE tenant_id = :tenant_id
                  AND employee_id = :employee_id
                  AND year_month = :year_month
                  AND is_deleted = FALSE
            """),
            {
                "tenant_id": tenant_id,
                "employee_id": employee_id,
                "year_month": year_month,
            },
        )
        row = result.mappings().first()
        if row:
            return float(row["total_overtime_hours"])
        return 0.0
    except SQLAlchemyError as exc:
        logger.error(
            "get_monthly_overtime_failed",
            tenant_id=tenant_id,
            employee_id=employee_id,
            error=str(exc),
            exc_info=True,
        )
        return 0.0


async def upsert_monthly_overtime(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str,
    year_month: date,
    total_hours: float,
) -> bool:
    """更新或插入月度加班累计。"""
    await _set_tenant(db, tenant_id)
    try:
        await db.execute(
            text("""
                INSERT INTO monthly_overtime_summary
                    (id, tenant_id, employee_id, year_month,
                     total_overtime_hours, last_calculated_at)
                VALUES
                    (:id, :tenant_id, :employee_id, :year_month,
                     :total_hours, NOW())
                ON CONFLICT (employee_id, year_month)
                DO UPDATE SET
                    total_overtime_hours = EXCLUDED.total_overtime_hours,
                    last_calculated_at = NOW()
            """),
            {
                "id": str(uuid4()),
                "tenant_id": tenant_id,
                "employee_id": employee_id,
                "year_month": year_month,
                "total_hours": total_hours,
            },
        )
        await db.commit()
        return True
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "upsert_monthly_overtime_failed",
            tenant_id=tenant_id,
            employee_id=employee_id,
            error=str(exc),
            exc_info=True,
        )
        return False


async def check_and_block(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str,
    block_date: date,
) -> ComplianceResult:
    """检查加班合规性，必要时自动冻结排班。

    流程:
    1. 查询当月累计加班小时
    2. >= 36h → 写入 schedule_compliance_blocks 冻结该日排班
    3. >= 32h → 返回 warning
    4. < 32h → 正常
    """
    await _set_tenant(db, tenant_id)

    # 计算所属月份（每月 1 日）
    year_month = block_date.replace(day=1)

    try:
        overtime_hours = await get_monthly_overtime(
            db, tenant_id, employee_id, year_month,
        )

        # 检查是否已达冻结阈值
        if overtime_hours >= OVERTIME_BLOCK_THRESHOLD:
            block_id = str(uuid4())
            reason = (
                f"本月已累计加班{overtime_hours}h，"
                f"超出{OVERTIME_BLOCK_THRESHOLD}h阈值"
            )
            await db.execute(
                text("""
                    INSERT INTO schedule_compliance_blocks
                        (id, tenant_id, employee_id, block_date, reason, created_at)
                    VALUES
                        (:id, :tenant_id, :employee_id, :block_date, :reason, NOW())
                    ON CONFLICT (employee_id, block_date) DO NOTHING
                """),
                {
                    "id": block_id,
                    "tenant_id": tenant_id,
                    "employee_id": employee_id,
                    "block_date": block_date,
                    "reason": reason,
                },
            )
            await db.commit()
            logger.warning(
                "overtime_block_created",
                employee_id=employee_id,
                block_date=str(block_date),
                overtime_hours=overtime_hours,
            )
            return ComplianceResult(
                ok=False,
                blocked=True,
                warning=f"已冻结：{reason}",
                overtime_hours=overtime_hours,
                block_id=block_id,
            )

        # 检查是否接近阈值
        if overtime_hours >= OVERTIME_WARNING_THRESHOLD:
            warning_msg = (
                f"本月已累计加班{overtime_hours}h，"
                f"接近{OVERTIME_BLOCK_THRESHOLD}h上限（预警线{OVERTIME_WARNING_THRESHOLD}h）"
            )
            logger.warning(
                "overtime_near_threshold",
                employee_id=employee_id,
                overtime_hours=overtime_hours,
            )
            return ComplianceResult(
                ok=True,
                blocked=False,
                warning=warning_msg,
                overtime_hours=overtime_hours,
            )

        return ComplianceResult(
            ok=True,
            blocked=False,
            warning=None,
            overtime_hours=overtime_hours,
        )

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "check_and_block_failed",
            tenant_id=tenant_id,
            employee_id=employee_id,
            error=str(exc),
            exc_info=True,
        )
        return ComplianceResult(
            ok=False,
            blocked=False,
            warning=f"检查失败：{exc}",
            overtime_hours=0.0,
        )


async def override_block(
    db: AsyncSession,
    tenant_id: str,
    block_id: str,
    override_by: str,
    reason: str,
) -> bool:
    """HRD/CEO 双签覆盖冻结。

    Args:
        block_id: 冻结记录 ID
        override_by: 审批人 ID（HRD 或 CEO）
        reason: 覆盖原因

    Returns:
        True 覆盖成功，False 记录不存在
    """
    await _set_tenant(db, tenant_id)
    try:
        result = await db.execute(
            text("""
                UPDATE schedule_compliance_blocks
                SET override_by = :override_by,
                    override_reason = :reason
                WHERE id = :block_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """),
            {
                "block_id": block_id,
                "tenant_id": tenant_id,
                "override_by": override_by,
                "reason": reason,
            },
        )
        await db.commit()
        if result.rowcount == 0:
            logger.warning("override_block_not_found", block_id=block_id)
            return False

        logger.info(
            "overtime_block_overridden",
            block_id=block_id,
            override_by=override_by,
        )
        return True

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "override_block_failed",
            block_id=block_id,
            error=str(exc),
            exc_info=True,
        )
        return False


async def get_blocks(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str | None = None,
    month: str | None = None,
) -> list[dict[str, Any]]:
    """查询排班冻结记录。

    Args:
        employee_id: 可选，按员工筛选
        month: 可选，按月份筛选 (YYYY-MM)
    """
    await _set_tenant(db, tenant_id)
    conditions = ["tenant_id = :tenant_id", "is_deleted = FALSE"]
    params: dict[str, Any] = {"tenant_id": tenant_id}

    if employee_id:
        conditions.append("employee_id = :employee_id")
        params["employee_id"] = employee_id

    if month:
        conditions.append("to_char(block_date, 'YYYY-MM') = :month")
        params["month"] = month

    where_clause = " AND ".join(conditions)

    try:
        rows = await db.execute(
            text(f"""
                SELECT id, employee_id, block_date, reason,
                       override_by, override_reason, created_at
                FROM schedule_compliance_blocks
                WHERE {where_clause}
                ORDER BY block_date DESC, created_at DESC
            """),
            params,
        )
        items = [dict(r._mapping) for r in rows]

        # 将 datetime/date 转为 isoformat
        for item in items:
            for key in ("block_date", "created_at"):
                if isinstance(item.get(key), (date, datetime)):
                    item[key] = item[key].isoformat()

        return items

    except SQLAlchemyError as exc:
        logger.error(
            "get_blocks_failed",
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        return []
