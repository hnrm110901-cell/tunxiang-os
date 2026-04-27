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

from datetime import date, datetime, timedelta, timezone
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

    # ── 事件聚合（从 mv_store_pnl 读取门店级实际值） ────────────────────
    #
    # 指标分级（P0-2 修复）：
    #   - 门店级指标（store-level）：table_count / unit_avg_fen / per_guest_avg_fen
    #     这些本质是门店粒度（桌数=门店计数；单均/人均=门店维度平均），
    #     给单个员工建这类目标在业务上无法"按员工归属"聚合
    #     → Service 层负责拒绝（要求 employee_id 为门店级哨兵）
    #     → Repository 层仅在 employee_id 为门店级哨兵时通过 mv_store_pnl 聚合
    #   - 员工可归属指标（per-employee）：revenue_fen / order_count / new_customer_count
    #     这些可以按订单归属员工（sales_employee_id/cashier_id）聚合
    #     → 优先从 events 表按 payload 中的归属员工字段过滤
    #     → 若无可用归属字段 → 降级 0 + warning（不再假装给出值）
    #
    # 注：历史实现只用 mv_store_pnl 按 store_id 聚合（不管 employee_id），
    # 导致同店多名销售经理拿到**相同**的 actual_value，直接影响薪资提成。

    # 存储级哨兵：表示"这是门店级目标，不归属任何个人员工"
    # (UUID(int=0) = '00000000-0000-0000-0000-000000000000')
    STORE_LEVEL_SENTINEL_EMPLOYEE_ID = UUID(int=0)

    # 门店级指标（个人无法独立聚合）
    _STORE_LEVEL_METRICS = frozenset(
        {"table_count", "unit_avg_fen", "per_guest_avg_fen"}
    )
    # 可按员工归属聚合的指标
    _PER_EMPLOYEE_METRICS = frozenset(
        {"revenue_fen", "order_count", "new_customer_count"}
    )

    async def aggregate_metric_from_views(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        store_id: UUID | None,
        metric_type: str,
        period_start: date,
        period_end: date,
        employee_id: UUID | None = None,
    ) -> int:
        """按员工归属聚合指标的实际值（P0-2 修复，严格按 employee_id 过滤）。

        聚合策略：
          1. metric_type ∈ 门店级指标（table_count/unit_avg_fen/per_guest_avg_fen）
             - employee_id 必须为 STORE_LEVEL_SENTINEL 或 None，否则拒绝（返回 0 + warn）
             - 从 mv_store_pnl 按 store_id 聚合（门店粒度，无员工维度）
          2. metric_type ∈ 员工可归属指标（revenue_fen/order_count/new_customer_count）
             - 必须传入具体 employee_id（非哨兵）
             - 从 events 表按 payload->>'sales_employee_id' 过滤 order.paid 事件
             - 兼容 payload->>'cashier_id'（收银员归属）作为次选
             - payload 中无任何归属字段时返回 0 + warning（不沉默错配）

        视图/表不存在或权限不足时返回 0 并记录 warning。
        """
        if metric_type in self._STORE_LEVEL_METRICS:
            # 门店级指标：要求 employee_id 为哨兵或 None
            if (
                employee_id is not None
                and employee_id != self.STORE_LEVEL_SENTINEL_EMPLOYEE_ID
            ):
                log.warning(
                    "sales_target_store_level_metric_rejected_individual",
                    metric_type=metric_type,
                    employee_id=str(employee_id),
                    reason=(
                        "门店级指标不支持按个人员工聚合，"
                        "请使用 STORE_LEVEL_SENTINEL_EMPLOYEE_ID 建门店级目标"
                    ),
                )
                return 0
            return await self._aggregate_store_level_from_view(
                db,
                tenant_id=tenant_id,
                store_id=store_id,
                metric_type=metric_type,
                period_start=period_start,
                period_end=period_end,
            )

        if metric_type in self._PER_EMPLOYEE_METRICS:
            if (
                employee_id is None
                or employee_id == self.STORE_LEVEL_SENTINEL_EMPLOYEE_ID
            ):
                # 门店级 revenue/order_count 目标：允许走 mv_store_pnl 总额
                return await self._aggregate_store_level_from_view(
                    db,
                    tenant_id=tenant_id,
                    store_id=store_id,
                    metric_type=metric_type,
                    period_start=period_start,
                    period_end=period_end,
                )
            return await self._aggregate_per_employee_from_events(
                db,
                tenant_id=tenant_id,
                store_id=store_id,
                metric_type=metric_type,
                period_start=period_start,
                period_end=period_end,
                employee_id=employee_id,
            )

        raise ValueError(f"未知 metric_type: {metric_type}")

    async def _aggregate_store_level_from_view(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        store_id: UUID | None,
        metric_type: str,
        period_start: date,
        period_end: date,
    ) -> int:
        """从 mv_store_pnl 按门店维度聚合（门店级目标）。"""
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
        except (ValueError, RuntimeError, LookupError) as exc:
            log.warning(
                "sales_target_aggregate_view_unavailable",
                error=str(exc),
                metric_type=metric_type,
            )
            return 0
        except Exception as exc:  # noqa: BLE001 — 兼容 asyncpg/SQLAlchemy 驱动异常
            log.warning(
                "sales_target_aggregate_view_unavailable",
                error=str(exc),
                metric_type=metric_type,
                exc_info=True,
            )
            return 0
        if row is None:
            return 0
        value = getattr(row, "actual", None)
        if value is None and hasattr(row, "_mapping"):
            value = row._mapping.get("actual", 0)
        return int(value or 0)

    async def _aggregate_per_employee_from_events(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        store_id: UUID | None,
        metric_type: str,
        period_start: date,
        period_end: date,
        employee_id: UUID,
    ) -> int:
        """从 events 表按员工归属聚合（order.paid 事件）。

        归因字段优先级（payload JSONB 读取）：
          1. sales_employee_id — 明确的销售归属（R2 将补齐）
          2. cashier_id        — 收银员归属（v011 orders 字段，当前主用）

        metric 映射：
          revenue_fen        → SUM((payload->>'final_amount_fen')::bigint)
          order_count        → COUNT(*)
          new_customer_count → COUNT(DISTINCT customer_id) where is_new=true
                               （R2 事件扩展字段；当前降级为 COUNT DISTINCT customer_id）

        period_end 按「含」语义：occurred_at < (period_end + 1 day)
        """
        # period_end 是"含"当天，转为排他上界
        period_end_exclusive = period_end + timedelta(days=1)

        metric_sql: dict[str, str] = {
            "revenue_fen": (
                "COALESCE(SUM((payload->>'final_amount_fen')::bigint), 0)"
            ),
            "order_count": "COUNT(*)",
            "new_customer_count": (
                "COUNT(DISTINCT NULLIF(payload->>'customer_id', ''))"
            ),
        }
        if metric_type not in metric_sql:
            raise ValueError(
                f"metric_type {metric_type!r} 不是员工可归属指标"
            )

        clauses = [
            "tenant_id = :tenant_id",
            "event_type = 'order.paid'",
            "occurred_at >= :period_start",
            "occurred_at < :period_end_exclusive",
            # 按员工归属过滤：优先 sales_employee_id，回退 cashier_id
            "("
            "payload->>'sales_employee_id' = :employee_id "
            "OR (payload->>'sales_employee_id' IS NULL "
            "    AND payload->>'cashier_id' = :employee_id)"
            ")",
        ]
        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "period_start": period_start,
            "period_end_exclusive": period_end_exclusive,
            "employee_id": str(employee_id),
        }
        if store_id is not None:
            clauses.append("store_id = :store_id")
            params["store_id"] = str(store_id)

        sql = text(
            f"""
            SELECT {metric_sql[metric_type]} AS actual
            FROM events
            WHERE {' AND '.join(clauses)}
            """
        )
        try:
            result = await db.execute(sql, params)
            row = result.fetchone()
        except (ValueError, RuntimeError, LookupError) as exc:
            log.warning(
                "sales_target_aggregate_events_unavailable",
                error=str(exc),
                metric_type=metric_type,
                employee_id=str(employee_id),
            )
            return 0
        except Exception as exc:  # noqa: BLE001 — 兼容 asyncpg/SQLAlchemy 驱动异常
            log.warning(
                "sales_target_aggregate_events_unavailable",
                error=str(exc),
                metric_type=metric_type,
                employee_id=str(employee_id),
                exc_info=True,
            )
            return 0
        if row is None:
            return 0
        value = getattr(row, "actual", None)
        if value is None and hasattr(row, "_mapping"):
            value = row._mapping.get("actual", 0)
        return int(value or 0)
