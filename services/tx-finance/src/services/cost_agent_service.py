"""成本核算 Agent 桥接服务

职责：
  1. 聚合多成本引擎数据，为 CostDiagnosisAgent 提供统一上下文
  2. 采购价趋势查询（供预测性预警使用）
  3. 成本预警事件推送（通过 FinanceEventType）
  4. Agent 决策写入 cost_snapshots

金额单位：分（fen, int）。
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, desc, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# 成本率预警阈值
_HIGH_COST_RATE_THRESHOLD = 0.36   # 超过36%触发高成本预警
_CRITICAL_COST_RATE_THRESHOLD = 0.42  # 超过42%触发严重预警

# 价格漂移检测：连续N次采购价上涨
_PRICE_DRIFT_CONSECUTIVE = 3


class CostAgentService:
    """成本核算Agent桥接服务

    依赖 AsyncSession，通过 Repository 查询数据。
    当 db=None 时，所有方法返回空数据（方便单元测试）。
    """

    def __init__(self, db: AsyncSession | None = None) -> None:
        self._db = db

    # ─── 上下文聚合 ────────────────────────────────────────────────────────────

    async def get_cost_context_for_agent(
        self,
        store_id: str,
        target_date: date,
        tenant_id: str,
    ) -> dict[str, Any]:
        """聚合Agent所需的成本上下文

        Returns:
            {
                "store_id": str,
                "date": str,
                "daily_pnl": dict,           # 当日P&L快报
                "top_cost_dishes": list,     # 成本率Top10菜品
                "cost_health": dict,         # 成本健康度评分
                "price_alerts": list,        # 采购价漂移预警
            }
        """
        if not self._db:
            log.warning("cost_agent_service.no_db", store_id=store_id)
            return {"store_id": store_id, "date": str(target_date), "no_db": True}

        try:
            pnl = await self._get_daily_pnl(store_id, target_date, tenant_id)
            top_dishes = await self._get_top_cost_dishes(store_id, target_date, tenant_id)
            health = self._compute_cost_health(pnl)  # reuse already-fetched pnl
            price_alerts = await self._detect_price_drift(store_id, tenant_id)

            return {
                "store_id": store_id,
                "date": str(target_date),
                "daily_pnl": pnl,
                "top_cost_dishes": top_dishes,
                "cost_health": health,
                "price_alerts": price_alerts,
            }
        except Exception as exc:
            log.error("cost_agent_service.context_error", store_id=store_id, error=str(exc), exc_info=True)
            return {"store_id": store_id, "date": str(target_date), "error": str(exc)}

    async def get_dish_cost_comparison(
        self,
        store_id: str,
        target_date: date,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        """获取菜品理论成本 vs 实际销售成本对比

        Returns: list of {dish_name, theoretical_cost_fen, actual_cost_fen,
                          variance_rate, quantity_sold, selling_price_fen}
        """
        if not self._db:
            return []

        try:
            # 从 cost_snapshots 聚合当日菜品成本
            sql = text("""
                SELECT
                    oi.dish_name,
                    COALESCE(cs.raw_material_cost, 0)::int          AS actual_cost_fen,
                    COALESCE(d.cost_fen, cs.raw_material_cost, 0)::int AS theoretical_cost_fen,
                    SUM(oi.quantity)::int                            AS quantity_sold,
                    COALESCE(oi.unit_price, 0)::int                  AS selling_price_fen
                FROM order_items oi
                LEFT JOIN cost_snapshots cs ON cs.order_item_id = oi.id
                LEFT JOIN dishes d ON d.id = oi.dish_id
                JOIN orders o ON o.id = oi.order_id
                WHERE o.store_id = :store_id
                  AND o.tenant_id = :tenant_id
                  AND DATE(o.created_at) = :target_date
                  AND o.status != 'cancelled'
                GROUP BY oi.dish_name, cs.raw_material_cost, d.cost_fen, oi.unit_price
                ORDER BY SUM(oi.quantity) DESC
                LIMIT 50
            """)
            result = await self._db.execute(
                sql,
                {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
            )
            rows = result.mappings().all()

            comparison = []
            for row in rows:
                theoretical = int(row["theoretical_cost_fen"])
                actual = int(row["actual_cost_fen"])
                variance = (actual - theoretical) / theoretical if theoretical > 0 else 0.0
                comparison.append({
                    "dish_name": row["dish_name"],
                    "theoretical_cost_fen": theoretical,
                    "actual_cost_fen": actual,
                    "variance_rate": round(variance, 4),
                    "quantity_sold": int(row["quantity_sold"]),
                    "selling_price_fen": int(row["selling_price_fen"]),
                })

            return comparison

        except Exception as exc:
            log.error("cost_agent_service.dish_comparison_error", store_id=store_id, error=str(exc), exc_info=True)
            return []

    async def get_price_trend(
        self,
        ingredient_id: str,
        tenant_id: str,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """获取食材采购价格历史趋势

        Returns: list of {date, unit_cost_fen, supplier_name, change_pct}，按日期升序
        """
        if not self._db:
            return []

        try:
            since = date.today() - timedelta(days=days)
            sql = text("""
                SELECT
                    DATE(it.created_at)          AS purchase_date,
                    it.unit_cost_fen::int         AS unit_cost_fen,
                    COALESCE(s.name, '未知供应商') AS supplier_name
                FROM ingredient_transactions it
                LEFT JOIN supply_orders so ON so.id = it.supply_order_id
                LEFT JOIN suppliers s ON s.id = so.supplier_id
                WHERE it.ingredient_id = :ingredient_id
                  AND it.tenant_id = :tenant_id
                  AND it.transaction_type = 'purchase'
                  AND DATE(it.created_at) >= :since
                ORDER BY it.created_at ASC
            """)
            result = await self._db.execute(
                sql,
                {
                    "ingredient_id": ingredient_id,
                    "tenant_id": tenant_id,
                    "since": since,
                },
            )
            rows = result.mappings().all()

            trend = []
            prev_price = None
            for row in rows:
                price = int(row["unit_cost_fen"])
                change_pct = (
                    round((price - prev_price) / prev_price, 4)
                    if prev_price and prev_price > 0
                    else 0.0
                )
                trend.append({
                    "date": str(row["purchase_date"]),
                    "unit_cost_fen": price,
                    "supplier_name": row["supplier_name"],
                    "change_pct": change_pct,
                })
                prev_price = price

            return trend

        except Exception as exc:
            log.error("cost_agent_service.price_trend_error", ingredient_id=ingredient_id, error=str(exc), exc_info=True)
            return []

    async def emit_cost_alert(
        self,
        store_id: str,
        tenant_id: str,
        alert: dict[str, Any],
    ) -> None:
        """推送成本预警事件

        alert: {
            "alert_type": "high_cost_rate" | "price_drift" | "waste_excess",
            "severity": "warning" | "critical",
            "message": str,
            "data": dict,
        }
        """
        try:
            from shared.events.src.emitter import emit_event
            from shared.events.src.event_types import FinanceEventType

            await emit_event(
                event_type=FinanceEventType.COST_ALERT,
                tenant_id=tenant_id,
                stream_id=store_id,
                payload={
                    "alert_type": alert.get("alert_type", "cost_alert"),
                    "severity": alert.get("severity", "warning"),
                    "message": alert.get("message", ""),
                    "data": alert.get("data", {}),
                },
                store_id=store_id,
                source_service="tx-finance",
            )
            log.info(
                "cost_alert_emitted",
                store_id=store_id,
                alert_type=alert.get("alert_type"),
                severity=alert.get("severity"),
            )
        except (SQLAlchemyError, ValueError, RuntimeError) as exc:
            # 预警推送失败不应阻断主流程
            log.warning("cost_agent_service.emit_alert_failed", store_id=store_id, error=str(exc))

    # ─── 内部查询 ──────────────────────────────────────────────────────────────

    async def _get_daily_pnl(
        self, store_id: str, target_date: date, tenant_id: str
    ) -> dict:
        """从 daily_pnl 取当日P&L数据"""
        sql = text("""
            SELECT
                food_cost_fen, labor_cost_fen, total_revenue_fen,
                gross_profit_fen, food_cost_rate, status
            FROM daily_pnl
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND pnl_date = :target_date
            LIMIT 1
        """)
        try:
            result = await self._db.execute(
                sql, {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date}
            )
            row = result.mappings().first()
            if row:
                return dict(row)
            return {}
        except SQLAlchemyError as exc:
            log.warning("cost_agent_service._get_daily_pnl_failed", error=str(exc))
            return {}

    async def _get_top_cost_dishes(
        self, store_id: str, target_date: date, tenant_id: str, limit: int = 10
    ) -> list[dict]:
        """取当日成本率最高的菜品"""
        sql = text("""
            SELECT
                oi.dish_name,
                AVG(CASE WHEN oi.unit_price > 0
                    THEN cs.raw_material_cost::float / oi.unit_price
                    ELSE 0 END) AS cost_rate,
                SUM(cs.raw_material_cost)::int AS total_cost_fen,
                SUM(oi.quantity)::int           AS quantity_sold
            FROM order_items oi
            JOIN cost_snapshots cs ON cs.order_item_id = oi.id
            JOIN orders o ON o.id = oi.order_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.created_at) = :target_date
              AND o.status != 'cancelled'
            GROUP BY oi.dish_name
            ORDER BY cost_rate DESC
            LIMIT :limit
        """)
        try:
            result = await self._db.execute(
                sql,
                {
                    "store_id": store_id,
                    "tenant_id": tenant_id,
                    "target_date": target_date,
                    "limit": limit,
                },
            )
            return [dict(row) for row in result.mappings().all()]
        except SQLAlchemyError as exc:
            log.warning("cost_agent_service._get_top_cost_dishes_failed", error=str(exc))
            return []

    def _compute_cost_health(self, pnl: dict) -> dict:
        """从已取得的 daily_pnl 数据计算成本健康度（无额外DB查询）"""
        food_cost_rate = float(pnl.get("food_cost_rate", 0.0))
        if food_cost_rate >= _CRITICAL_COST_RATE_THRESHOLD:
            status = "critical"
        elif food_cost_rate >= _HIGH_COST_RATE_THRESHOLD:
            status = "high"
        elif food_cost_rate >= 0.30:
            status = "normal"
        else:
            status = "excellent"
        return {
            "food_cost_rate": food_cost_rate,
            "status": status,
            "threshold_high": _HIGH_COST_RATE_THRESHOLD,
            "threshold_critical": _CRITICAL_COST_RATE_THRESHOLD,
        }

    async def _detect_price_drift(
        self, store_id: str, tenant_id: str, lookback_days: int = 14
    ) -> list[dict]:
        """检测连续N次采购价上涨的食材（价格漂移）

        Returns: list of {ingredient_name, ingredient_id, consecutive_rises, last_price_fen, drift_pct}
        """
        since = date.today() - timedelta(days=lookback_days)
        sql = text("""
            WITH ranked AS (
                SELECT
                    it.ingredient_id,
                    i.name AS ingredient_name,
                    it.unit_cost_fen::int AS price,
                    ROW_NUMBER() OVER (PARTITION BY it.ingredient_id ORDER BY it.created_at DESC) AS rn
                FROM ingredient_transactions it
                JOIN ingredients i ON i.id = it.ingredient_id
                WHERE it.tenant_id = :tenant_id
                  AND it.transaction_type = 'purchase'
                  AND DATE(it.created_at) >= :since
            )
            SELECT ingredient_id, ingredient_name,
                   array_agg(price ORDER BY rn DESC) AS prices
            FROM ranked
            WHERE rn <= :n
            GROUP BY ingredient_id, ingredient_name
            HAVING count(*) >= :n
        """)
        try:
            result = await self._db.execute(
                sql,
                {
                    "tenant_id": tenant_id,
                    "since": since,
                    "n": _PRICE_DRIFT_CONSECUTIVE,
                },
            )
            rows = result.mappings().all()
            alerts = []
            for row in rows:
                prices: list[int] = row["prices"]  # 最新在前
                if len(prices) < 2:
                    continue
                # 检查是否连续上涨（最新在前，所以检查倒序递增）
                is_drifting = all(prices[i] > prices[i + 1] for i in range(len(prices) - 1))
                if is_drifting:
                    drift_pct = (prices[0] - prices[-1]) / prices[-1] if prices[-1] > 0 else 0.0
                    alerts.append({
                        "ingredient_id": str(row["ingredient_id"]),
                        "ingredient_name": row["ingredient_name"],
                        "consecutive_rises": len(prices) - 1,
                        "last_price_fen": prices[0],
                        "first_price_fen": prices[-1],
                        "drift_pct": round(drift_pct, 4),
                    })
            return alerts
        except SQLAlchemyError as exc:
            log.warning("cost_agent_service._detect_price_drift_failed", error=str(exc))
            return []
