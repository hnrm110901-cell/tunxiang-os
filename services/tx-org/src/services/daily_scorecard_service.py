"""日KPI得分卡服务

按角色差异化的日KPI自动评分系统。
每个角色有独立的KPI维度及权重，系统从业务数据自动计算得分，
支持同角色/全员排名、昨日对比、亮点/待改善提炼、IM推送。

与 performance_scoring_service.py 的区别：
  - performance_scoring_service: 月度主观打分（6维度，人工评分）
  - daily_scorecard_service: 日自动计算（角色KPI维度，数据驱动）

金额单位：分（fen）。RLS：每次 DB 操作前设置 app.tenant_id。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: UUID) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


class DailyScorecardService:
    """日KPI得分卡引擎"""

    # ── 角色KPI维度定义 ─────────────────────────────────────────────
    ROLE_KPI_CONFIG: dict[str, dict[str, dict[str, Any]]] = {
        "waiter": {
            "turnover_rate": {
                "weight": 0.30, "target": 3.0, "unit": "次",
                "higher_better": True, "label": "翻台率",
            },
            "avg_ticket_fen": {
                "weight": 0.30, "target": 10000, "unit": "元",
                "higher_better": True, "label": "客单价",
            },
            "complaint_rate": {
                "weight": 0.40, "target": 0.02, "unit": "%",
                "higher_better": False, "label": "投诉率",
            },
        },
        "chef": {
            "serve_speed_min": {
                "weight": 0.40, "target": 15.0, "unit": "分钟",
                "higher_better": False, "label": "出餐速度",
            },
            "waste_rate": {
                "weight": 0.30, "target": 0.05, "unit": "%",
                "higher_better": False, "label": "浪费率",
            },
            "dish_rating": {
                "weight": 0.30, "target": 4.5, "unit": "分",
                "higher_better": True, "label": "菜品评分",
            },
        },
        "purchaser": {
            "on_time_rate": {
                "weight": 0.40, "target": 0.95, "unit": "%",
                "higher_better": True, "label": "到货准时率",
            },
            "price_variance": {
                "weight": 0.35, "target": 0.05, "unit": "%",
                "higher_better": False, "label": "价格偏差率",
            },
            "waste_from_overstock": {
                "weight": 0.25, "target": 0.03, "unit": "%",
                "higher_better": False, "label": "过量库存浪费率",
            },
        },
        "manager": {
            "revenue_achievement": {
                "weight": 0.25, "target": 1.0, "unit": "%",
                "higher_better": True, "label": "营收达成率",
            },
            "profit_margin": {
                "weight": 0.25, "target": 0.15, "unit": "%",
                "higher_better": True, "label": "利润率",
            },
            "employee_retention": {
                "weight": 0.25, "target": 0.90, "unit": "%",
                "higher_better": True, "label": "员工留存率",
            },
            "customer_satisfaction": {
                "weight": 0.25, "target": 4.0, "unit": "分",
                "higher_better": True, "label": "顾客满意度",
            },
        },
    }

    # ── 核心计算方法 ─────────────────────────────────────────────────

    async def compute_daily_scores(
        self,
        db: AsyncSession,
        store_id: UUID,
        tenant_id: UUID,
        target_date: date,
    ) -> list[dict[str, Any]]:
        """计算指定门店所有员工的日得分卡

        1. 查询该店所有在岗员工+角色
        2. 按角色查询当日KPI原始数据
        3. 每个指标: value -> score(0-100)
        4. 加权总分
        5. 排名(同角色内+全员)
        6. 与昨日对比
        7. 生成亮点+待改善文本
        8. 批量UPSERT到daily_scorecards表
        """
        await _set_tenant(db, tenant_id)

        # 1. 查询在岗员工
        employees = await self._fetch_store_employees(db, tenant_id, store_id)
        if not employees:
            log.info("scorecard.no_employees", store_id=str(store_id))
            return []

        # 2-4. 为每个员工计算得分
        scored: list[dict[str, Any]] = []
        for emp in employees:
            role = str(emp.get("role", "")).strip().lower()
            kpi_config = self.ROLE_KPI_CONFIG.get(role)
            if kpi_config is None:
                log.debug(
                    "scorecard.unknown_role_skip",
                    employee_id=str(emp["employee_id"]),
                    role=role,
                )
                continue

            raw_values = await self._fetch_kpi_raw_values(
                db, tenant_id, store_id, UUID(str(emp["employee_id"])), role, target_date,
            )

            dimension_scores: dict[str, dict[str, Any]] = {}
            weighted_total = 0.0
            for dim_key, cfg in kpi_config.items():
                value = raw_values.get(dim_key, 0.0)
                score = self._compute_dimension_score(
                    value, cfg["target"], cfg["higher_better"],
                )
                weighted_total += score * cfg["weight"]
                dimension_scores[dim_key] = {
                    "value": round(value, 4),
                    "score": score,
                    "weight": cfg["weight"],
                    "label": cfg["label"],
                    "unit": cfg["unit"],
                }

            total_score = round(min(100.0, max(0.0, weighted_total)), 1)

            scored.append({
                "employee_id": str(emp["employee_id"]),
                "employee_name": emp.get("emp_name", ""),
                "role": role,
                "total_score": total_score,
                "dimension_scores": dimension_scores,
            })

        # 5. 排名
        scored.sort(key=lambda x: x["total_score"], reverse=True)
        # 全员排名
        for idx, item in enumerate(scored, start=1):
            item["rank_total"] = idx

        # 同角色排名
        role_groups: dict[str, list[dict[str, Any]]] = {}
        for item in scored:
            role_groups.setdefault(item["role"], []).append(item)
        for role_items in role_groups.values():
            role_items.sort(key=lambda x: x["total_score"], reverse=True)
            for idx, item in enumerate(role_items, start=1):
                item["rank_in_role"] = idx
                item["total_employees_in_role"] = len(role_items)

        # 6. 昨日对比
        yesterday = target_date - timedelta(days=1)
        yesterday_map = await self._fetch_yesterday_scores(
            db, tenant_id, store_id, yesterday,
        )

        # 7. 生成亮点+待改善 & 8. 批量UPSERT
        results: list[dict[str, Any]] = []
        for item in scored:
            emp_id = item["employee_id"]
            yesterday_score = yesterday_map.get(emp_id)
            vs_yesterday = (
                round(item["total_score"] - yesterday_score, 1)
                if yesterday_score is not None
                else None
            )

            highlights, improvements = self._generate_insights(
                item["dimension_scores"], item["role"],
            )

            # UPSERT
            await self._upsert_scorecard(
                db, tenant_id, store_id, item, target_date,
                vs_yesterday, highlights, improvements,
            )

            result = {
                "employee_id": emp_id,
                "employee_name": item["employee_name"],
                "role": item["role"],
                "total_score": item["total_score"],
                "dimension_scores": item["dimension_scores"],
                "rank_in_role": item["rank_in_role"],
                "rank_total": item["rank_total"],
                "total_employees_in_role": item["total_employees_in_role"],
                "vs_yesterday": vs_yesterday,
                "highlights": highlights,
                "improvements": improvements,
                "score_date": target_date.isoformat(),
            }
            results.append(result)

        log.info(
            "scorecard.computed",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            date=target_date.isoformat(),
            employee_count=len(results),
        )
        return results

    @staticmethod
    def _compute_dimension_score(
        value: float,
        target: float,
        higher_better: bool,
    ) -> int:
        """单维度得分计算(0-100)

        higher_better=True:  score = min(100, value/target * 100)
        higher_better=False: score = min(100, target/value * 100) if value>0
        """
        if higher_better:
            if target <= 0:
                return 50
            raw = (value / target) * 100.0
        else:
            if value <= 0:
                return 100  # 无不良数据即满分
            raw = (target / value) * 100.0
        return int(min(100, max(0, round(raw))))

    async def push_scorecards_via_im(
        self,
        db: AsyncSession,
        store_id: UUID,
        tenant_id: UUID,
        target_date: date,
    ) -> int:
        """通过IM推送日得分卡到 notifications 表

        格式: "今日得分87分(排名3/12), TOP:翻台率3.2次(95分), 待改善:客单价偏低"
        返回推送人数
        """
        await _set_tenant(db, tenant_id)

        rows = await db.execute(
            text("""
                SELECT id, employee_id, employee_name, role, total_score,
                       rank_total, highlights, improvements, dimension_scores
                FROM daily_scorecards
                WHERE tenant_id = :tid AND store_id = :sid AND score_date = :d
                  AND is_deleted = FALSE AND pushed_at IS NULL
                ORDER BY rank_total
            """),
            {"tid": tenant_id, "sid": store_id, "d": target_date},
        )
        cards = rows.mappings().fetchall()
        if not cards:
            return 0

        # 总员工数（用于排名展示）
        total_emp = len(cards)
        pushed = 0

        for card in cards:
            card_id = card["id"]
            emp_id = card["employee_id"]
            name = card["employee_name"] or ""
            score = float(card["total_score"])
            rank = int(card["rank_total"] or 0)
            highlights_arr = card["highlights"] or []
            improvements_arr = card["improvements"] or []

            top_str = highlights_arr[0] if highlights_arr else "无"
            imp_str = improvements_arr[0] if improvements_arr else "无"

            body = (
                f"今日得分{score:.0f}分(排名{rank}/{total_emp}), "
                f"TOP:{top_str}, 待改善:{imp_str}"
            )
            title = f"【日得分卡】{name} {target_date.isoformat()}"

            try:
                await db.execute(
                    text("""
                        INSERT INTO notifications
                            (id, tenant_id, target_type, target_id, title, body, channel,
                             created_at, is_deleted)
                        VALUES
                            (gen_random_uuid(), :tid, 'employee', :emp_id, :title, :body,
                             'im', NOW(), FALSE)
                    """),
                    {
                        "tid": tenant_id,
                        "emp_id": emp_id,
                        "title": title,
                        "body": body,
                    },
                )

                await db.execute(
                    text("""
                        UPDATE daily_scorecards
                        SET pushed_at = NOW(), updated_at = NOW()
                        WHERE id = :cid AND tenant_id = :tid
                    """),
                    {"cid": card_id, "tid": tenant_id},
                )
                pushed += 1
            except (ProgrammingError, DBAPIError) as exc:
                log.warning(
                    "scorecard.push_failed",
                    employee_id=str(emp_id),
                    error=str(exc),
                )

        log.info(
            "scorecard.pushed",
            store_id=str(store_id),
            date=target_date.isoformat(),
            pushed=pushed,
        )
        return pushed

    async def get_scorecard(
        self,
        db: AsyncSession,
        store_id: UUID,
        tenant_id: UUID,
        employee_id: UUID,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        """查询个人得分卡历史"""
        await _set_tenant(db, tenant_id)

        rows = await db.execute(
            text("""
                SELECT id, score_date, total_score, dimension_scores,
                       rank_in_role, rank_total, total_employees_in_role,
                       vs_yesterday, highlights, improvements, pushed_at,
                       role, employee_name
                FROM daily_scorecards
                WHERE tenant_id = :tid AND store_id = :sid
                  AND employee_id = :eid
                  AND score_date >= :d0 AND score_date <= :d1
                  AND is_deleted = FALSE
                ORDER BY score_date DESC
            """),
            {
                "tid": tenant_id,
                "sid": store_id,
                "eid": employee_id,
                "d0": date_from,
                "d1": date_to,
            },
        )
        items: list[dict[str, Any]] = []
        for r in rows.mappings().fetchall():
            row = dict(r)
            row["id"] = str(row["id"])
            row["score_date"] = row["score_date"].isoformat() if hasattr(row["score_date"], "isoformat") else str(row["score_date"])
            row["total_score"] = float(row["total_score"]) if row["total_score"] is not None else 0.0
            row["vs_yesterday"] = float(row["vs_yesterday"]) if row["vs_yesterday"] is not None else None
            ds = row.get("dimension_scores")
            if isinstance(ds, str):
                row["dimension_scores"] = json.loads(ds)
            if row.get("pushed_at") and hasattr(row["pushed_at"], "isoformat"):
                row["pushed_at"] = row["pushed_at"].isoformat()
            items.append(row)
        return items

    async def get_store_ranking(
        self,
        db: AsyncSession,
        store_id: UUID,
        tenant_id: UUID,
        target_date: date,
        role: str | None = None,
    ) -> list[dict[str, Any]]:
        """门店排行榜(可按角色筛选)"""
        await _set_tenant(db, tenant_id)

        conds = [
            "tenant_id = :tid",
            "store_id = :sid",
            "score_date = :d",
            "is_deleted = FALSE",
        ]
        params: dict[str, Any] = {"tid": tenant_id, "sid": store_id, "d": target_date}

        if role:
            conds.append("role = :role")
            params["role"] = role.strip().lower()

        where = " AND ".join(conds)
        rows = await db.execute(
            text(f"""
                SELECT employee_id, employee_name, role, total_score,
                       dimension_scores, rank_in_role, rank_total,
                       total_employees_in_role, vs_yesterday,
                       highlights, improvements
                FROM daily_scorecards
                WHERE {where}
                ORDER BY total_score DESC, employee_name
            """),
            params,
        )
        items: list[dict[str, Any]] = []
        for r in rows.mappings().fetchall():
            row = dict(r)
            row["employee_id"] = str(row["employee_id"])
            row["total_score"] = float(row["total_score"]) if row["total_score"] is not None else 0.0
            row["vs_yesterday"] = float(row["vs_yesterday"]) if row["vs_yesterday"] is not None else None
            ds = row.get("dimension_scores")
            if isinstance(ds, str):
                row["dimension_scores"] = json.loads(ds)
            items.append(row)
        return items

    # ── 内部辅助方法 ─────────────────────────────────────────────────

    async def _fetch_store_employees(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
    ) -> list[dict[str, Any]]:
        """查询门店在岗员工"""
        try:
            rows = await db.execute(
                text("""
                    SELECT e.id::text AS employee_id, e.emp_name,
                           COALESCE(p.code, e.role, '') AS role
                    FROM employees e
                    LEFT JOIN positions p ON p.id = e.position_id AND p.tenant_id = e.tenant_id
                    WHERE e.tenant_id = :tid
                      AND e.store_id = :sid
                      AND e.is_deleted = FALSE
                      AND COALESCE(e.status, 'active') = 'active'
                    ORDER BY e.emp_name
                """),
                {"tid": tenant_id, "sid": store_id},
            )
            return [dict(r) for r in rows.mappings().fetchall()]
        except (ProgrammingError, DBAPIError) as exc:
            log.warning("scorecard.fetch_employees_failed", error=str(exc))
            return []

    async def _fetch_kpi_raw_values(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        employee_id: UUID,
        role: str,
        target_date: date,
    ) -> dict[str, float]:
        """按角色从业务表获取KPI原始数据，表不可用时降级为基准值"""
        if role == "waiter":
            return await self._fetch_waiter_kpi(db, tenant_id, store_id, employee_id, target_date)
        if role == "chef":
            return await self._fetch_chef_kpi(db, tenant_id, store_id, employee_id, target_date)
        if role == "purchaser":
            return await self._fetch_purchaser_kpi(db, tenant_id, store_id, employee_id, target_date)
        if role == "manager":
            return await self._fetch_manager_kpi(db, tenant_id, store_id, target_date)
        return {}

    async def _fetch_waiter_kpi(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        employee_id: UUID,
        target_date: date,
    ) -> dict[str, float]:
        """服务员KPI: 翻台率、客单价、投诉率"""
        result: dict[str, float] = {
            "turnover_rate": 0.0,
            "avg_ticket_fen": 0.0,
            "complaint_rate": 0.0,
        }

        # 翻台率 & 客单价 — 从 orders 表
        try:
            row = await db.execute(
                text("""
                    SELECT COUNT(*) AS order_count,
                           COALESCE(AVG(final_amount_fen), 0) AS avg_ticket
                    FROM orders
                    WHERE tenant_id = :tid
                      AND store_id = :sid
                      AND created_at::date = :d
                      AND status NOT IN ('cancelled', 'refunded')
                """),
                {"tid": tenant_id, "sid": store_id, "d": target_date},
            )
            r = row.mappings().first()
            if r:
                order_count = int(r["order_count"] or 0)
                # 翻台率 = 订单数 / 桌台数（简化：按门店30桌估算）
                table_count = 30
                try:
                    tbl_row = await db.execute(
                        text("""
                            SELECT COUNT(*) AS cnt FROM tables
                            WHERE store_id = :sid AND is_deleted = FALSE
                        """),
                        {"sid": store_id},
                    )
                    tbl_r = tbl_row.mappings().first()
                    if tbl_r and int(tbl_r["cnt"] or 0) > 0:
                        table_count = int(tbl_r["cnt"])
                except (ProgrammingError, DBAPIError):
                    pass  # 降级使用默认桌数

                result["turnover_rate"] = round(order_count / max(table_count, 1), 2)
                result["avg_ticket_fen"] = float(r["avg_ticket"] or 0)
        except (ProgrammingError, DBAPIError) as exc:
            log.warning("scorecard.waiter_orders_unavailable", error=str(exc))

        # 投诉率 — 从 satisfaction_ratings 表降级
        try:
            row = await db.execute(
                text("""
                    SELECT COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE overall_score <= 2) AS bad
                    FROM satisfaction_ratings
                    WHERE tenant_id = :tid AND store_id = :sid
                      AND created_at::date = :d AND is_deleted = FALSE
                """),
                {"tid": tenant_id, "sid": store_id, "d": target_date},
            )
            r = row.mappings().first()
            if r and int(r["total"] or 0) > 0:
                result["complaint_rate"] = round(int(r["bad"] or 0) / int(r["total"]), 4)
        except (ProgrammingError, DBAPIError) as exc:
            log.debug("scorecard.satisfaction_unavailable", error=str(exc))

        return result

    async def _fetch_chef_kpi(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        employee_id: UUID,
        target_date: date,
    ) -> dict[str, float]:
        """厨师KPI: 出餐速度、浪费率、菜品评分"""
        result: dict[str, float] = {
            "serve_speed_min": 15.0,  # 基准值
            "waste_rate": 0.05,
            "dish_rating": 4.0,
        }

        # 出餐速度 — 从 customer_journey_timings
        try:
            row = await db.execute(
                text("""
                    SELECT AVG(
                        EXTRACT(EPOCH FROM (first_served_at - ordered_at)) / 60
                    ) AS avg_serve_min
                    FROM customer_journey_timings
                    WHERE tenant_id = :tid AND store_id = :sid
                      AND journey_date = :d AND is_deleted = FALSE
                      AND first_served_at IS NOT NULL AND ordered_at IS NOT NULL
                """),
                {"tid": tenant_id, "sid": store_id, "d": target_date},
            )
            r = row.mappings().first()
            if r and r["avg_serve_min"] is not None:
                result["serve_speed_min"] = round(float(r["avg_serve_min"]), 1)
        except (ProgrammingError, DBAPIError) as exc:
            log.debug("scorecard.chef_serve_speed_unavailable", error=str(exc))

        # 菜品评分 — 从 satisfaction_ratings
        try:
            row = await db.execute(
                text("""
                    SELECT AVG(food_score) AS avg_food
                    FROM satisfaction_ratings
                    WHERE tenant_id = :tid AND store_id = :sid
                      AND created_at::date = :d AND is_deleted = FALSE
                      AND food_score IS NOT NULL
                """),
                {"tid": tenant_id, "sid": store_id, "d": target_date},
            )
            r = row.mappings().first()
            if r and r["avg_food"] is not None:
                result["dish_rating"] = round(float(r["avg_food"]), 1)
        except (ProgrammingError, DBAPIError) as exc:
            log.debug("scorecard.chef_dish_rating_unavailable", error=str(exc))

        return result

    async def _fetch_purchaser_kpi(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        employee_id: UUID,
        target_date: date,
    ) -> dict[str, float]:
        """采购员KPI: 到货准时率、价格偏差率、过量库存浪费率（降级基准值）"""
        result: dict[str, float] = {
            "on_time_rate": 0.90,
            "price_variance": 0.05,
            "waste_from_overstock": 0.03,
        }

        # 到货准时率 — 查 purchase_orders 表
        try:
            row = await db.execute(
                text("""
                    SELECT COUNT(*) AS total,
                           COUNT(*) FILTER (
                               WHERE actual_delivery_date <= expected_delivery_date
                           ) AS on_time
                    FROM purchase_orders
                    WHERE tenant_id = :tid AND store_id = :sid
                      AND actual_delivery_date IS NOT NULL
                      AND actual_delivery_date::date
                          BETWEEN :d - INTERVAL '30 days' AND :d
                      AND is_deleted = FALSE
                """),
                {"tid": tenant_id, "sid": store_id, "d": target_date},
            )
            r = row.mappings().first()
            if r and int(r["total"] or 0) > 0:
                result["on_time_rate"] = round(int(r["on_time"] or 0) / int(r["total"]), 4)
        except (ProgrammingError, DBAPIError) as exc:
            log.debug("scorecard.purchaser_ontime_unavailable", error=str(exc))

        return result

    async def _fetch_manager_kpi(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        target_date: date,
    ) -> dict[str, float]:
        """店长KPI: 营收达成率、利润率、员工留存率、顾客满意度"""
        result: dict[str, float] = {
            "revenue_achievement": 0.80,
            "profit_margin": 0.10,
            "employee_retention": 0.85,
            "customer_satisfaction": 3.5,
        }

        # 营收达成率 — orders 当月累计 vs 目标
        try:
            first_of_month = target_date.replace(day=1)
            row = await db.execute(
                text("""
                    SELECT COALESCE(SUM(final_amount_fen), 0) AS actual_fen
                    FROM orders
                    WHERE tenant_id = :tid AND store_id = :sid
                      AND created_at::date >= :m0
                      AND created_at::date <= :d
                      AND status NOT IN ('cancelled', 'refunded')
                """),
                {"tid": tenant_id, "sid": store_id, "m0": first_of_month, "d": target_date},
            )
            r = row.mappings().first()
            actual_fen = int(r["actual_fen"] or 0) if r else 0

            # 查目标
            target_row = await db.execute(
                text("""
                    SELECT revenue_target_fen FROM stores
                    WHERE id = :sid AND tenant_id = :tid AND is_deleted = FALSE
                """),
                {"sid": store_id, "tid": tenant_id},
            )
            t = target_row.mappings().first()
            target_fen = int(t["revenue_target_fen"] or 0) if t and t["revenue_target_fen"] else 0

            if target_fen > 0:
                # 按日期比例折算月目标
                days_in_month = (target_date - first_of_month).days + 1
                import calendar
                _, total_days = calendar.monthrange(target_date.year, target_date.month)
                prorated_target = target_fen * (days_in_month / total_days)
                result["revenue_achievement"] = round(actual_fen / max(prorated_target, 1), 4)
        except (ProgrammingError, DBAPIError) as exc:
            log.debug("scorecard.manager_revenue_unavailable", error=str(exc))

        # 顾客满意度
        try:
            row = await db.execute(
                text("""
                    SELECT AVG(overall_score) AS avg_sat
                    FROM satisfaction_ratings
                    WHERE tenant_id = :tid AND store_id = :sid
                      AND created_at::date = :d AND is_deleted = FALSE
                """),
                {"tid": tenant_id, "sid": store_id, "d": target_date},
            )
            r = row.mappings().first()
            if r and r["avg_sat"] is not None:
                result["customer_satisfaction"] = round(float(r["avg_sat"]), 1)
        except (ProgrammingError, DBAPIError) as exc:
            log.debug("scorecard.manager_satisfaction_unavailable", error=str(exc))

        return result

    async def _fetch_yesterday_scores(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        yesterday: date,
    ) -> dict[str, float]:
        """获取昨日得分map: employee_id -> total_score"""
        try:
            rows = await db.execute(
                text("""
                    SELECT employee_id::text, total_score
                    FROM daily_scorecards
                    WHERE tenant_id = :tid AND store_id = :sid
                      AND score_date = :d AND is_deleted = FALSE
                """),
                {"tid": tenant_id, "sid": store_id, "d": yesterday},
            )
            return {
                str(r["employee_id"]): float(r["total_score"])
                for r in rows.mappings().fetchall()
            }
        except (ProgrammingError, DBAPIError):
            return {}

    @staticmethod
    def _generate_insights(
        dimension_scores: dict[str, dict[str, Any]],
        role: str,
    ) -> tuple[list[str], list[str]]:
        """根据各维度得分生成亮点和待改善文本"""
        highlights: list[str] = []
        improvements: list[str] = []

        for dim_key, dim_data in dimension_scores.items():
            score = dim_data.get("score", 0)
            value = dim_data.get("value", 0)
            label = dim_data.get("label", dim_key)
            unit = dim_data.get("unit", "")

            # 格式化显示值
            if unit == "元" and isinstance(value, (int, float)):
                display_val = f"{value / 100:.0f}{unit}"
            elif unit == "%":
                display_val = f"{value * 100:.1f}{unit}"
            else:
                display_val = f"{value}{unit}"

            if score >= 85:
                highlights.append(f"{label}{display_val}({score}分)")
            elif score < 60:
                suggestion = _IMPROVEMENT_SUGGESTIONS.get(dim_key, f"建议关注{label}")
                improvements.append(f"{label}偏低({display_val}), {suggestion}")

        return highlights, improvements

    async def _upsert_scorecard(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        item: dict[str, Any],
        score_date: date,
        vs_yesterday: float | None,
        highlights: list[str],
        improvements: list[str],
    ) -> None:
        """UPSERT 得分卡到 daily_scorecards 表"""
        dim_json = json.dumps(item["dimension_scores"], ensure_ascii=False)
        await db.execute(
            text("""
                INSERT INTO daily_scorecards
                    (id, tenant_id, store_id, employee_id, employee_name, role,
                     score_date, total_score, dimension_scores,
                     rank_in_role, rank_total, total_employees_in_role,
                     vs_yesterday, highlights, improvements)
                VALUES
                    (gen_random_uuid(), :tid, :sid, :eid, :ename, :role,
                     :d, :score, CAST(:dims AS jsonb),
                     :rir, :rt, :teir,
                     :vsy, :hl, :imp)
                ON CONFLICT (tenant_id, store_id, employee_id, score_date)
                DO UPDATE SET
                    total_score = EXCLUDED.total_score,
                    dimension_scores = EXCLUDED.dimension_scores,
                    rank_in_role = EXCLUDED.rank_in_role,
                    rank_total = EXCLUDED.rank_total,
                    total_employees_in_role = EXCLUDED.total_employees_in_role,
                    vs_yesterday = EXCLUDED.vs_yesterday,
                    highlights = EXCLUDED.highlights,
                    improvements = EXCLUDED.improvements,
                    updated_at = NOW()
            """),
            {
                "tid": tenant_id,
                "sid": store_id,
                "eid": UUID(item["employee_id"]),
                "ename": item["employee_name"],
                "role": item["role"],
                "d": score_date,
                "score": item["total_score"],
                "dims": dim_json,
                "rir": item.get("rank_in_role"),
                "rt": item.get("rank_total"),
                "teir": item.get("total_employees_in_role"),
                "vsy": vs_yesterday,
                "hl": highlights,
                "imp": improvements,
            },
        )


# ── 待改善建议模板 ───────────────────────────────────────────────────
_IMPROVEMENT_SUGGESTIONS: dict[str, str] = {
    "turnover_rate": "建议优化翻台流程,缩短等位时间",
    "avg_ticket_fen": "建议主推高毛利菜品或套餐",
    "complaint_rate": "建议加强服务培训,关注差评反馈",
    "serve_speed_min": "建议优化后厨动线,缩短出餐时间",
    "waste_rate": "建议精准备料,减少食材浪费",
    "dish_rating": "建议提升出品质量,关注顾客口味反馈",
    "on_time_rate": "建议优化供应商管理,确保准时送货",
    "price_variance": "建议多渠道比价,控制采购成本",
    "waste_from_overstock": "建议精准预估用量,减少过量采购",
    "revenue_achievement": "建议加强营销活动,提升门店客流",
    "profit_margin": "建议控制成本,优化菜品结构提升毛利",
    "employee_retention": "建议关注员工满意度,降低流失",
    "customer_satisfaction": "建议提升服务品质,关注顾客体验",
}
