"""顾客旅程时间打点服务 — Sprint G4

记录顾客全链路时间（到店→入座→点单→上菜→结账→离店），
实时检测SLA违规，提供统计分析和活跃旅程看板。

金额单位: 分(fen)。时间单位: 分钟(minutes)。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# 事件类型到数据库列的映射
_EVENT_COLUMN_MAP: dict[str, str] = {
    "arrived": "arrived_at",
    "seated": "seated_at",
    "ordered": "ordered_at",
    "first_served": "first_served_at",
    "paid": "paid_at",
    "left": "left_at",
}


class CustomerJourneyTimingService:
    """顾客旅程时间打点服务。"""

    # SLA配置（可由门店自定义）
    DEFAULT_SLA: dict[str, float] = {
        "wait": 15.0,   # 等位 ≤ 15 分钟
        "order": 5.0,   # 点单 ≤ 5 分钟
        "serve": 12.0,  # 首道菜 ≤ 12 分钟
        "total": 60.0,  # 总用餐 ≤ 60 分钟
    }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  record_event — 记录旅程事件打点
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def record_event(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        order_id: Optional[uuid.UUID],
        event_type: str,
        timestamp: datetime,
        table_id: Optional[uuid.UUID] = None,
        party_size: Optional[int] = None,
        is_delivery: bool = False,
    ) -> dict[str, Any]:
        """记录旅程事件打点。

        event_type: 'arrived'|'seated'|'ordered'|'first_served'|'paid'|'left'
        - arrived 事件：创建新 journey 记录
        - 其他事件：更新已有 journey 对应字段
        - 返回当前旅程状态
        """
        if event_type not in _EVENT_COLUMN_MAP:
            raise ValueError(f"无效事件类型: {event_type}，有效值: {list(_EVENT_COLUMN_MAP.keys())}")

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        column = _EVENT_COLUMN_MAP[event_type]
        assert column in ("arrived_at", "seated_at", "ordered_at", "first_served_at", "paid_at", "left_at")

        if event_type == "arrived":
            # 创建新旅程
            result = await db.execute(
                text("""
                    INSERT INTO customer_journey_timings
                        (tenant_id, store_id, order_id, table_id, journey_date,
                         arrived_at, party_size, is_delivery)
                    VALUES
                        (:tenant_id, :store_id, :order_id, :table_id, :journey_date,
                         :timestamp, :party_size, :is_delivery)
                    RETURNING id, tenant_id, store_id, order_id, table_id,
                              journey_date, arrived_at, seated_at, ordered_at,
                              first_served_at, paid_at, left_at,
                              wait_minutes, order_minutes, serve_minutes,
                              dine_minutes, total_minutes,
                              party_size, is_delivery
                """),
                {
                    "tenant_id": str(tenant_id),
                    "store_id": str(store_id),
                    "order_id": str(order_id) if order_id else None,
                    "table_id": str(table_id) if table_id else None,
                    "journey_date": timestamp.date(),
                    "timestamp": timestamp,
                    "party_size": party_size,
                    "is_delivery": is_delivery,
                },
            )
            row = result.mappings().first()
            await db.commit()
            log.info(
                "journey_created",
                journey_id=str(row["id"]),
                store_id=str(store_id),
                event_type=event_type,
            )
            return _row_to_dict(row)

        # 非 arrived 事件：先按 order_id 查找，再按 store_id + 最近活跃查找
        journey_id = await self._find_journey_id(db, store_id, tenant_id, order_id, table_id)
        if journey_id is None:
            raise ValueError(f"找不到活跃旅程: store_id={store_id}, order_id={order_id}")

        # 更新对应字段 + order_id/table_id（如果之前为空）
        result = await db.execute(
            text(f"""
                UPDATE customer_journey_timings
                SET {column} = :timestamp,
                    order_id = COALESCE(order_id, :order_id),
                    table_id = COALESCE(table_id, :table_id),
                    updated_at = NOW()
                WHERE id = :journey_id
                  AND is_deleted = FALSE
                RETURNING id, tenant_id, store_id, order_id, table_id,
                          journey_date, arrived_at, seated_at, ordered_at,
                          first_served_at, paid_at, left_at,
                          wait_minutes, order_minutes, serve_minutes,
                          dine_minutes, total_minutes,
                          party_size, is_delivery
            """),
            {
                "timestamp": timestamp,
                "order_id": str(order_id) if order_id else None,
                "table_id": str(table_id) if table_id else None,
                "journey_id": str(journey_id),
            },
        )
        row = result.mappings().first()
        await db.commit()

        log.info(
            "journey_event_recorded",
            journey_id=str(journey_id),
            store_id=str(store_id),
            event_type=event_type,
        )
        return _row_to_dict(row)

    async def _find_journey_id(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        order_id: Optional[uuid.UUID],
        table_id: Optional[uuid.UUID],
    ) -> Optional[uuid.UUID]:
        """查找活跃旅程 ID。优先 order_id > table_id > 最近活跃。"""
        if order_id:
            result = await db.execute(
                text("""
                    SELECT id FROM customer_journey_timings
                    WHERE order_id = :order_id
                      AND tenant_id = :tenant_id
                      AND is_deleted = FALSE
                    ORDER BY created_at DESC LIMIT 1
                """),
                {"order_id": str(order_id), "tenant_id": str(tenant_id)},
            )
            row = result.scalar_one_or_none()
            if row:
                return row

        if table_id:
            result = await db.execute(
                text("""
                    SELECT id FROM customer_journey_timings
                    WHERE table_id = :table_id
                      AND store_id = :store_id
                      AND tenant_id = :tenant_id
                      AND paid_at IS NULL
                      AND is_deleted = FALSE
                    ORDER BY created_at DESC LIMIT 1
                """),
                {
                    "table_id": str(table_id),
                    "store_id": str(store_id),
                    "tenant_id": str(tenant_id),
                },
            )
            row = result.scalar_one_or_none()
            if row:
                return row

        # 兜底：最近活跃未结账
        result = await db.execute(
            text("""
                SELECT id FROM customer_journey_timings
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND paid_at IS NULL
                  AND arrived_at IS NOT NULL
                  AND is_deleted = FALSE
                ORDER BY created_at DESC LIMIT 1
            """),
            {"store_id": str(store_id), "tenant_id": str(tenant_id)},
        )
        return result.scalar_one_or_none()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  check_sla_violations — 实时 SLA 违规检查
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def check_sla_violations(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        sla: Optional[dict[str, float]] = None,
    ) -> list[dict[str, Any]]:
        """实时 SLA 违规检查。

        扫描当前活跃旅程（arrived 但未 paid）：
        - 等位 > SLA → 推送前台
        - 上菜 > SLA → 推送厨房
        返回违规列表 [{order_id, violation_type, current_minutes, sla_minutes}]
        """
        sla_config = sla or self.DEFAULT_SLA
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        result = await db.execute(
            text("""
                SELECT
                    cjt.id,
                    cjt.order_id,
                    cjt.table_id,
                    cjt.arrived_at,
                    cjt.seated_at,
                    cjt.ordered_at,
                    cjt.first_served_at,
                    cjt.paid_at,
                    t.name AS table_name
                FROM customer_journey_timings cjt
                LEFT JOIN tables t ON t.id = cjt.table_id
                WHERE cjt.store_id = :store_id
                  AND cjt.tenant_id = :tenant_id
                  AND cjt.paid_at IS NULL
                  AND cjt.arrived_at IS NOT NULL
                  AND cjt.is_deleted = FALSE
            """),
            {"store_id": str(store_id), "tenant_id": str(tenant_id)},
        )
        rows = result.mappings().all()
        now = datetime.now(timezone.utc)
        violations: list[dict[str, Any]] = []

        for row in rows:
            # 等位超时：已到店但未入座
            if row["arrived_at"] and not row["seated_at"]:
                wait_min = (now - row["arrived_at"]).total_seconds() / 60
                if wait_min > sla_config["wait"]:
                    violations.append({
                        "journey_id": str(row["id"]),
                        "order_id": str(row["order_id"]) if row["order_id"] else None,
                        "violation_type": "wait",
                        "violation_label": "等位超时",
                        "current_minutes": round(wait_min, 1),
                        "sla_minutes": sla_config["wait"],
                        "table_name": row["table_name"],
                        "target": "前台",
                    })

            # 点单超时：已入座但未点单
            if row["seated_at"] and not row["ordered_at"]:
                order_min = (now - row["seated_at"]).total_seconds() / 60
                if order_min > sla_config["order"]:
                    violations.append({
                        "journey_id": str(row["id"]),
                        "order_id": str(row["order_id"]) if row["order_id"] else None,
                        "violation_type": "order",
                        "violation_label": "点单超时",
                        "current_minutes": round(order_min, 1),
                        "sla_minutes": sla_config["order"],
                        "table_name": row["table_name"],
                        "target": "服务员",
                    })

            # 上菜超时：已点单但首道菜未上
            if row["ordered_at"] and not row["first_served_at"]:
                serve_min = (now - row["ordered_at"]).total_seconds() / 60
                if serve_min > sla_config["serve"]:
                    violations.append({
                        "journey_id": str(row["id"]),
                        "order_id": str(row["order_id"]) if row["order_id"] else None,
                        "violation_type": "serve",
                        "violation_label": "上菜超时",
                        "current_minutes": round(serve_min, 1),
                        "sla_minutes": sla_config["serve"],
                        "table_name": row["table_name"],
                        "target": "厨房",
                    })

            # 总用餐超时
            if row["arrived_at"]:
                total_min = (now - row["arrived_at"]).total_seconds() / 60
                if total_min > sla_config["total"]:
                    violations.append({
                        "journey_id": str(row["id"]),
                        "order_id": str(row["order_id"]) if row["order_id"] else None,
                        "violation_type": "total",
                        "violation_label": "总用餐超时",
                        "current_minutes": round(total_min, 1),
                        "sla_minutes": sla_config["total"],
                        "table_name": row["table_name"],
                        "target": "店长",
                    })

        log.info(
            "sla_violations_checked",
            store_id=str(store_id),
            active_journeys=len(rows),
            violations=len(violations),
        )
        return violations

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  get_journey_stats — 旅程统计
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_journey_stats(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        date_from: date,
        date_to: date,
        sla: Optional[dict[str, float]] = None,
    ) -> dict[str, Any]:
        """旅程统计：各环节 AVG/P50/P90 + SLA 达标率 + 时段分布 + 趋势。"""
        sla_config = sla or self.DEFAULT_SLA
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        # 1) 各环节 AVG / P50 / P90
        percentile_result = await db.execute(
            text("""
                SELECT
                    COUNT(*)                                           AS total_journeys,
                    ROUND(AVG(wait_minutes)::NUMERIC, 1)               AS wait_avg,
                    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY wait_minutes)::NUMERIC, 1)  AS wait_p50,
                    ROUND(PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY wait_minutes)::NUMERIC, 1)  AS wait_p90,
                    ROUND(AVG(order_minutes)::NUMERIC, 1)              AS order_avg,
                    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY order_minutes)::NUMERIC, 1) AS order_p50,
                    ROUND(PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY order_minutes)::NUMERIC, 1) AS order_p90,
                    ROUND(AVG(serve_minutes)::NUMERIC, 1)              AS serve_avg,
                    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY serve_minutes)::NUMERIC, 1) AS serve_p50,
                    ROUND(PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY serve_minutes)::NUMERIC, 1) AS serve_p90,
                    ROUND(AVG(total_minutes)::NUMERIC, 1)              AS total_avg,
                    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_minutes)::NUMERIC, 1) AS total_p50,
                    ROUND(PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY total_minutes)::NUMERIC, 1) AS total_p90
                FROM customer_journey_timings
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND journey_date BETWEEN :date_from AND :date_to
                  AND paid_at IS NOT NULL
                  AND is_deleted = FALSE
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        p = percentile_result.mappings().first()

        # 2) SLA 达标率
        sla_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE wait_minutes IS NOT NULL AND wait_minutes <= :sla_wait)   AS wait_ok,
                    COUNT(*) FILTER (WHERE wait_minutes IS NOT NULL)                                  AS wait_total,
                    COUNT(*) FILTER (WHERE order_minutes IS NOT NULL AND order_minutes <= :sla_order) AS order_ok,
                    COUNT(*) FILTER (WHERE order_minutes IS NOT NULL)                                 AS order_total,
                    COUNT(*) FILTER (WHERE serve_minutes IS NOT NULL AND serve_minutes <= :sla_serve) AS serve_ok,
                    COUNT(*) FILTER (WHERE serve_minutes IS NOT NULL)                                 AS serve_total,
                    COUNT(*) FILTER (WHERE total_minutes IS NOT NULL AND total_minutes <= :sla_total) AS total_ok,
                    COUNT(*) FILTER (WHERE total_minutes IS NOT NULL)                                 AS total_total
                FROM customer_journey_timings
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND journey_date BETWEEN :date_from AND :date_to
                  AND paid_at IS NOT NULL
                  AND is_deleted = FALSE
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "date_from": date_from,
                "date_to": date_to,
                "sla_wait": sla_config["wait"],
                "sla_order": sla_config["order"],
                "sla_serve": sla_config["serve"],
                "sla_total": sla_config["total"],
            },
        )
        s = sla_result.mappings().first()

        def _rate(ok: int, total: int) -> float:
            return round(ok * 100.0 / total, 1) if total > 0 else 100.0

        sla_compliance = {
            "wait": _rate(int(s["wait_ok"] or 0), int(s["wait_total"] or 0)),
            "order": _rate(int(s["order_ok"] or 0), int(s["order_total"] or 0)),
            "serve": _rate(int(s["serve_ok"] or 0), int(s["serve_total"] or 0)),
            "total": _rate(int(s["total_ok"] or 0), int(s["total_total"] or 0)),
        }

        # 3) 时段分布（午市 vs 晚市）
        period_result = await db.execute(
            text("""
                SELECT
                    CASE
                        WHEN EXTRACT(HOUR FROM arrived_at) BETWEEN 10 AND 14 THEN 'lunch'
                        WHEN EXTRACT(HOUR FROM arrived_at) BETWEEN 17 AND 21 THEN 'dinner'
                        ELSE 'other'
                    END AS meal_period,
                    COUNT(*) AS cnt,
                    ROUND(AVG(total_minutes)::NUMERIC, 1) AS avg_total
                FROM customer_journey_timings
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND journey_date BETWEEN :date_from AND :date_to
                  AND paid_at IS NOT NULL
                  AND is_deleted = FALSE
                GROUP BY meal_period
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        period_distribution = {
            row["meal_period"]: {
                "count": int(row["cnt"]),
                "avg_total_minutes": float(row["avg_total"]) if row["avg_total"] else 0.0,
            }
            for row in period_result.mappings().all()
        }

        # 4) 每日趋势
        trend_result = await db.execute(
            text("""
                SELECT
                    journey_date,
                    COUNT(*) AS cnt,
                    ROUND(AVG(wait_minutes)::NUMERIC, 1)  AS avg_wait,
                    ROUND(AVG(serve_minutes)::NUMERIC, 1) AS avg_serve,
                    ROUND(AVG(total_minutes)::NUMERIC, 1) AS avg_total
                FROM customer_journey_timings
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND journey_date BETWEEN :date_from AND :date_to
                  AND paid_at IS NOT NULL
                  AND is_deleted = FALSE
                GROUP BY journey_date
                ORDER BY journey_date
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        trends = [
            {
                "date": str(row["journey_date"]),
                "count": int(row["cnt"]),
                "avg_wait_minutes": float(row["avg_wait"]) if row["avg_wait"] else 0.0,
                "avg_serve_minutes": float(row["avg_serve"]) if row["avg_serve"] else 0.0,
                "avg_total_minutes": float(row["avg_total"]) if row["avg_total"] else 0.0,
            }
            for row in trend_result.mappings().all()
        ]

        log.info(
            "journey_stats_computed",
            store_id=str(store_id),
            date_range=[str(date_from), str(date_to)],
            total_journeys=int(p["total_journeys"]) if p else 0,
        )

        return {
            "date_range": [str(date_from), str(date_to)],
            "total_journeys": int(p["total_journeys"]) if p else 0,
            "percentiles": {
                "wait": {
                    "avg": float(p["wait_avg"]) if p and p["wait_avg"] else None,
                    "p50": float(p["wait_p50"]) if p and p["wait_p50"] else None,
                    "p90": float(p["wait_p90"]) if p and p["wait_p90"] else None,
                },
                "order": {
                    "avg": float(p["order_avg"]) if p and p["order_avg"] else None,
                    "p50": float(p["order_p50"]) if p and p["order_p50"] else None,
                    "p90": float(p["order_p90"]) if p and p["order_p90"] else None,
                },
                "serve": {
                    "avg": float(p["serve_avg"]) if p and p["serve_avg"] else None,
                    "p50": float(p["serve_p50"]) if p and p["serve_p50"] else None,
                    "p90": float(p["serve_p90"]) if p and p["serve_p90"] else None,
                },
                "total": {
                    "avg": float(p["total_avg"]) if p and p["total_avg"] else None,
                    "p50": float(p["total_p50"]) if p and p["total_p50"] else None,
                    "p90": float(p["total_p90"]) if p and p["total_p90"] else None,
                },
            },
            "sla_compliance": sla_compliance,
            "sla_config": sla_config,
            "period_distribution": period_distribution,
            "trends": trends,
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  get_active_journeys — 当前活跃旅程（实时看板）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_active_journeys(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        sla: Optional[dict[str, float]] = None,
    ) -> list[dict[str, Any]]:
        """当前活跃旅程（实时看板用）。

        返回所有已到店但未离店的顾客旅程，含每个环节的已耗时+是否超标。
        """
        sla_config = sla or self.DEFAULT_SLA
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        result = await db.execute(
            text("""
                SELECT
                    cjt.id,
                    cjt.order_id,
                    cjt.table_id,
                    cjt.journey_date,
                    cjt.arrived_at,
                    cjt.seated_at,
                    cjt.ordered_at,
                    cjt.first_served_at,
                    cjt.paid_at,
                    cjt.left_at,
                    cjt.party_size,
                    cjt.is_delivery,
                    t.name AS table_name
                FROM customer_journey_timings cjt
                LEFT JOIN tables t ON t.id = cjt.table_id
                WHERE cjt.store_id = :store_id
                  AND cjt.tenant_id = :tenant_id
                  AND cjt.arrived_at IS NOT NULL
                  AND cjt.left_at IS NULL
                  AND cjt.is_deleted = FALSE
                ORDER BY cjt.arrived_at
            """),
            {"store_id": str(store_id), "tenant_id": str(tenant_id)},
        )

        now = datetime.now(timezone.utc)
        journeys: list[dict[str, Any]] = []

        for row in result.mappings().all():
            stages: list[dict[str, Any]] = []
            current_stage = "arrived"

            # 等位阶段
            if row["arrived_at"] and not row["seated_at"]:
                elapsed = (now - row["arrived_at"]).total_seconds() / 60
                current_stage = "waiting"
                stages.append({
                    "stage": "wait",
                    "label": "等位",
                    "elapsed_minutes": round(elapsed, 1),
                    "sla_minutes": sla_config["wait"],
                    "exceeded": elapsed > sla_config["wait"],
                    "status": "active",
                })
            elif row["arrived_at"] and row["seated_at"]:
                elapsed = (row["seated_at"] - row["arrived_at"]).total_seconds() / 60
                stages.append({
                    "stage": "wait",
                    "label": "等位",
                    "elapsed_minutes": round(elapsed, 1),
                    "sla_minutes": sla_config["wait"],
                    "exceeded": elapsed > sla_config["wait"],
                    "status": "done",
                })

            # 点单阶段
            if row["seated_at"] and not row["ordered_at"]:
                elapsed = (now - row["seated_at"]).total_seconds() / 60
                current_stage = "ordering"
                stages.append({
                    "stage": "order",
                    "label": "点单",
                    "elapsed_minutes": round(elapsed, 1),
                    "sla_minutes": sla_config["order"],
                    "exceeded": elapsed > sla_config["order"],
                    "status": "active",
                })
            elif row["seated_at"] and row["ordered_at"]:
                elapsed = (row["ordered_at"] - row["seated_at"]).total_seconds() / 60
                stages.append({
                    "stage": "order",
                    "label": "点单",
                    "elapsed_minutes": round(elapsed, 1),
                    "sla_minutes": sla_config["order"],
                    "exceeded": elapsed > sla_config["order"],
                    "status": "done",
                })

            # 上菜阶段
            if row["ordered_at"] and not row["first_served_at"]:
                elapsed = (now - row["ordered_at"]).total_seconds() / 60
                current_stage = "cooking"
                stages.append({
                    "stage": "serve",
                    "label": "上菜",
                    "elapsed_minutes": round(elapsed, 1),
                    "sla_minutes": sla_config["serve"],
                    "exceeded": elapsed > sla_config["serve"],
                    "status": "active",
                })
            elif row["ordered_at"] and row["first_served_at"]:
                elapsed = (row["first_served_at"] - row["ordered_at"]).total_seconds() / 60
                stages.append({
                    "stage": "serve",
                    "label": "上菜",
                    "elapsed_minutes": round(elapsed, 1),
                    "sla_minutes": sla_config["serve"],
                    "exceeded": elapsed > sla_config["serve"],
                    "status": "done",
                })

            # 用餐阶段
            if row["first_served_at"] and not row["paid_at"]:
                elapsed = (now - row["first_served_at"]).total_seconds() / 60
                current_stage = "dining"
                stages.append({
                    "stage": "dine",
                    "label": "用餐",
                    "elapsed_minutes": round(elapsed, 1),
                    "sla_minutes": None,
                    "exceeded": False,
                    "status": "active",
                })
            elif row["first_served_at"] and row["paid_at"]:
                elapsed = (row["paid_at"] - row["first_served_at"]).total_seconds() / 60
                stages.append({
                    "stage": "dine",
                    "label": "用餐",
                    "elapsed_minutes": round(elapsed, 1),
                    "sla_minutes": None,
                    "exceeded": False,
                    "status": "done",
                })

            total_elapsed = (now - row["arrived_at"]).total_seconds() / 60

            journeys.append({
                "journey_id": str(row["id"]),
                "order_id": str(row["order_id"]) if row["order_id"] else None,
                "table_id": str(row["table_id"]) if row["table_id"] else None,
                "table_name": row["table_name"],
                "party_size": row["party_size"],
                "is_delivery": row["is_delivery"],
                "current_stage": current_stage,
                "total_elapsed_minutes": round(total_elapsed, 1),
                "total_exceeded": total_elapsed > sla_config["total"],
                "stages": stages,
                "arrived_at": row["arrived_at"].isoformat() if row["arrived_at"] else None,
            })

        log.info(
            "active_journeys_fetched",
            store_id=str(store_id),
            count=len(journeys),
        )
        return journeys


def _row_to_dict(row: Any) -> dict[str, Any]:
    """将数据库行转为字典，自动处理 UUID/datetime 序列化。"""
    result: dict[str, Any] = {}
    for key in row.keys():
        val = row[key]
        if isinstance(val, uuid.UUID):
            result[key] = str(val)
        elif isinstance(val, (datetime, date)):
            result[key] = val.isoformat() if val else None
        elif val is None:
            result[key] = None
        else:
            result[key] = val
    return result
