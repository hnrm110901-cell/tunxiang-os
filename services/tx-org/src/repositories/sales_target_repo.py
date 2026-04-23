"""销售目标与进度仓储层（Repository）

对应表（v266_sales_targets）：
  sales_targets   — 目标设定
  sales_progress  — 进度快照

遵循：
  - CLAUDE.md §10：Service → Repository → DB
  - CLAUDE.md §14：所有查询必须带 tenant_id（RLS 已由 app.tenant_id 保底）
  - CLAUDE.md §15：金额字段单位为分（整数），achievement_rate 用 Decimal

本文件只负责 SQL 访问（增删改查），业务规则在 sales_target_service.py。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────────────────────────────────────


def _row_to_target(row: Any) -> dict:
    """将 SQLAlchemy Row 转为 dict（兼容 _mapping 和属性访问）。"""
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return dict(mapping)
    # 兜底属性读取
    keys = (
        "target_id",
        "tenant_id",
        "store_id",
        "employee_id",
        "period_type",
        "period_start",
        "period_end",
        "metric_type",
        "target_value",
        "parent_target_id",
        "notes",
        "created_by",
        "created_at",
        "updated_at",
    )
    return {k: getattr(row, k, None) for k in keys}


def _row_to_progress(row: Any) -> dict:
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return dict(mapping)
    keys = (
        "progress_id",
        "tenant_id",
        "target_id",
        "actual_value",
        "achievement_rate",
        "snapshot_at",
        "source_event_id",
        "created_at",
    )
    return {k: getattr(row, k, None) for k in keys}


# ─────────────────────────────────────────────────────────────────────────────
# Repository
# ─────────────────────────────────────────────────────────────────────────────


class SalesTargetRepository:
    """sales_targets + sales_progress 仓储。"""

    # ── 目标写入 ────────────────────────────────────────────────────────

    async def insert_target(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        employee_id: UUID,
        period_type: str,
        period_start: date,
        period_end: date,
        metric_type: str,
        target_value: int,
        store_id: UUID | None = None,
        parent_target_id: UUID | None = None,
        notes: str | None = None,
        created_by: UUID | None = None,
    ) -> dict:
        """插入一条销售目标，返回包含 target_id/created_at 的 dict。

        依赖 DB 侧 UNIQUE (tenant_id, employee_id, period_type, period_start, metric_type)
        触发唯一约束时交由调用方捕获并转换为业务异常。
        """
        target_id = uuid4()
        sql = text(
            """
            INSERT INTO sales_targets
                (target_id, tenant_id, store_id, employee_id,
                 period_type, period_start, period_end, metric_type,
                 target_value, parent_target_id, notes, created_by,
                 created_at, updated_at)
            VALUES
                (:target_id, :tenant_id, :store_id, :employee_id,
                 :period_type, :period_start, :period_end, :metric_type,
                 :target_value, :parent_target_id, :notes, :created_by,
                 NOW(), NOW())
            RETURNING target_id, tenant_id, store_id, employee_id,
                      period_type, period_start, period_end, metric_type,
                      target_value, parent_target_id, notes, created_by,
                      created_at, updated_at
            """
        )
        result = await db.execute(
            sql,
            {
                "target_id": str(target_id),
                "tenant_id": str(tenant_id),
                "store_id": str(store_id) if store_id else None,
                "employee_id": str(employee_id),
                "period_type": period_type,
                "period_start": period_start,
                "period_end": period_end,
                "metric_type": metric_type,
                "target_value": int(target_value),
                "parent_target_id": str(parent_target_id) if parent_target_id else None,
                "notes": notes,
                "created_by": str(created_by) if created_by else None,
            },
        )
        row = result.fetchone()
        if row is None:
            # 极端情况：DB 未返回（测试 mock 场景）
            return {
                "target_id": target_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "employee_id": employee_id,
                "period_type": period_type,
                "period_start": period_start,
                "period_end": period_end,
                "metric_type": metric_type,
                "target_value": int(target_value),
                "parent_target_id": parent_target_id,
                "notes": notes,
                "created_by": created_by,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        return _row_to_target(row)

    async def get_by_id(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        target_id: UUID,
    ) -> dict | None:
        sql = text(
            """
            SELECT target_id, tenant_id, store_id, employee_id,
                   period_type, period_start, period_end, metric_type,
                   target_value, parent_target_id, notes, created_by,
                   created_at, updated_at
            FROM sales_targets
            WHERE tenant_id = :tenant_id AND target_id = :target_id
            """
        )
        result = await db.execute(
            sql,
            {"tenant_id": str(tenant_id), "target_id": str(target_id)},
        )
        row = result.fetchone()
        return _row_to_target(row) if row is not None else None

    async def list_by_employee_and_period(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        employee_id: UUID,
        period_type: str | None = None,
        active_only: bool = False,
        today: date | None = None,
    ) -> list[dict]:
        """按员工 + 周期类型查目标。active_only=True 时仅返回 today 在 [start,end] 内的目标。"""
        clauses = ["tenant_id = :tenant_id", "employee_id = :employee_id"]
        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "employee_id": str(employee_id),
        }
        if period_type:
            clauses.append("period_type = :period_type")
            params["period_type"] = period_type
        if active_only:
            clauses.append(":today BETWEEN period_start AND period_end")
            params["today"] = today or date.today()

        sql = text(
            f"""
            SELECT target_id, tenant_id, store_id, employee_id,
                   period_type, period_start, period_end, metric_type,
                   target_value, parent_target_id, notes, created_by,
                   created_at, updated_at
            FROM sales_targets
            WHERE {' AND '.join(clauses)}
            ORDER BY period_start DESC
            """
        )
        result = await db.execute(sql, params)
        rows = result.fetchall()
        return [_row_to_target(r) for r in rows]

    async def list_active_targets(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        period_type: str | None = None,
        today: date | None = None,
    ) -> list[dict]:
        """列出当前生效中的目标（today 落在周期内）。"""
        clauses = [
            "tenant_id = :tenant_id",
            ":today BETWEEN period_start AND period_end",
        ]
        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "today": today or date.today(),
        }
        if period_type:
            clauses.append("period_type = :period_type")
            params["period_type"] = period_type

        sql = text(
            f"""
            SELECT target_id, tenant_id, store_id, employee_id,
                   period_type, period_start, period_end, metric_type,
                   target_value, parent_target_id, notes, created_by,
                   created_at, updated_at
            FROM sales_targets
            WHERE {' AND '.join(clauses)}
            ORDER BY period_start DESC
            """
        )
        result = await db.execute(sql, params)
        rows = result.fetchall()
        return [_row_to_target(r) for r in rows]

    async def list_children(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        parent_target_id: UUID,
    ) -> list[dict]:
        sql = text(
            """
            SELECT target_id, tenant_id, store_id, employee_id,
                   period_type, period_start, period_end, metric_type,
                   target_value, parent_target_id, notes, created_by,
                   created_at, updated_at
            FROM sales_targets
            WHERE tenant_id = :tenant_id AND parent_target_id = :parent
            ORDER BY period_start ASC
            """
        )
        result = await db.execute(
            sql,
            {"tenant_id": str(tenant_id), "parent": str(parent_target_id)},
        )
        rows = result.fetchall()
        return [_row_to_target(r) for r in rows]

    # ── 进度写入与查询 ──────────────────────────────────────────────────

    async def check_source_event_exists(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        target_id: UUID,
        source_event_id: UUID,
    ) -> bool:
        """幂等性校验：同一 source_event_id 是否已写入。"""
        sql = text(
            """
            SELECT 1
            FROM sales_progress
            WHERE tenant_id = :tenant_id
              AND target_id = :target_id
              AND source_event_id = :source_event_id
            LIMIT 1
            """
        )
        result = await db.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "target_id": str(target_id),
                "source_event_id": str(source_event_id),
            },
        )
        row = result.fetchone()
        return row is not None

    async def insert_progress(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        target_id: UUID,
        actual_value: int,
        achievement_rate: Decimal,
        source_event_id: UUID | None = None,
    ) -> dict:
        progress_id = uuid4()
        sql = text(
            """
            INSERT INTO sales_progress
                (progress_id, tenant_id, target_id, actual_value,
                 achievement_rate, snapshot_at, source_event_id, created_at)
            VALUES
                (:progress_id, :tenant_id, :target_id, :actual_value,
                 :achievement_rate, NOW(), :source_event_id, NOW())
            RETURNING progress_id, tenant_id, target_id, actual_value,
                      achievement_rate, snapshot_at, source_event_id, created_at
            """
        )
        result = await db.execute(
            sql,
            {
                "progress_id": str(progress_id),
                "tenant_id": str(tenant_id),
                "target_id": str(target_id),
                "actual_value": int(actual_value),
                "achievement_rate": str(achievement_rate),
                "source_event_id": str(source_event_id) if source_event_id else None,
            },
        )
        row = result.fetchone()
        if row is None:
            return {
                "progress_id": progress_id,
                "tenant_id": tenant_id,
                "target_id": target_id,
                "actual_value": int(actual_value),
                "achievement_rate": achievement_rate,
                "snapshot_at": datetime.now(timezone.utc),
                "source_event_id": source_event_id,
                "created_at": datetime.now(timezone.utc),
            }
        return _row_to_progress(row)

    async def get_latest_progress(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        target_id: UUID,
    ) -> dict | None:
        sql = text(
            """
            SELECT progress_id, tenant_id, target_id, actual_value,
                   achievement_rate, snapshot_at, source_event_id, created_at
            FROM sales_progress
            WHERE tenant_id = :tenant_id AND target_id = :target_id
            ORDER BY snapshot_at DESC
            LIMIT 1
            """
        )
        result = await db.execute(
            sql,
            {"tenant_id": str(tenant_id), "target_id": str(target_id)},
        )
        row = result.fetchone()
        return _row_to_progress(row) if row is not None else None

    async def list_progress_history(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        target_id: UUID,
        limit: int = 100,
    ) -> list[dict]:
        sql = text(
            """
            SELECT progress_id, tenant_id, target_id, actual_value,
                   achievement_rate, snapshot_at, source_event_id, created_at
            FROM sales_progress
            WHERE tenant_id = :tenant_id AND target_id = :target_id
            ORDER BY snapshot_at DESC
            LIMIT :limit
            """
        )
        result = await db.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "target_id": str(target_id),
                "limit": int(limit),
            },
        )
        rows = result.fetchall()
        return [_row_to_progress(r) for r in rows]

    # ── 排行榜聚合 ───────────────────────────────────────────────────────

    async def leaderboard_by_period(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        period_type: str,
        metric_type: str,
        today: date | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """排行榜：同 period_type + metric_type 内，按最新进度 achievement_rate DESC 排序。

        数据来源：sales_targets JOIN sales_progress（取每个 target 最新一条进度）
        """
        sql = text(
            """
            WITH latest AS (
                SELECT DISTINCT ON (sp.target_id)
                    sp.target_id,
                    sp.actual_value,
                    sp.achievement_rate,
                    sp.snapshot_at
                FROM sales_progress sp
                WHERE sp.tenant_id = :tenant_id
                ORDER BY sp.target_id, sp.snapshot_at DESC
            )
            SELECT st.target_id,
                   st.employee_id,
                   st.store_id,
                   st.metric_type,
                   st.period_type,
                   st.period_start,
                   st.period_end,
                   st.target_value,
                   COALESCE(latest.actual_value, 0)      AS actual_value,
                   COALESCE(latest.achievement_rate, 0)  AS achievement_rate,
                   latest.snapshot_at
            FROM sales_targets st
            LEFT JOIN latest ON latest.target_id = st.target_id
            WHERE st.tenant_id = :tenant_id
              AND st.period_type = :period_type
              AND st.metric_type = :metric_type
              AND :today BETWEEN st.period_start AND st.period_end
            ORDER BY achievement_rate DESC, actual_value DESC
            LIMIT :limit
            """
        )
        result = await db.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "period_type": period_type,
                "metric_type": metric_type,
                "today": today or date.today(),
                "limit": int(limit),
            },
        )
        rows = result.fetchall()
        return [
            {
                "target_id": getattr(r, "target_id", None)
                or r._mapping.get("target_id"),
                "employee_id": getattr(r, "employee_id", None)
                or r._mapping.get("employee_id"),
                "store_id": getattr(r, "store_id", None)
                or r._mapping.get("store_id"),
                "metric_type": getattr(r, "metric_type", None)
                or r._mapping.get("metric_type"),
                "period_type": getattr(r, "period_type", None)
                or r._mapping.get("period_type"),
                "period_start": getattr(r, "period_start", None)
                or r._mapping.get("period_start"),
                "period_end": getattr(r, "period_end", None)
                or r._mapping.get("period_end"),
                "target_value": getattr(r, "target_value", None)
                or r._mapping.get("target_value"),
                "actual_value": getattr(r, "actual_value", None)
                or r._mapping.get("actual_value"),
                "achievement_rate": getattr(r, "achievement_rate", None)
                or r._mapping.get("achievement_rate"),
                "snapshot_at": getattr(r, "snapshot_at", None)
                or r._mapping.get("snapshot_at"),
            }
            for r in rows
        ]

    # ── 事件聚合（从 mv_store_pnl 读取实际值） ──────────────────────────

    async def aggregate_metric_from_views(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        store_id: UUID | None,
        metric_type: str,
        period_start: date,
        period_end: date,
    ) -> int:
        """从物化视图聚合指定指标的实际值（Phase 3 读视图，不跨服务查）。

        映射关系：
          revenue_fen        → SUM(gross_revenue_fen)
          order_count        → SUM(order_count)
          table_count        → SUM(order_count)    (门店无桌数视图，用订单数兜底)
          unit_avg_fen       → SUM(gross_revenue_fen) / NULLIF(SUM(order_count),0)
          per_guest_avg_fen  → SUM(avg_check_fen)   (视图已存客单价，直接聚合取均)
          new_customer_count → SUM(customer_count)

        视图不存在或无数据时返回 0（测试环境不强制依赖 v148）。
        """
        metric_to_sql = {
            "revenue_fen": "COALESCE(SUM(gross_revenue_fen), 0)",
            "order_count": "COALESCE(SUM(order_count), 0)",
            "table_count": "COALESCE(SUM(order_count), 0)",
            "unit_avg_fen": (
                "COALESCE(SUM(gross_revenue_fen) / NULLIF(SUM(order_count),0), 0)"
            ),
            "per_guest_avg_fen": "COALESCE(AVG(avg_check_fen), 0)",
            "new_customer_count": "COALESCE(SUM(customer_count), 0)",
        }
        if metric_type not in metric_to_sql:
            raise ValueError(f"未知 metric_type: {metric_type}")

        clauses = [
            "tenant_id = :tenant_id",
            "stat_date BETWEEN :period_start AND :period_end",
        ]
        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "period_start": period_start,
            "period_end": period_end,
        }
        if store_id is not None:
            clauses.append("store_id = :store_id")
            params["store_id"] = str(store_id)

        sql = text(
            f"""
            SELECT {metric_to_sql[metric_type]} AS actual
            FROM mv_store_pnl
            WHERE {' AND '.join(clauses)}
            """
        )
        try:
            result = await db.execute(sql, params)
            row = result.fetchone()
        except Exception as exc:  # noqa: BLE001
            # 视图不存在/权限不足等场景：降级 0，记录告警
            log.warning(
                "sales_target_aggregate_view_unavailable",
                error=str(exc),
                metric_type=metric_type,
            )
            return 0
        if row is None:
            return 0
        value = getattr(row, "actual", None)
        if value is None and hasattr(row, "_mapping"):
            value = row._mapping.get("actual", 0)
        return int(value or 0)
