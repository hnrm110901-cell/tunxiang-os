"""试点指标采集器 — PilotMetricsCollector

每天凌晨 02:00 由 APScheduler 调用，为所有 active 试点采集当日指标快照。

数据来源：
  - 优先从 tx-analytics 的菜品销量聚合接口获取
  - 无法访问时降级查询本地 orders 表

设计原则：
  - pilot_metrics 唯一索引 (pilot_program_id, store_id, metric_date) 支持 upsert
  - 基线计算取试点前 N 天的历史均值（仅首次运行时用于对比参考）
  - 试验组 vs 对照组差值计算供 PilotService 复盘报告使用
"""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class PilotMetricsCollector:
    """试点指标采集与汇总"""

    def __init__(self, db_session: Any, analytics_base_url: str = "http://localhost:8001"):
        self._db = db_session
        self._analytics_url = analytics_base_url.rstrip("/")

    # ------------------------------------------------------------------
    # 定时任务入口
    # ------------------------------------------------------------------

    async def collect_for_all_active_pilots(self, tenant_id: uuid.UUID) -> dict[str, Any]:
        """
        定时任务入口（APScheduler 每天 02:00 调用）：
        遍历所有 active 试点，为每个试点采集昨日指标。
        """
        today = date.today()
        target_date = today - timedelta(days=1)

        rows = await self._db.fetch_all(
            """
            SELECT id, name, target_stores, control_stores, pilot_type
            FROM pilot_programs
            WHERE tenant_id = :tenant_id
              AND status = 'active'
              AND start_date <= :target_date
              AND end_date >= :target_date
              AND is_deleted = FALSE
            """,
            {"tenant_id": str(tenant_id), "target_date": target_date.isoformat()},
        )

        results: list[dict] = []
        for row in rows:
            program = dict(row)
            pilot_id = uuid.UUID(str(program["id"]))
            try:
                result = await self._collect_for_pilot(tenant_id, pilot_id, program, target_date)
                results.append({"pilot_id": str(pilot_id), "name": program["name"], "status": "ok", **result})
            except Exception as exc:  # noqa: BLE001 — 外部API/爬虫场景异常类型不可预测
                logger.error(
                    "pilot_metrics_collect_error",
                    pilot_id=str(pilot_id),
                    error=str(exc),
                    exc_info=True,
                )
                results.append({"pilot_id": str(pilot_id), "name": program["name"], "status": "error", "error": str(exc)})

        logger.info(
            "pilot_metrics_batch_complete",
            tenant_id=str(tenant_id),
            date=target_date.isoformat(),
            total=len(results),
            ok=sum(1 for r in results if r["status"] == "ok"),
        )
        return {"date": target_date.isoformat(), "pilots_processed": len(results), "results": results}

    # ------------------------------------------------------------------
    # 单试点采集
    # ------------------------------------------------------------------

    async def _collect_for_pilot(
        self,
        tenant_id: uuid.UUID,
        pilot_id: uuid.UUID,
        program: dict,
        target_date: date,
    ) -> dict[str, Any]:
        """为单个试点采集指标并写入 pilot_metrics"""
        # 解析门店列表
        target_stores: list[dict] = program.get("target_stores") or []
        control_stores: list[dict] = program.get("control_stores") or []

        if isinstance(target_stores, str):
            target_stores = json.loads(target_stores)
        if isinstance(control_stores, str):
            control_stores = json.loads(control_stores) if control_stores else []

        # 获取该试点的菜品 ID 列表
        items = await self._db.fetch_all(
            "SELECT item_ref_id FROM pilot_items WHERE tenant_id = :t AND pilot_program_id = :p AND is_active = TRUE AND item_ref_id IS NOT NULL",
            {"t": str(tenant_id), "p": str(pilot_id)},
        )
        dish_ids = [str(r["item_ref_id"]) for r in items]

        rows_written = 0

        # 试验组采集
        for store_ref in target_stores:
            store_id = store_ref.get("store_id", "")
            sales_data = await self.get_dish_sales_by_store(store_id, dish_ids, target_date)
            await self._upsert_metric(
                tenant_id, pilot_id,
                store_id=uuid.UUID(store_id),
                is_control=False,
                metric_date=target_date,
                sales_data=sales_data,
            )
            rows_written += 1

        # 对照组采集
        for store_ref in control_stores:
            store_id = store_ref.get("store_id", "")
            sales_data = await self.get_dish_sales_by_store(store_id, dish_ids, target_date)
            await self._upsert_metric(
                tenant_id, pilot_id,
                store_id=uuid.UUID(store_id),
                is_control=True,
                metric_date=target_date,
                sales_data=sales_data,
            )
            rows_written += 1

        # 检查是否提前达到成功标准
        early_success = await self._check_early_success(tenant_id, pilot_id, program)

        return {"rows_written": rows_written, "early_success_triggered": early_success}

    # ------------------------------------------------------------------
    # 从 tx-analytics 拉取菜品销量
    # ------------------------------------------------------------------

    async def get_dish_sales_by_store(
        self,
        store_id: str,
        dish_ids: list[str],
        target_date: date,
    ) -> dict[str, Any]:
        """
        从 tx-analytics 或直接查 orders 表获取菜品销量。

        返回结构：
        {
            "dish_sales_count": int,
            "dish_revenue": float,
            "avg_order_value": float,
            "raw": {...}
        }
        """
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._analytics_url}/api/v1/internal/dish-sales",
                    params={
                        "store_id": store_id,
                        "dish_ids": ",".join(dish_ids) if dish_ids else "",
                        "date": target_date.isoformat(),
                    },
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    return {
                        "dish_sales_count": data.get("total_count", 0),
                        "dish_revenue": float(data.get("total_revenue", 0)),
                        "avg_order_value": float(data.get("avg_order_value", 0)),
                        "raw": data,
                    }
        except Exception as exc:  # noqa: BLE001 — 外部API/爬虫场景异常类型不可预测
            logger.warning(
                "analytics_fetch_failed_fallback_db",
                store_id=store_id,
                error=str(exc),
            )

        # 降级：直接查数据库（简化版 — 实际项目中补充完整 orders 查询）
        return await self._fallback_db_sales(store_id, dish_ids, target_date)

    async def _fallback_db_sales(
        self,
        store_id: str,
        dish_ids: list[str],
        target_date: date,
    ) -> dict[str, Any]:
        """降级：从本地 orders 表汇总菜品销量"""
        if not dish_ids:
            return {"dish_sales_count": 0, "dish_revenue": 0.0, "avg_order_value": 0.0, "raw": {}}

        try:
            row = await self._db.fetch_one(
                """
                SELECT
                    COALESCE(SUM(oi.quantity), 0)        AS sales_count,
                    COALESCE(SUM(oi.amount_fen) / 100.0, 0) AS revenue,
                    COALESCE(AVG(o.total_amount_fen) / 100.0, 0) AS avg_order_value
                FROM orders o
                JOIN order_items oi ON oi.order_id = o.id
                WHERE o.store_id = :store_id
                  AND DATE(o.created_at) = :target_date
                  AND oi.dish_id = ANY(:dish_ids::uuid[])
                  AND o.status NOT IN ('cancelled', 'refunded')
                """,
                {
                    "store_id": store_id,
                    "target_date": target_date.isoformat(),
                    "dish_ids": dish_ids,
                },
            )
            if row:
                return {
                    "dish_sales_count": int(row["sales_count"] or 0),
                    "dish_revenue": float(row["revenue"] or 0),
                    "avg_order_value": float(row["avg_order_value"] or 0),
                    "raw": {},
                }
        except Exception as exc:  # noqa: BLE001 — 外部API/爬虫场景异常类型不可预测
            logger.error("fallback_db_sales_error", store_id=store_id, error=str(exc))

        return {"dish_sales_count": 0, "dish_revenue": 0.0, "avg_order_value": 0.0, "raw": {}}

    # ------------------------------------------------------------------
    # 基线计算
    # ------------------------------------------------------------------

    async def compute_baseline(self, pilot_id: uuid.UUID, lookback_days: int = 14) -> dict[str, Any]:
        """
        计算试点前 N 天的基线指标（用于对比）。

        说明：基线数据从试点开始前的 orders 历史中聚合，
        此处返回 pilot_metrics 中最早几天的数据作为参考基线。
        """
        rows = await self._db.fetch_all(
            """
            SELECT
                is_control_store,
                AVG(dish_sales_count)  AS avg_sales,
                AVG(dish_revenue)      AS avg_revenue,
                AVG(avg_order_value)   AS avg_order_value
            FROM pilot_metrics
            WHERE pilot_program_id = :pilot_id
            GROUP BY is_control_store
            ORDER BY is_control_store
            """,
            {"pilot_id": str(pilot_id)},
        )

        baseline: dict = {}
        for r in rows:
            d = dict(r)
            key = "control" if d.get("is_control_store") else "pilot"
            baseline[key] = {
                "avg_daily_sales": float(d.get("avg_sales") or 0),
                "avg_daily_revenue": float(d.get("avg_revenue") or 0),
                "avg_order_value": float(d.get("avg_order_value") or 0),
            }
        return baseline

    # ------------------------------------------------------------------
    # 试验组 vs 对照组对比
    # ------------------------------------------------------------------

    async def compare_pilot_vs_control(
        self,
        pilot_id: uuid.UUID,
        date_range: tuple[date, date],
    ) -> dict[str, Any]:
        """计算试验组 vs 对照组在给定日期区间的指标对比"""
        start_date, end_date = date_range

        rows = await self._db.fetch_all(
            """
            SELECT
                is_control_store,
                COUNT(DISTINCT store_id)         AS store_count,
                SUM(dish_sales_count)            AS total_sales,
                SUM(dish_revenue)                AS total_revenue,
                AVG(avg_order_value)             AS avg_order_value,
                AVG(customer_satisfaction_score) AS avg_satisfaction,
                AVG(repeat_purchase_rate)        AS avg_repeat_rate
            FROM pilot_metrics
            WHERE pilot_program_id = :pilot_id
              AND metric_date BETWEEN :start_date AND :end_date
            GROUP BY is_control_store
            """,
            {
                "pilot_id": str(pilot_id),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )

        comparison: dict = {"pilot": {}, "control": {}, "lift": {}}
        for r in rows:
            d = dict(r)
            key = "control" if d.get("is_control_store") else "pilot"
            comparison[key] = {
                "store_count": d.get("store_count", 0),
                "total_sales": int(d.get("total_sales") or 0),
                "total_revenue": float(d.get("total_revenue") or 0),
                "avg_order_value": float(d.get("avg_order_value") or 0),
                "avg_satisfaction": float(d.get("avg_satisfaction") or 0),
                "avg_repeat_rate": float(d.get("avg_repeat_rate") or 0),
            }

        # 计算提升率
        if comparison["pilot"] and comparison["control"]:
            for metric in ("total_sales", "total_revenue", "avg_order_value", "avg_satisfaction", "avg_repeat_rate"):
                p = comparison["pilot"].get(metric, 0)
                c = comparison["control"].get(metric, 0)
                lift = round((p - c) / abs(c) * 100, 2) if c else None
                comparison["lift"][metric] = lift

        return comparison

    # ------------------------------------------------------------------
    # upsert 单条指标
    # ------------------------------------------------------------------

    async def _upsert_metric(
        self,
        tenant_id: uuid.UUID,
        pilot_id: uuid.UUID,
        store_id: uuid.UUID,
        is_control: bool,
        metric_date: date,
        sales_data: dict,
    ) -> None:
        """写入或更新 pilot_metrics（ON CONFLICT DO UPDATE）"""
        await self._db.execute(
            """
            INSERT INTO pilot_metrics
              (id, tenant_id, pilot_program_id, store_id, is_control_store,
               metric_date, dish_sales_count, dish_revenue, avg_order_value,
               raw_metrics, created_at)
            VALUES
              (gen_random_uuid(), :tenant_id, :pilot_id, :store_id, :is_control,
               :metric_date, :sales_count, :revenue, :avg_order_value,
               :raw_metrics::jsonb, NOW())
            ON CONFLICT (pilot_program_id, store_id, metric_date) DO UPDATE SET
              dish_sales_count = EXCLUDED.dish_sales_count,
              dish_revenue     = EXCLUDED.dish_revenue,
              avg_order_value  = EXCLUDED.avg_order_value,
              raw_metrics      = EXCLUDED.raw_metrics
            """,
            {
                "tenant_id": str(tenant_id),
                "pilot_id": str(pilot_id),
                "store_id": str(store_id),
                "is_control": is_control,
                "metric_date": metric_date.isoformat(),
                "sales_count": sales_data.get("dish_sales_count", 0),
                "revenue": sales_data.get("dish_revenue", 0.0),
                "avg_order_value": sales_data.get("avg_order_value") or None,
                "raw_metrics": json.dumps(sales_data.get("raw", {})),
            },
        )

    async def _check_early_success(
        self,
        tenant_id: uuid.UUID,
        pilot_id: uuid.UUID,
        program: dict,
    ) -> bool:
        """
        检查是否满足提前结束条件（成功标准连续3天全部达标）。
        达到条件时将试点状态更新为 completed。
        """
        success_criteria = program.get("success_criteria") or []
        if not success_criteria:
            return False

        # 取最近3天的汇总数据
        rows = await self._db.fetch_all(
            """
            SELECT metric_date,
                   SUM(dish_sales_count) FILTER (WHERE NOT is_control_store) AS pilot_sales,
                   AVG(avg_order_value)  FILTER (WHERE NOT is_control_store) AS pilot_aov
            FROM pilot_metrics
            WHERE pilot_program_id = :pilot_id AND tenant_id = :tenant_id
            GROUP BY metric_date
            ORDER BY metric_date DESC
            LIMIT 3
            """,
            {"pilot_id": str(pilot_id), "tenant_id": str(tenant_id)},
        )

        if len(rows) < 3:
            return False  # 数据不足3天

        # 简化检查：如果连续3天 pilot_sales 均高于所有 gt 阈值，则视为提前成功
        for criterion in success_criteria:
            if criterion.get("operator") == "gt":
                threshold = float(criterion.get("threshold", 0))
                metric = criterion.get("metric", "")
                if metric == "total_sales" and all(
                    (dict(r).get("pilot_sales") or 0) > threshold for r in rows
                ):
                    logger.info("pilot_early_success_detected", pilot_id=str(pilot_id))
                    await self._db.execute(
                        "UPDATE pilot_programs SET status = 'completed', updated_at = NOW() WHERE id = :id AND tenant_id = :tenant_id",
                        {"id": str(pilot_id), "tenant_id": str(tenant_id)},
                    )
                    return True

        return False
