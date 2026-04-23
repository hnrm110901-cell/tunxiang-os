"""员工经营贡献度服务

从POS交易数据为每个员工计算实时经营贡献分，替代主观绩效打分。
这是屯象OS核心差异化——i人事/乐才没有POS数据，只能手动打分。

贡献度模型（百分制）：
  - 营收贡献 30分：员工关联订单金额 vs 同岗位均值
  - 服务效率 25分：翻台速度/出餐速度 vs 标准
  - 客户满意 20分：退菜率(反向)/好评率/会员转化
  - 出勤纪律 15分：出勤率/迟到率(反向)
  - 团队协作 10分：跨岗支援次数/帮带新人

SQL降级策略：优先查真实表，表不存在时用基准分50。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# 默认基准分（表不存在或无数据时使用）
_BASELINE = 50.0


class ContributionScoreService:
    """员工经营贡献度计算引擎"""

    # 岗位权重差异化
    ROLE_WEIGHTS: dict[str, dict[str, float]] = {
        "服务员": {"revenue": 0.30, "efficiency": 0.20, "satisfaction": 0.30, "attendance": 0.15, "teamwork": 0.05},
        "厨师": {"revenue": 0.15, "efficiency": 0.35, "satisfaction": 0.25, "attendance": 0.15, "teamwork": 0.10},
        "收银员": {"revenue": 0.25, "efficiency": 0.25, "satisfaction": 0.20, "attendance": 0.20, "teamwork": 0.10},
        "店长": {"revenue": 0.35, "efficiency": 0.15, "satisfaction": 0.20, "attendance": 0.15, "teamwork": 0.15},
    }

    # 默认权重（未匹配的岗位使用）
    DEFAULT_WEIGHTS: dict[str, float] = {
        "revenue": 0.25,
        "efficiency": 0.25,
        "satisfaction": 0.20,
        "attendance": 0.20,
        "teamwork": 0.10,
    }

    # ── 公开方法 ─────────────────────────────────────────────────────

    async def calculate_score(
        self,
        db: AsyncSession,
        tenant_id: str,
        employee_id: str,
        period_start: date,
        period_end: date,
    ) -> dict[str, Any]:
        """计算单个员工的经营贡献度

        数据来源：
        - 营收：查 orders 表关联 employee_id（服务员=order.waiter_id，收银=order.cashier_id）
        - 效率：查 daily_attendance 的工时 + orders 数量算人效
        - 满意：查 orders 的退菜数/总菜品数
        - 出勤：查 daily_attendance 的出勤记录
        - 团队：查 unified_schedules 的跨岗记录
        """
        await self._set_tenant(db, tenant_id)

        # 获取员工基础信息
        emp = await self._fetch_employee(db, tenant_id, employee_id)
        if emp is None:
            raise ValueError(f"员工不存在: {employee_id}")

        role = emp.get("role", "")
        store_id = emp.get("store_id", "")

        # 并行计算5个维度分
        revenue = await self.calculate_revenue_contribution(
            db,
            tenant_id,
            employee_id,
            store_id,
            period_start,
            period_end,
        )
        efficiency = await self.calculate_efficiency_score(
            db,
            tenant_id,
            employee_id,
            store_id,
            period_start,
            period_end,
        )
        satisfaction = await self.calculate_satisfaction_score(
            db,
            tenant_id,
            employee_id,
            store_id,
            period_start,
            period_end,
        )
        attendance = await self.calculate_attendance_score(
            db,
            tenant_id,
            employee_id,
            period_start,
            period_end,
        )
        teamwork = await self.calculate_teamwork_score(
            db,
            tenant_id,
            employee_id,
            store_id,
            period_start,
            period_end,
        )

        dimensions = {
            "revenue": revenue,
            "efficiency": efficiency,
            "satisfaction": satisfaction,
            "attendance": attendance,
            "teamwork": teamwork,
        }

        # 按岗位权重加权
        weights = self.ROLE_WEIGHTS.get(role, self.DEFAULT_WEIGHTS)
        total_score = sum(dimensions[dim] * weights[dim] for dim in dimensions)
        total_score = round(min(100.0, max(0.0, total_score)), 1)

        log.info(
            "contribution_score_calculated",
            tenant_id=tenant_id,
            employee_id=employee_id,
            total_score=total_score,
        )

        return {
            "employee_id": employee_id,
            "employee_name": emp.get("emp_name", ""),
            "role": role,
            "store_id": store_id,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "total_score": total_score,
            "dimensions": {k: round(v, 1) for k, v in dimensions.items()},
            "weights": weights,
            "grade": self._grade_label(total_score),
            "data_source": "AI实时计算",
        }

    async def calculate_store_rankings(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        period_start: date,
        period_end: date,
    ) -> dict[str, Any]:
        """计算门店全员排名

        返回按贡献度降序排列的员工列表，含趋势对比。
        """
        await self._set_tenant(db, tenant_id)

        # 获取门店全部在职员工
        employees = await self._fetch_store_employees(db, tenant_id, store_id)
        if not employees:
            return {"rankings": [], "stats": {"avg": 0, "max": 0, "min": 0, "spread": 0}}

        rankings: list[dict[str, Any]] = []
        for emp in employees:
            try:
                score_data = await self.calculate_score(
                    db,
                    tenant_id,
                    str(emp["employee_id"]),
                    period_start,
                    period_end,
                )
                # 获取上一周期趋势
                prev_start, prev_end = self._prev_period(period_start, period_end)
                prev_score = await self._get_period_total(
                    db,
                    tenant_id,
                    str(emp["employee_id"]),
                    prev_start,
                    prev_end,
                )
                delta = round(score_data["total_score"] - prev_score, 1) if prev_score > 0 else 0.0
                trend = "up" if delta > 0 else ("down" if delta < 0 else "same")

                rankings.append(
                    {
                        "employee_id": str(emp["employee_id"]),
                        "name": emp.get("emp_name", ""),
                        "role": emp.get("role", ""),
                        "total_score": score_data["total_score"],
                        "dimensions": score_data["dimensions"],
                        "trend": trend,
                        "delta": delta,
                    }
                )
            except (ProgrammingError, DBAPIError, ValueError) as exc:
                log.warning(
                    "contribution_score_skip",
                    employee_id=str(emp["employee_id"]),
                    error=str(exc),
                )
                continue

        # 排序并赋排名
        rankings.sort(key=lambda x: x["total_score"], reverse=True)
        prev_score = None
        rank = 0
        for i, item in enumerate(rankings, start=1):
            if prev_score is None or item["total_score"] != prev_score:
                rank = i
                prev_score = item["total_score"]
            item["rank"] = rank

        # 统计信息
        scores = [r["total_score"] for r in rankings]
        stats = {
            "avg": round(sum(scores) / len(scores), 1) if scores else 0,
            "max": max(scores) if scores else 0,
            "min": min(scores) if scores else 0,
            "spread": round(max(scores) - min(scores), 1) if scores else 0,
            "total_employees": len(rankings),
        }

        return {"rankings": rankings, "stats": stats}

    # ── 维度计算 ─────────────────────────────────────────────────────

    async def calculate_revenue_contribution(
        self,
        db: AsyncSession,
        tenant_id: str,
        employee_id: str,
        store_id: str,
        period_start: date,
        period_end: date,
    ) -> float:
        """营收贡献维度 -- 从POS订单数据计算

        计算：员工关联营收 / 同岗位同店平均营收 * 100，封顶100
        """
        try:
            sql_employee = text("""
                SELECT COALESCE(SUM(total_fen), 0) AS revenue_fen,
                       COUNT(*) AS order_count
                FROM orders
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND store_id = CAST(:store_id AS TEXT)
                  AND (waiter_id = CAST(:eid AS TEXT) OR cashier_id = CAST(:eid AS TEXT))
                  AND created_at BETWEEN :start AND :end
                  AND status = 'paid'
            """)
            row = await db.execute(
                sql_employee,
                {
                    "tid": tenant_id,
                    "store_id": store_id,
                    "eid": employee_id,
                    "start": period_start,
                    "end": period_end,
                },
            )
            emp_result = row.mappings().first()
            emp_revenue = int(emp_result["revenue_fen"] or 0) if emp_result else 0

            if emp_revenue == 0:
                return _BASELINE

            # 同店同岗均值
            sql_avg = text("""
                SELECT COALESCE(AVG(emp_rev), 0) AS avg_revenue_fen
                FROM (
                    SELECT (waiter_id) AS eid,
                           COALESCE(SUM(total_fen), 0) AS emp_rev
                    FROM orders
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND store_id = CAST(:store_id AS TEXT)
                      AND created_at BETWEEN :start AND :end
                      AND status = 'paid'
                    GROUP BY waiter_id
                ) sub
            """)
            avg_row = await db.execute(
                sql_avg,
                {
                    "tid": tenant_id,
                    "store_id": store_id,
                    "start": period_start,
                    "end": period_end,
                },
            )
            avg_result = avg_row.mappings().first()
            avg_revenue = float(avg_result["avg_revenue_fen"] or 1) if avg_result else 1.0

            score = (emp_revenue / max(avg_revenue, 1.0)) * 100.0
            return round(min(100.0, max(0.0, score)), 1)

        except (ProgrammingError, DBAPIError) as exc:
            log.warning(
                "contribution.revenue_unavailable",
                tenant_id=tenant_id,
                employee_id=employee_id,
                error=str(exc),
            )
            return _BASELINE

    async def calculate_efficiency_score(
        self,
        db: AsyncSession,
        tenant_id: str,
        employee_id: str,
        store_id: str,
        period_start: date,
        period_end: date,
    ) -> float:
        """服务效率维度

        服务员：服务桌台数/工时 vs 基准
        厨师：平均出餐时间 vs 标准出餐时间
        """
        try:
            # 人效 = 关联订单数 / 出勤天数
            sql_orders = text("""
                SELECT COUNT(*) AS order_count
                FROM orders
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND store_id = CAST(:store_id AS TEXT)
                  AND (waiter_id = CAST(:eid AS TEXT) OR cashier_id = CAST(:eid AS TEXT))
                  AND created_at BETWEEN :start AND :end
                  AND status = 'paid'
            """)
            o_row = await db.execute(
                sql_orders,
                {
                    "tid": tenant_id,
                    "store_id": store_id,
                    "eid": employee_id,
                    "start": period_start,
                    "end": period_end,
                },
            )
            order_count = int((o_row.mappings().first() or {}).get("order_count", 0))

            sql_attendance = text("""
                SELECT COUNT(*) AS work_days
                FROM daily_attendance
                WHERE tenant_id = CAST(:tid AS TEXT)
                  AND employee_id = CAST(:eid AS TEXT)
                  AND attendance_date BETWEEN :start AND :end
                  AND status IN ('normal', 'late')
            """)
            a_row = await db.execute(
                sql_attendance,
                {
                    "tid": tenant_id,
                    "eid": employee_id,
                    "start": period_start,
                    "end": period_end,
                },
            )
            work_days = int((a_row.mappings().first() or {}).get("work_days", 0))

            if work_days == 0 or order_count == 0:
                return _BASELINE

            # 人效：每天服务订单数
            daily_eff = order_count / work_days
            # 基准：每天10单为满分
            baseline_daily = 10.0
            score = (daily_eff / baseline_daily) * 100.0
            return round(min(100.0, max(0.0, score)), 1)

        except (ProgrammingError, DBAPIError) as exc:
            log.warning(
                "contribution.efficiency_unavailable",
                tenant_id=tenant_id,
                employee_id=employee_id,
                error=str(exc),
            )
            return _BASELINE

    async def calculate_satisfaction_score(
        self,
        db: AsyncSession,
        tenant_id: str,
        employee_id: str,
        store_id: str,
        period_start: date,
        period_end: date,
    ) -> float:
        """客户满意维度

        退菜率（反向）：退菜数/总菜品数 → 退菜率越低分越高
        会员转化：该员工服务桌台办会员卡比例
        """
        try:
            # 退菜率：查订单明细
            sql_refund = text("""
                SELECT
                    COUNT(*) AS total_items,
                    SUM(CASE WHEN oi.status = 'refunded' THEN 1 ELSE 0 END) AS refunded_items
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                WHERE o.tenant_id = CAST(:tid AS uuid)
                  AND o.store_id = CAST(:store_id AS TEXT)
                  AND (o.waiter_id = CAST(:eid AS TEXT) OR o.cashier_id = CAST(:eid AS TEXT))
                  AND o.created_at BETWEEN :start AND :end
            """)
            row = await db.execute(
                sql_refund,
                {
                    "tid": tenant_id,
                    "store_id": store_id,
                    "eid": employee_id,
                    "start": period_start,
                    "end": period_end,
                },
            )
            result = row.mappings().first()
            total_items = int(result["total_items"] or 0) if result else 0
            refunded = int(result["refunded_items"] or 0) if result else 0

            if total_items == 0:
                return _BASELINE

            # 退菜率：0% = 100分，10%以上 = 0分
            refund_rate = refunded / total_items
            refund_score = max(0.0, (1.0 - refund_rate * 10.0)) * 100.0
            return round(min(100.0, max(0.0, refund_score)), 1)

        except (ProgrammingError, DBAPIError) as exc:
            log.warning(
                "contribution.satisfaction_unavailable",
                tenant_id=tenant_id,
                employee_id=employee_id,
                error=str(exc),
            )
            return _BASELINE

    async def calculate_attendance_score(
        self,
        db: AsyncSession,
        tenant_id: str,
        employee_id: str,
        period_start: date,
        period_end: date,
    ) -> float:
        """出勤纪律维度 -- 从考勤数据计算"""
        try:
            sql = text("""
                SELECT
                    COUNT(*) AS total_days,
                    SUM(CASE WHEN status = 'normal' THEN 1 ELSE 0 END) AS normal_days,
                    SUM(CASE WHEN status = 'late' THEN 1 ELSE 0 END) AS late_days,
                    SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) AS absent_days
                FROM daily_attendance
                WHERE tenant_id = CAST(:tid AS TEXT)
                  AND employee_id = CAST(:eid AS TEXT)
                  AND attendance_date BETWEEN :start AND :end
            """)
            row = await db.execute(
                sql,
                {
                    "tid": tenant_id,
                    "eid": employee_id,
                    "start": period_start,
                    "end": period_end,
                },
            )
            result = row.mappings().first()
            total = int(result["total_days"] or 0) if result else 0

            if total == 0:
                return _BASELINE

            normal = int(result["normal_days"] or 0)
            late = int(result["late_days"] or 0)
            absent = int(result["absent_days"] or 0)

            # 出勤率基础分 + 迟到/缺勤扣分
            base = (normal / total) * 100.0
            penalty = late * 3.0 + absent * 15.0
            score = base - penalty
            return round(min(100.0, max(0.0, score)), 1)

        except (ProgrammingError, DBAPIError) as exc:
            log.warning(
                "contribution.attendance_unavailable",
                tenant_id=tenant_id,
                employee_id=employee_id,
                error=str(exc),
            )
            return _BASELINE

    async def calculate_teamwork_score(
        self,
        db: AsyncSession,
        tenant_id: str,
        employee_id: str,
        store_id: str,
        period_start: date,
        period_end: date,
    ) -> float:
        """团队协作维度 -- 跨岗支援次数/帮带新人"""
        try:
            # 查跨岗支援：unified_schedules中非本岗位排班
            sql = text("""
                SELECT COUNT(*) AS cross_support_count
                FROM unified_schedules us
                WHERE us.tenant_id = CAST(:tid AS uuid)
                  AND us.employee_id = CAST(:eid AS uuid)
                  AND us.store_id = CAST(:store_id AS uuid)
                  AND us.schedule_date BETWEEN :start AND :end
                  AND us.is_cross_position = TRUE
                  AND us.is_deleted = FALSE
            """)
            row = await db.execute(
                sql,
                {
                    "tid": tenant_id,
                    "eid": employee_id,
                    "store_id": store_id,
                    "start": period_start,
                    "end": period_end,
                },
            )
            result = row.mappings().first()
            cross_count = int(result["cross_support_count"] or 0) if result else 0

            # 每次跨岗支援 +10分，基础50分，上限100
            score = _BASELINE + cross_count * 10.0
            return round(min(100.0, max(0.0, score)), 1)

        except (ProgrammingError, DBAPIError) as exc:
            log.warning(
                "contribution.teamwork_unavailable",
                tenant_id=tenant_id,
                employee_id=employee_id,
                error=str(exc),
            )
            return _BASELINE

    async def get_employee_trend(
        self,
        db: AsyncSession,
        tenant_id: str,
        employee_id: str,
        periods: int = 6,
    ) -> list[dict[str, Any]]:
        """获取员工贡献度趋势（最近N个周期，按周）"""
        await self._set_tenant(db, tenant_id)
        today = date.today()
        trend: list[dict[str, Any]] = []

        for i in range(periods - 1, -1, -1):
            p_end = today - timedelta(weeks=i)
            p_start = p_end - timedelta(days=6)
            try:
                score_data = await self.calculate_score(
                    db,
                    tenant_id,
                    employee_id,
                    p_start,
                    p_end,
                )
                trend.append(
                    {
                        "period_start": p_start.isoformat(),
                        "period_end": p_end.isoformat(),
                        "total_score": score_data["total_score"],
                        "dimensions": score_data["dimensions"],
                    }
                )
            except (ProgrammingError, DBAPIError, ValueError):
                trend.append(
                    {
                        "period_start": p_start.isoformat(),
                        "period_end": p_end.isoformat(),
                        "total_score": 0,
                        "dimensions": {},
                    }
                )

        return trend

    # ── 内部辅助 ─────────────────────────────────────────────────────

    @staticmethod
    async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    async def _fetch_employee(
        self,
        db: AsyncSession,
        tenant_id: str,
        employee_id: str,
    ) -> Optional[dict[str, Any]]:
        row = await db.execute(
            text("""
                SELECT id::text AS employee_id, emp_name, role, store_id::text AS store_id
                FROM employees
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND id = CAST(:eid AS uuid)
                  AND is_deleted = FALSE
            """),
            {"tid": tenant_id, "eid": employee_id},
        )
        m = row.mappings().first()
        return dict(m) if m else None

    async def _fetch_store_employees(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
    ) -> list[dict[str, Any]]:
        rows = await db.execute(
            text("""
                SELECT id::text AS employee_id, emp_name, role
                FROM employees
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND store_id = CAST(:store_id AS uuid)
                  AND is_deleted = FALSE
                  AND COALESCE(is_active, true) = true
                ORDER BY emp_name
            """),
            {"tid": tenant_id, "store_id": store_id},
        )
        return [dict(r) for r in rows.mappings().fetchall()]

    async def _get_period_total(
        self,
        db: AsyncSession,
        tenant_id: str,
        employee_id: str,
        period_start: date,
        period_end: date,
    ) -> float:
        """获取某个周期的总分（用于趋势对比），简化版只算营收+出勤"""
        try:
            score_data = await self.calculate_score(
                db,
                tenant_id,
                employee_id,
                period_start,
                period_end,
            )
            return score_data["total_score"]
        except (ProgrammingError, DBAPIError, ValueError):
            return 0.0

    @staticmethod
    def _prev_period(start: date, end: date) -> tuple[date, date]:
        """计算上一个同长度周期"""
        delta = end - start
        return start - delta - timedelta(days=1), start - timedelta(days=1)

    @staticmethod
    def _grade_label(score: float) -> str:
        if score >= 90:
            return "卓越"
        if score >= 80:
            return "优秀"
        if score >= 60:
            return "良好"
        if score >= 40:
            return "合格"
        return "待提升"
