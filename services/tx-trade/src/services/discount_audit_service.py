"""折扣审计链 Service

职责：
  1. record_discount_action() — 记录折扣/赠品/退菜操作（供其他 service 调用的 hook）
  2. get_audit_log()          — 查询审计记录（支持多维度过滤）
  3. get_high_risk_summary()  — 高风险折扣汇总（折扣率超过阈值的记录聚合）
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.discount_audit_log import DiscountAuditLog

logger = structlog.get_logger(__name__)

VALID_ACTION_TYPES = frozenset({
    "discount_pct", "discount_amt", "gift_item",
    "return_item", "free_order", "price_override", "coupon",
})


class DiscountAuditService:
    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)

    # ──────────────────────────────────────────────────────────
    #  内部 hook：供其他 service 调用，不单独对外暴露
    # ──────────────────────────────────────────────────────────

    async def record_discount_action(
        self,
        *,
        store_id: str,
        order_id: str,
        operator_id: str,
        operator_name: str,
        action_type: str,
        original_amount: Decimal,
        final_amount: Decimal,
        order_item_id: Optional[str] = None,
        approver_id: Optional[str] = None,
        approver_name: Optional[str] = None,
        reason: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
        device_id: Optional[str] = None,
    ) -> dict[str, Any]:
        if action_type not in VALID_ACTION_TYPES:
            raise ValueError(
                f"Invalid action_type '{action_type}'. "
                f"Must be one of: {sorted(VALID_ACTION_TYPES)}"
            )

        discount_amount = original_amount - final_amount

        try:
            record = DiscountAuditLog(
                tenant_id=self.tenant_id,
                store_id=uuid.UUID(store_id),
                order_id=uuid.UUID(order_id),
                order_item_id=uuid.UUID(order_item_id) if order_item_id else None,
                operator_id=uuid.UUID(operator_id),
                operator_name=operator_name,
                approver_id=uuid.UUID(approver_id) if approver_id else None,
                approver_name=approver_name,
                action_type=action_type,
                original_amount=original_amount,
                final_amount=final_amount,
                discount_amount=discount_amount,
                reason=reason,
                extra=extra,
                device_id=device_id,
            )
            self.db.add(record)
            await self.db.flush()
            await self.db.refresh(record)

            log = logger.bind(
                audit_id=str(record.id),
                tenant_id=str(self.tenant_id),
                store_id=store_id,
                action_type=action_type,
                discount_amount=str(discount_amount),
            )
            log.info("discount_audit_recorded")

            return _row_to_dict(record)

        except SQLAlchemyError as exc:
            logger.error("discount_audit_record_failed", error=str(exc))
            raise

    # ──────────────────────────────────────────────────────────
    #  查询审计记录
    # ──────────────────────────────────────────────────────────

    async def get_audit_log(
        self,
        *,
        store_id: Optional[str] = None,
        operator_id: Optional[str] = None,
        action_type: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        min_discount_amount: Optional[Decimal] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        stmt = (
            select(DiscountAuditLog)
            .where(
                DiscountAuditLog.tenant_id == self.tenant_id,
                DiscountAuditLog.is_deleted.is_(False),
            )
            .order_by(DiscountAuditLog.created_at.desc())
        )

        if store_id:
            stmt = stmt.where(DiscountAuditLog.store_id == uuid.UUID(store_id))
        if operator_id:
            stmt = stmt.where(DiscountAuditLog.operator_id == uuid.UUID(operator_id))
        if action_type:
            if action_type not in VALID_ACTION_TYPES:
                raise ValueError(f"Invalid action_type: {action_type}")
            stmt = stmt.where(DiscountAuditLog.action_type == action_type)
        if date_from:
            stmt = stmt.where(DiscountAuditLog.created_at >= date_from)
        if date_to:
            stmt = stmt.where(DiscountAuditLog.created_at <= date_to)
        if min_discount_amount is not None:
            stmt = stmt.where(DiscountAuditLog.discount_amount >= min_discount_amount)

        count_stmt = select(func.count()).select_from(stmt.subquery())

        try:
            total_result = await self.db.execute(count_stmt)
            total = total_result.scalar_one()

            offset = (page - 1) * size
            page_stmt = stmt.offset(offset).limit(size)
            rows = await self.db.execute(page_stmt)
            items = [_row_to_dict(r) for r in rows.scalars().all()]

            return {"items": items, "total": total, "page": page, "size": size}

        except SQLAlchemyError as exc:
            logger.error("discount_audit_query_failed", error=str(exc))
            raise

    # ──────────────────────────────────────────────────────────
    #  高风险折扣汇总
    # ──────────────────────────────────────────────────────────

    async def get_high_risk_summary(
        self,
        *,
        store_id: Optional[str] = None,
        threshold_pct: int = 30,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """按 operator_id 聚合高折扣操作频次

        高风险条件：discount_amount / original_amount >= threshold_pct / 100
        """
        # Build base WHERE conditions as raw SQL fragments
        conditions = [
            "tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID",
            "is_deleted = FALSE",
            "original_amount > 0",
            f"discount_amount / original_amount >= {threshold_pct}::NUMERIC / 100",
        ]
        params: dict[str, Any] = {}

        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = uuid.UUID(store_id)
        if date_from:
            conditions.append("created_at >= :date_from")
            params["date_from"] = date_from
        if date_to:
            conditions.append("created_at <= :date_to")
            params["date_to"] = date_to

        where_clause = " AND ".join(conditions)

        sql = text(f"""
            SELECT
                operator_id,
                operator_name,
                COUNT(*)                            AS high_risk_count,
                SUM(discount_amount)                AS total_discount_amount,
                AVG(discount_amount / original_amount * 100)  AS avg_discount_pct,
                MAX(created_at)                     AS last_action_at
            FROM discount_audit_log
            WHERE {where_clause}
            GROUP BY operator_id, operator_name
            ORDER BY high_risk_count DESC
        """)

        try:
            result = await self.db.execute(sql, params)
            rows = result.mappings().all()
            summary = [
                {
                    "operator_id": str(r["operator_id"]),
                    "operator_name": r["operator_name"],
                    "high_risk_count": int(r["high_risk_count"]),
                    "total_discount_amount": str(r["total_discount_amount"]),
                    "avg_discount_pct": round(float(r["avg_discount_pct"]), 1),
                    "last_action_at": r["last_action_at"].isoformat() if r["last_action_at"] else None,
                }
                for r in rows
            ]
            return {
                "summary": summary,
                "threshold_pct": threshold_pct,
                "total_operators": len(summary),
            }

        except SQLAlchemyError as exc:
            logger.error("high_risk_summary_failed", error=str(exc))
            raise


# ──────────────────────────────────────────────────────────
#  helpers
# ──────────────────────────────────────────────────────────

def _row_to_dict(row: DiscountAuditLog) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "store_id": str(row.store_id),
        "order_id": str(row.order_id),
        "order_item_id": str(row.order_item_id) if row.order_item_id else None,
        "operator_id": str(row.operator_id),
        "operator_name": row.operator_name,
        "approver_id": str(row.approver_id) if row.approver_id else None,
        "approver_name": row.approver_name,
        "action_type": row.action_type,
        "original_amount": str(row.original_amount),
        "final_amount": str(row.final_amount),
        "discount_amount": str(row.discount_amount),
        "discount_pct": (
            round(float(row.discount_amount) / float(row.original_amount) * 100, 1)
            if row.original_amount else 0.0
        ),
        "reason": row.reason,
        "extra": row.extra,
        "device_id": row.device_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "is_deleted": row.is_deleted,
    }
