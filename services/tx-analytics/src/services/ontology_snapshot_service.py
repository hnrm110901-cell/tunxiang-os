"""Ontology快照服务 — 6大实体周期性聚合

核心能力：
  - 按 daily/weekly/monthly 周期计算并持久化6大实体快照
  - 三粒度：集团级(brand_id=None,store_id=None) / 品牌级(store_id=None) / 门店级
  - 趋势查询（时间范围内某实体指标变化）
  - 跨品牌对比（同一指标各品牌排行）
  - AI洞察触发（通过 ModelRouter，不可用时优雅降级）

金额单位：分(fen)，展示时 /100 转元。
所有 DB 操作：async/await + AsyncSession。
AI 调用：通过 ModelRouter，不直接调用 API。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ─── AI洞察触发阈值 ────────────────────────────────────────────────────────────

_AI_ORDER_ABNORMAL_THRESHOLD = 5        # abnormal_count > 5
_AI_ORDER_MARGIN_ALERT_THRESHOLD = 10   # margin_alert_count > 10
_AI_INGREDIENT_OUT_OF_STOCK_THRESHOLD = 0  # out_of_stock_count > 0
_AI_CUSTOMER_CHURN_RISK_THRESHOLD = 100    # churn_risk_count > 100

# ─── 支持的实体类型 ────────────────────────────────────────────────────────────

ENTITY_TYPES = frozenset(["customer", "dish", "store", "order", "ingredient", "employee"])
SNAPSHOT_TYPES = frozenset(["daily", "weekly", "monthly"])


def _get_model_router():
    """获取 ModelRouter 实例，不可用时返回 None（优雅降级）。"""
    try:
        from tx_agent.model_router import ModelRouter  # type: ignore[import]
        return ModelRouter()
    except ImportError:
        logger.warning("ontology_snapshot.model_router_not_available")
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Metrics 计算函数（纯 SQL 聚合，返回 dict）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _compute_customer_metrics(
    db: AsyncSession,
    tenant_id: UUID,
    snapshot_date: date,
    brand_id: UUID | None,
    store_id: UUID | None,
) -> dict[str, Any]:
    """从 customers 表聚合顾客指标。"""
    active_threshold = snapshot_date - timedelta(days=30)
    next_day = snapshot_date + timedelta(days=1)
    churn_risk_threshold = 0.7
    high_value_rfm_threshold = 12

    store_filter = ""
    params: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "active_threshold": active_threshold.isoformat(),
        "snapshot_date": snapshot_date.isoformat(),
        "next_day": next_day.isoformat(),
        "churn_risk_threshold": churn_risk_threshold,
        "high_value_rfm_threshold": high_value_rfm_threshold,
    }

    # 门店级：通过 orders 关联过滤
    # 品牌/集团级：无法从 customers 直接关联，聚合全租户数据
    # （实际项目中 customers 表无 brand_id/store_id 直接字段，集团级聚合全部顾客）

    row = await db.execute(text(f"""
        SELECT
            COUNT(*)                                                                    AS total_count,
            COUNT(*) FILTER (WHERE last_order_at >= :active_threshold)                  AS active_count,
            COUNT(*) FILTER (WHERE created_at >= :snapshot_date
                                AND created_at < :next_day)                             AS new_count,
            COUNT(*) FILTER (WHERE (COALESCE(r_score,0) + COALESCE(f_score,0)
                                    + COALESCE(m_score,0)) >= :high_value_rfm_threshold) AS high_value_count,
            AVG(COALESCE(r_score,0) + COALESCE(f_score,0)
                + COALESCE(m_score,0))                                                  AS avg_rfm_score,
            COUNT(*) FILTER (WHERE risk_score > :churn_risk_threshold)                  AS churn_risk_count,
            AVG(total_order_amount_fen)                                                 AS avg_lifetime_value_fen
        FROM customers
        WHERE tenant_id = :tenant_id
          AND is_deleted = FALSE
          AND is_merged = FALSE
        {store_filter}
    """), params))
    r = row.mappings().one()

    return {
        "total_count": int(r["total_count"] or 0),
        "active_count": int(r["active_count"] or 0),
        "new_count": int(r["new_count"] or 0),
        "high_value_count": int(r["high_value_count"] or 0),
        "avg_rfm_score": round(float(r["avg_rfm_score"] or 0.0), 2),
        "churn_risk_count": int(r["churn_risk_count"] or 0),
        "avg_lifetime_value_fen": int(r["avg_lifetime_value_fen"] or 0),
    }


async def _compute_dish_metrics(
    db: AsyncSession,
    tenant_id: UUID,
    snapshot_date: date,
    brand_id: UUID | None,
    store_id: UUID | None,
) -> dict[str, Any]:
    """从 dishes 表聚合菜品指标。"""
    low_margin_threshold = 0.40

    brand_filter = "AND brand_id = :brand_id" if brand_id else ""
    store_filter = "AND store_id = :store_id" if store_id else ""
    params: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "low_margin_threshold": low_margin_threshold,
    }
    if brand_id:
        params["brand_id"] = str(brand_id)
    if store_id:
        params["store_id"] = str(store_id)

    row = await db.execute(text(f"""
        SELECT
            COUNT(*) FILTER (WHERE status = 'active')                   AS active_count,
            AVG(profit_margin) FILTER (WHERE status = 'active')         AS avg_profit_margin,
            COUNT(*) FILTER (WHERE profit_margin < :low_margin_threshold
                               AND status = 'active')                   AS low_margin_count,
            SUM(total_revenue_fen)                                       AS total_revenue_fen,
            MAX(total_sales)                                             AS top_dish_sales,
            COUNT(*) FILTER (WHERE is_recommended = TRUE
                               AND status = 'active')                   AS recommended_count,
            AVG(rating) FILTER (WHERE status = 'active')                AS avg_rating
        FROM dishes
        WHERE tenant_id = :tenant_id
          AND is_deleted = FALSE
          {brand_filter}
          {store_filter}
    """), params))
    r = row.mappings().one()

    return {
        "active_count": int(r["active_count"] or 0),
        "avg_profit_margin": round(float(r["avg_profit_margin"] or 0.0), 4),
        "low_margin_count": int(r["low_margin_count"] or 0),
        "total_revenue_fen": int(r["total_revenue_fen"] or 0),
        "top_dish_sales": int(r["top_dish_sales"] or 0),
        "recommended_count": int(r["recommended_count"] or 0),
        "avg_rating": round(float(r["avg_rating"] or 0.0), 2),
    }


async def _compute_order_metrics(
    db: AsyncSession,
    tenant_id: UUID,
    snapshot_date: date,
    brand_id: UUID | None,
    store_id: UUID | None,
) -> dict[str, Any]:
    """从 orders 表聚合当天订单指标。"""
    next_day = snapshot_date + timedelta(days=1)

    brand_filter = "AND o.brand_id = :brand_id" if brand_id else ""
    store_filter = "AND o.store_id = :store_id" if store_id else ""
    params: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "snapshot_date": snapshot_date.isoformat(),
        "next_day": next_day.isoformat(),
    }
    if brand_id:
        params["brand_id"] = str(brand_id)
    if store_id:
        params["store_id"] = str(store_id)

    row = await db.execute(text(f"""
        SELECT
            COUNT(*)                                                        AS total_count,
            SUM(final_amount_fen)                                           AS total_revenue_fen,
            SUM(discount_amount_fen)                                        AS total_discount_fen,
            AVG(final_amount_fen)                                           AS avg_order_value_fen,
            COUNT(*) FILTER (WHERE abnormal_flag = TRUE)                    AS abnormal_count,
            COUNT(*) FILTER (WHERE margin_alert_flag = TRUE)                AS margin_alert_count,
            COUNT(*) FILTER (WHERE order_type = 'dine_in')                  AS dine_in_count,
            COUNT(*) FILTER (WHERE order_type = 'takeaway')                 AS takeaway_count,
            COUNT(*) FILTER (WHERE order_type = 'delivery')                 AS delivery_count,
            AVG(gross_margin_after)                                         AS avg_gross_margin
        FROM orders o
        WHERE o.tenant_id = :tenant_id
          AND o.is_deleted = FALSE
          AND o.created_at >= :snapshot_date
          AND o.created_at < :next_day
          {brand_filter}
          {store_filter}
    """), params))
    r = row.mappings().one()

    return {
        "total_count": int(r["total_count"] or 0),
        "total_revenue_fen": int(r["total_revenue_fen"] or 0),
        "total_discount_fen": int(r["total_discount_fen"] or 0),
        "avg_order_value_fen": int(r["avg_order_value_fen"] or 0),
        "abnormal_count": int(r["abnormal_count"] or 0),
        "margin_alert_count": int(r["margin_alert_count"] or 0),
        "dine_in_count": int(r["dine_in_count"] or 0),
        "takeaway_count": int(r["takeaway_count"] or 0),
        "delivery_count": int(r["delivery_count"] or 0),
        "avg_gross_margin": round(float(r["avg_gross_margin"] or 0.0), 4),
    }


async def _compute_ingredient_metrics(
    db: AsyncSession,
    tenant_id: UUID,
    snapshot_date: date,
    brand_id: UUID | None,
    store_id: UUID | None,
) -> dict[str, Any]:
    """从 ingredients 表聚合库存指标。"""
    store_filter = "AND store_id = :store_id" if store_id else ""
    params: dict[str, Any] = {"tenant_id": str(tenant_id)}
    if store_id:
        params["store_id"] = str(store_id)

    row = await db.execute(text(f"""
        SELECT
            COUNT(*)                                                            AS total_sku_count,
            COUNT(*) FILTER (WHERE current_quantity < min_quantity
                               AND current_quantity > 0)                        AS low_stock_count,
            COUNT(*) FILTER (WHERE current_quantity <= 0)                       AS out_of_stock_count,
            SUM(current_quantity * unit_price_fen)                              AS total_inventory_value_fen,
            COUNT(*) FILTER (WHERE status = 'normal')                           AS normal_count
        FROM ingredients
        WHERE tenant_id = :tenant_id
          AND is_deleted = FALSE
          {store_filter}
    """), params))
    r = row.mappings().one()

    return {
        "total_sku_count": int(r["total_sku_count"] or 0),
        "low_stock_count": int(r["low_stock_count"] or 0),
        "out_of_stock_count": int(r["out_of_stock_count"] or 0),
        "total_inventory_value_fen": int(r["total_inventory_value_fen"] or 0),
        "normal_count": int(r["normal_count"] or 0),
    }


async def _compute_employee_metrics(
    db: AsyncSession,
    tenant_id: UUID,
    snapshot_date: date,
    brand_id: UUID | None,
    store_id: UUID | None,
) -> dict[str, Any]:
    """从 employees 表聚合员工指标。"""
    cert_alert_threshold = snapshot_date + timedelta(days=30)

    brand_filter = "AND brand_id = :brand_id" if brand_id else ""
    store_filter = "AND store_id = :store_id" if store_id else ""
    params: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "cert_alert_threshold": cert_alert_threshold.isoformat(),
        "snapshot_date": snapshot_date.isoformat(),
    }
    if brand_id:
        params["brand_id"] = str(brand_id)
    if store_id:
        params["store_id"] = str(store_id)

    row = await db.execute(text(f"""
        SELECT
            COUNT(*)                                                            AS total_count,
            COUNT(*) FILTER (WHERE employment_status = 'active')                AS active_count,
            COUNT(*) FILTER (WHERE role = 'chef')                               AS chef_count,
            COUNT(*) FILTER (WHERE role = 'waiter')                             AS waiter_count,
            COUNT(*) FILTER (WHERE role = 'manager')                            AS manager_count,
            COUNT(*) FILTER (WHERE health_cert_expiry IS NOT NULL
                               AND health_cert_expiry <= :cert_alert_threshold) AS cert_expiry_alert_count,
            AVG(
                EXTRACT(YEAR FROM AGE(:snapshot_date::DATE, hire_date)) * 12
                + EXTRACT(MONTH FROM AGE(:snapshot_date::DATE, hire_date))
            ) FILTER (WHERE hire_date IS NOT NULL)                              AS avg_seniority_months
        FROM employees
        WHERE tenant_id = :tenant_id
          AND is_deleted = FALSE
          {brand_filter}
          {store_filter}
    """), params))
    r = row.mappings().one()

    return {
        "total_count": int(r["total_count"] or 0),
        "active_count": int(r["active_count"] or 0),
        "chef_count": int(r["chef_count"] or 0),
        "waiter_count": int(r["waiter_count"] or 0),
        "manager_count": int(r["manager_count"] or 0),
        "cert_expiry_alert_count": int(r["cert_expiry_alert_count"] or 0),
        "avg_seniority_months": round(float(r["avg_seniority_months"] or 0.0), 1),
    }


async def _compute_store_metrics(
    db: AsyncSession,
    tenant_id: UUID,
    snapshot_date: date,
    brand_id: UUID | None,
    store_id: UUID | None,
) -> dict[str, Any]:
    """从 stores + orders 聚合门店指标（集团/品牌粒度）。"""
    next_day = snapshot_date + timedelta(days=1)

    brand_filter_store = "AND brand_id = :brand_id" if brand_id else ""
    brand_filter_order = "AND o.brand_id = :brand_id" if brand_id else ""
    store_filter_store = "AND id = :store_id" if store_id else ""
    store_filter_order = "AND o.store_id = :store_id" if store_id else ""

    params: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "snapshot_date": snapshot_date.isoformat(),
        "next_day": next_day.isoformat(),
    }
    if brand_id:
        params["brand_id"] = str(brand_id)
    if store_id:
        params["store_id"] = str(store_id)

    store_row = await db.execute(text(f"""
        SELECT
            COUNT(*)                                                        AS total_store_count,
            COUNT(*) FILTER (WHERE operation_mode = '直营')                  AS direct_count,
            COUNT(*) FILTER (WHERE operation_mode = '加盟')                  AS franchise_count,
            COUNT(*) FILTER (WHERE status = 'active')                       AS active_count,
            COUNT(*) FILTER (WHERE business_type = 'fine_dining')           AS fine_dining_count,
            COUNT(*) FILTER (WHERE business_type = 'fast_food')             AS fast_food_count
        FROM stores
        WHERE tenant_id = :tenant_id
          AND is_deleted = FALSE
          {brand_filter_store}
          {store_filter_store}
    """), params))
    sr = store_row.mappings().one()

    order_row = await db.execute(text(f"""
        SELECT
            AVG(daily_rev.rev)      AS avg_daily_revenue_fen,
            MAX(daily_rev.rev)      AS top_store_revenue_fen
        FROM (
            SELECT o.store_id, SUM(o.final_amount_fen) AS rev
            FROM orders o
            WHERE o.tenant_id = :tenant_id
              AND o.is_deleted = FALSE
              AND o.created_at >= :snapshot_date
              AND o.created_at < :next_day
              {brand_filter_order}
              {store_filter_order}
            GROUP BY o.store_id
        ) daily_rev
    """), params))
    orr = order_row.mappings().one()

    return {
        "total_store_count": int(sr["total_store_count"] or 0),
        "direct_count": int(sr["direct_count"] or 0),
        "franchise_count": int(sr["franchise_count"] or 0),
        "active_count": int(sr["active_count"] or 0),
        "fine_dining_count": int(sr["fine_dining_count"] or 0),
        "fast_food_count": int(sr["fast_food_count"] or 0),
        "avg_daily_revenue_fen": int(orr["avg_daily_revenue_fen"] or 0),
        "top_store_revenue_fen": int(orr["top_store_revenue_fen"] or 0),
    }


# ─── 分发表 ──────────────────────────────────────────────────────────────────

_ENTITY_COMPUTE_MAP = {
    "customer": _compute_customer_metrics,
    "dish": _compute_dish_metrics,
    "order": _compute_order_metrics,
    "ingredient": _compute_ingredient_metrics,
    "employee": _compute_employee_metrics,
    "store": _compute_store_metrics,
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  OntologySnapshotService
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class OntologySnapshotService:
    """6大实体周期性聚合快照服务。

    支持: daily / weekly / monthly
    粒度: 集团级(store_id=None, brand_id=None) / 品牌级(store_id=None) / 门店级
    """

    # ── 写入 / 计算 ──────────────────────────────────────────────────────────

    async def _upsert_snapshot(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        brand_id: UUID | None,
        store_id: UUID | None,
        snapshot_date: date,
        snapshot_type: str,
        entity_type: str,
        metrics: dict[str, Any],
    ) -> None:
        """插入或覆盖更新一条快照记录（ON CONFLICT DO UPDATE）。"""
        now = datetime.now(tz=timezone.utc)
        await db.execute(text("""
            INSERT INTO ontology_snapshots
                (tenant_id, brand_id, store_id, snapshot_date, snapshot_type,
                 entity_type, metrics, computed_at, is_deleted, created_at, updated_at)
            VALUES
                (:tenant_id, :brand_id, :store_id, :snapshot_date, :snapshot_type,
                 :entity_type, :metrics::jsonb, :computed_at, FALSE, :now, :now)
            ON CONFLICT (tenant_id, brand_id, store_id, snapshot_type, entity_type, snapshot_date)
            DO UPDATE SET
                metrics     = EXCLUDED.metrics,
                computed_at = EXCLUDED.computed_at,
                updated_at  = EXCLUDED.updated_at,
                is_deleted  = FALSE
        """), {
            "tenant_id": str(tenant_id),
            "brand_id": str(brand_id) if brand_id else None,
            "store_id": str(store_id) if store_id else None,
            "snapshot_date": snapshot_date.isoformat(),
            "snapshot_type": snapshot_type,
            "entity_type": entity_type,
            "metrics": __import__("json").dumps(metrics),
            "computed_at": now,
            "now": now,
        })

    async def compute_daily_snapshots(
        self,
        tenant_id: UUID,
        snapshot_date: date,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """计算并持久化指定日期的所有实体快照（集团级）。

        Returns:
            摘要 dict：{entity_type: {"ok": bool, "metrics": dict} | {"ok": False, "error": str}}
        """
        summary: dict[str, Any] = {}

        for entity_type, compute_fn in _ENTITY_COMPUTE_MAP.items():
            try:
                metrics = await compute_fn(
                    db=db,
                    tenant_id=tenant_id,
                    snapshot_date=snapshot_date,
                    brand_id=None,
                    store_id=None,
                )
                await self._upsert_snapshot(
                    db=db,
                    tenant_id=tenant_id,
                    brand_id=None,
                    store_id=None,
                    snapshot_date=snapshot_date,
                    snapshot_type="daily",
                    entity_type=entity_type,
                    metrics=metrics,
                )
                summary[entity_type] = {"ok": True, "metrics": metrics}
                logger.info(
                    "ontology_snapshot.computed",
                    tenant_id=str(tenant_id),
                    entity_type=entity_type,
                    snapshot_date=snapshot_date.isoformat(),
                )
            except SQLAlchemyError as exc:
                logger.error(
                    "ontology_snapshot.db_error",
                    tenant_id=str(tenant_id),
                    entity_type=entity_type,
                    error=str(exc),
                )
                summary[entity_type] = {"ok": False, "error": str(exc)}

        await db.commit()

        # AI洞察触发（条件满足时异步触发，不影响主流程）
        await self._maybe_trigger_ai_insight(tenant_id, snapshot_date, summary)

        return summary

    async def _maybe_trigger_ai_insight(
        self,
        tenant_id: UUID,
        snapshot_date: date,
        summary: dict[str, Any],
    ) -> None:
        """根据阈值判断是否触发 AI 洞察，通过 ModelRouter 调用，不可用时优雅降级。"""
        order_metrics = summary.get("order", {}).get("metrics", {})
        ingredient_metrics = summary.get("ingredient", {}).get("metrics", {})
        customer_metrics = summary.get("customer", {}).get("metrics", {})

        should_trigger = (
            order_metrics.get("abnormal_count", 0) > _AI_ORDER_ABNORMAL_THRESHOLD
            or order_metrics.get("margin_alert_count", 0) > _AI_ORDER_MARGIN_ALERT_THRESHOLD
            or ingredient_metrics.get("out_of_stock_count", 0) > _AI_INGREDIENT_OUT_OF_STOCK_THRESHOLD
            or customer_metrics.get("churn_risk_count", 0) > _AI_CUSTOMER_CHURN_RISK_THRESHOLD
        )

        if not should_trigger:
            return

        model_router = _get_model_router()
        if model_router is None:
            return

        try:
            alert_parts = []
            if order_metrics.get("abnormal_count", 0) > _AI_ORDER_ABNORMAL_THRESHOLD:
                alert_parts.append(f"异常订单{order_metrics['abnormal_count']}笔")
            if order_metrics.get("margin_alert_count", 0) > _AI_ORDER_MARGIN_ALERT_THRESHOLD:
                alert_parts.append(f"毛利预警{order_metrics['margin_alert_count']}笔")
            if ingredient_metrics.get("out_of_stock_count", 0) > _AI_INGREDIENT_OUT_OF_STOCK_THRESHOLD:
                alert_parts.append(f"缺货SKU{ingredient_metrics['out_of_stock_count']}个")
            if customer_metrics.get("churn_risk_count", 0) > _AI_CUSTOMER_CHURN_RISK_THRESHOLD:
                alert_parts.append(f"高流失风险顾客{customer_metrics['churn_risk_count']}人")

            prompt = (
                f"屯象OS经营快照 [{snapshot_date.isoformat()}]，发现以下异常：\n"
                + "\n".join(f"- {p}" for p in alert_parts)
                + "\n\n请用150字内给出关键风险判断和优先处理建议。"
            )
            insight = await model_router.complete(
                prompt=prompt,
                max_tokens=250,
                temperature=0.3,
            )
            logger.info(
                "ontology_snapshot.ai_insight_generated",
                tenant_id=str(tenant_id),
                snapshot_date=snapshot_date.isoformat(),
                insight_preview=(insight or "")[:50],
            )
        except Exception as exc:  # noqa: BLE001 — AI 调用最外层兜底，不影响业务
            logger.warning(
                "ontology_snapshot.ai_insight_failed",
                tenant_id=str(tenant_id),
                error=str(exc),
                exc_info=True,
            )

    # ── 查询 ─────────────────────────────────────────────────────────────────

    async def get_entity_trend(
        self,
        tenant_id: UUID,
        entity_type: str,
        brand_id: UUID | None,
        store_id: UUID | None,
        start_date: date,
        end_date: date,
        snapshot_type: str = "daily",
        db: AsyncSession = None,
    ) -> list[dict[str, Any]]:
        """返回指定实体在时间范围内的趋势数据（按日期升序）。

        Returns:
            [{"snapshot_date": "2026-03-01", "metrics": {...}}, ...]
        """
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"不支持的实体类型: {entity_type}，合法值: {ENTITY_TYPES}")
        if snapshot_type not in SNAPSHOT_TYPES:
            raise ValueError(f"不支持的快照类型: {snapshot_type}，合法值: {SNAPSHOT_TYPES}")

        brand_clause = (
            "AND brand_id = :brand_id" if brand_id
            else "AND brand_id IS NULL"
        )
        store_clause = (
            "AND store_id = :store_id" if store_id
            else "AND store_id IS NULL"
        )

        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "entity_type": entity_type,
            "snapshot_type": snapshot_type,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        if brand_id:
            params["brand_id"] = str(brand_id)
        if store_id:
            params["store_id"] = str(store_id)

        result = await db.execute(text(f"""
            SELECT snapshot_date, metrics
            FROM ontology_snapshots
            WHERE tenant_id = :tenant_id
              AND entity_type = :entity_type
              AND snapshot_type = :snapshot_type
              AND snapshot_date BETWEEN :start_date AND :end_date
              AND is_deleted = FALSE
              {brand_clause}
              {store_clause}
            ORDER BY snapshot_date ASC
        """), params)

        rows = result.mappings().all()
        return [
            {
                "snapshot_date": str(row["snapshot_date"]),
                "metrics": row["metrics"],
            }
            for row in rows
        ]

    async def get_cross_brand_comparison(
        self,
        tenant_id: UUID,
        entity_type: str,
        snapshot_date: date,
        metric_key: str,
        db: AsyncSession = None,
    ) -> list[dict[str, Any]]:
        """跨品牌对比：返回各品牌在某天某指标的排行（降序）。

        Returns:
            [{"brand_id": "...", "metric_value": 12200, "rank": 1}, ...]
        """
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"不支持的实体类型: {entity_type}，合法值: {ENTITY_TYPES}")

        result = await db.execute(text("""
            SELECT
                brand_id,
                (metrics->>:metric_key)::NUMERIC   AS metric_value
            FROM ontology_snapshots
            WHERE tenant_id = :tenant_id
              AND entity_type = :entity_type
              AND snapshot_date = :snapshot_date
              AND snapshot_type = 'daily'
              AND brand_id IS NOT NULL
              AND store_id IS NULL
              AND is_deleted = FALSE
              AND metrics ? :metric_key
            ORDER BY metric_value DESC NULLS LAST
        """), {
            "tenant_id": str(tenant_id),
            "entity_type": entity_type,
            "snapshot_date": snapshot_date.isoformat(),
            "metric_key": metric_key,
        })

        rows = result.mappings().all()
        return [
            {
                "brand_id": str(row["brand_id"]),
                "metric_value": float(row["metric_value"] or 0),
                "rank": idx + 1,
            }
            for idx, row in enumerate(rows)
        ]

    async def get_latest_group_snapshot(
        self,
        tenant_id: UUID,
        entity_type: str,
        db: AsyncSession = None,
    ) -> dict[str, Any] | None:
        """获取集团级（brand_id IS NULL, store_id IS NULL）最新快照。

        Returns:
            {"snapshot_date": "...", "snapshot_type": "...", "metrics": {...}} 或 None
        """
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"不支持的实体类型: {entity_type}，合法值: {ENTITY_TYPES}")

        result = await db.execute(text("""
            SELECT snapshot_date, snapshot_type, metrics
            FROM ontology_snapshots
            WHERE tenant_id = :tenant_id
              AND entity_type = :entity_type
              AND brand_id IS NULL
              AND store_id IS NULL
              AND is_deleted = FALSE
            ORDER BY snapshot_date DESC, computed_at DESC
            LIMIT 1
        """), {
            "tenant_id": str(tenant_id),
            "entity_type": entity_type,
        })

        row = result.mappings().first()
        if row is None:
            return None

        return {
            "snapshot_date": str(row["snapshot_date"]),
            "snapshot_type": row["snapshot_type"],
            "metrics": row["metrics"],
        }

    async def get_all_latest_group_snapshots(
        self,
        tenant_id: UUID,
        db: AsyncSession = None,
    ) -> dict[str, Any]:
        """获取所有6大实体的集团级最新快照汇总。

        Returns:
            {"customer": {...}, "dish": {...}, ...}
        """
        result: dict[str, Any] = {}
        for entity_type in ENTITY_TYPES:
            snapshot = await self.get_latest_group_snapshot(
                tenant_id=tenant_id,
                entity_type=entity_type,
                db=db,
            )
            result[entity_type] = snapshot
        return result
