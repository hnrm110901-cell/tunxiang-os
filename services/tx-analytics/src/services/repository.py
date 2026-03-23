"""经营分析 Repository — 真实 DB 查询层

封装门店健康度、日报、KPI 预警、决策推荐的聚合查询。
"""
import uuid
from datetime import datetime, timezone, timedelta, date
from typing import Optional

from sqlalchemy import select, func, text, case, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem, Store, Ingredient, Employee
from shared.ontology.src.enums import OrderStatus, InventoryStatus


class AnalyticsRepository:
    """经营分析 Repository — 封装真实 DB 聚合查询"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self._tenant_uuid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ─── 门店健康度 ───

    async def get_store_health(self, store_id: str, date: Optional[str] = None) -> dict:
        """门店健康度评分 — 5 维度加权

        维度：营收达成率 / 翻台率 / 成本率 / 客诉率 / 人效
        """
        await self._set_tenant()

        store_uuid = uuid.UUID(store_id)
        target_date = self._parse_date(date)
        day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        # 获取门店目标
        store_result = await self.db.execute(
            select(Store)
            .where(Store.id == store_uuid)
            .where(Store.tenant_id == self._tenant_uuid)
        )
        store = store_result.scalar_one_or_none()
        if not store:
            raise ValueError(f"Store not found: {store_id}")

        # 当日营收
        revenue_result = await self.db.execute(
            select(
                func.coalesce(func.sum(Order.final_amount_fen), 0).label("revenue_fen"),
                func.count(Order.id).label("order_count"),
                func.coalesce(func.sum(Order.guest_count), 0).label("guest_count"),
            )
            .where(Order.tenant_id == self._tenant_uuid)
            .where(Order.store_id == store_uuid)
            .where(Order.status == OrderStatus.completed.value)
            .where(Order.order_time >= day_start)
            .where(Order.order_time < day_end)
        )
        rev_row = revenue_result.one()
        revenue_fen = rev_row[0]
        order_count = rev_row[1]
        guest_count = rev_row[2]

        # 异常订单数（客诉）
        complaint_result = await self.db.execute(
            select(func.count(Order.id))
            .where(Order.tenant_id == self._tenant_uuid)
            .where(Order.store_id == store_uuid)
            .where(Order.abnormal_flag == True)  # noqa: E712
            .where(Order.order_time >= day_start)
            .where(Order.order_time < day_end)
        )
        complaint_count = complaint_result.scalar() or 0

        # 在岗员工数
        emp_result = await self.db.execute(
            select(func.count(Employee.id))
            .where(Employee.tenant_id == self._tenant_uuid)
            .where(Employee.store_id == store_uuid)
            .where(Employee.is_active == True)  # noqa: E712
        )
        emp_count = emp_result.scalar() or 1

        # 计算各维度分数 (0-100)
        daily_target = (store.monthly_revenue_target_fen or 0) / 30
        revenue_score = min(100, int((revenue_fen / daily_target * 100))) if daily_target > 0 else 50

        seats = store.seats or 100
        turnover_rate = order_count / seats if seats > 0 else 0
        turnover_target = store.turnover_rate_target or 2.0
        turnover_score = min(100, int(turnover_rate / turnover_target * 100)) if turnover_target > 0 else 50

        complaint_rate = complaint_count / order_count if order_count > 0 else 0
        complaint_score = max(0, 100 - int(complaint_rate * 1000))

        labor_efficiency = revenue_fen / emp_count if emp_count > 0 else 0
        labor_score = min(100, int(labor_efficiency / 500_00)) if labor_efficiency > 0 else 50  # 500 元/人为基准

        # 加权综合分
        weights = {"revenue": 0.30, "turnover": 0.20, "cost": 0.20, "complaint": 0.15, "labor": 0.15}
        cost_score = 70  # 成本率需要 BOM 计算，此处给默认值

        overall = int(
            revenue_score * weights["revenue"]
            + turnover_score * weights["turnover"]
            + cost_score * weights["cost"]
            + complaint_score * weights["complaint"]
            + labor_score * weights["labor"]
        )

        return {
            "store_id": store_id,
            "date": target_date.isoformat(),
            "overall_score": overall,
            "dimensions": {
                "revenue": {"score": revenue_score, "value_fen": revenue_fen, "target_fen": int(daily_target)},
                "turnover": {"score": turnover_score, "rate": round(turnover_rate, 2), "target": turnover_target},
                "cost": {"score": cost_score},
                "complaint": {"score": complaint_score, "count": complaint_count, "rate": round(complaint_rate, 4)},
                "labor": {"score": labor_score, "efficiency_fen": int(labor_efficiency), "emp_count": emp_count},
            },
            "order_count": order_count,
            "guest_count": guest_count,
        }

    # ─── 日报 ───

    async def get_daily_report(self, store_id: str, date: str) -> dict:
        """门店经营日报"""
        await self._set_tenant()

        store_uuid = uuid.UUID(store_id)
        target_date = self._parse_date(date)
        day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        # 营收与订单统计
        result = await self.db.execute(
            select(
                func.coalesce(func.sum(Order.final_amount_fen), 0).label("revenue_fen"),
                func.coalesce(func.sum(Order.discount_amount_fen), 0).label("discount_fen"),
                func.count(Order.id).label("order_count"),
                func.coalesce(func.sum(Order.guest_count), 0).label("guest_count"),
                func.coalesce(func.avg(Order.final_amount_fen), 0).label("avg_ticket_fen"),
            )
            .where(Order.tenant_id == self._tenant_uuid)
            .where(Order.store_id == store_uuid)
            .where(Order.status == OrderStatus.completed.value)
            .where(Order.order_time >= day_start)
            .where(Order.order_time < day_end)
        )
        row = result.one()

        # 渠道分布
        channel_result = await self.db.execute(
            select(
                Order.sales_channel,
                func.count(Order.id).label("count"),
                func.coalesce(func.sum(Order.final_amount_fen), 0).label("revenue_fen"),
            )
            .where(Order.tenant_id == self._tenant_uuid)
            .where(Order.store_id == store_uuid)
            .where(Order.status == OrderStatus.completed.value)
            .where(Order.order_time >= day_start)
            .where(Order.order_time < day_end)
            .group_by(Order.sales_channel)
        )
        channels = {
            r[0] or "unknown": {"count": r[1], "revenue_fen": r[2]}
            for r in channel_result.all()
        }

        # 取消订单数
        cancel_result = await self.db.execute(
            select(func.count(Order.id))
            .where(Order.tenant_id == self._tenant_uuid)
            .where(Order.store_id == store_uuid)
            .where(Order.status == OrderStatus.cancelled.value)
            .where(Order.order_time >= day_start)
            .where(Order.order_time < day_end)
        )
        cancel_count = cancel_result.scalar() or 0

        return {
            "store_id": store_id,
            "date": target_date.isoformat(),
            "revenue_fen": row[0],
            "discount_fen": row[1],
            "order_count": row[2],
            "guest_count": row[3],
            "avg_ticket_fen": int(row[4]),
            "cancel_count": cancel_count,
            "channels": channels,
        }

    # ─── KPI 预警 ───

    async def get_kpi_alerts(self, store_id: str) -> list:
        """获取 KPI 预警列表"""
        await self._set_tenant()

        store_uuid = uuid.UUID(store_id)

        # 获取门店目标
        store_result = await self.db.execute(
            select(Store)
            .where(Store.id == store_uuid)
            .where(Store.tenant_id == self._tenant_uuid)
        )
        store = store_result.scalar_one_or_none()
        if not store:
            return []

        alerts = []

        # 检查当月营收 vs 目标
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        rev_result = await self.db.execute(
            select(func.coalesce(func.sum(Order.final_amount_fen), 0))
            .where(Order.tenant_id == self._tenant_uuid)
            .where(Order.store_id == store_uuid)
            .where(Order.status == OrderStatus.completed.value)
            .where(Order.order_time >= month_start)
        )
        month_revenue = rev_result.scalar() or 0

        target = store.monthly_revenue_target_fen or 0
        if target > 0:
            progress = now.day / 30  # 月度进度
            expected = int(target * progress)
            if month_revenue < expected * 0.8:
                alerts.append({
                    "type": "revenue_behind",
                    "severity": "high",
                    "message": f"月营收进度落后: 已完成 {month_revenue} 分, 期望 {expected} 分",
                    "current": month_revenue,
                    "expected": expected,
                    "target": target,
                })

        # 检查库存预警数量
        inv_alert_result = await self.db.execute(
            select(func.count(Ingredient.id))
            .where(Ingredient.tenant_id == self._tenant_uuid)
            .where(Ingredient.store_id == store_uuid)
            .where(Ingredient.is_deleted == False)  # noqa: E712
            .where(Ingredient.status.in_([
                InventoryStatus.critical.value,
                InventoryStatus.out_of_stock.value,
            ]))
        )
        inv_alert_count = inv_alert_result.scalar() or 0
        if inv_alert_count > 0:
            alerts.append({
                "type": "inventory_critical",
                "severity": "high" if inv_alert_count >= 3 else "medium",
                "message": f"{inv_alert_count} 种食材库存告急",
                "count": inv_alert_count,
            })

        return alerts

    # ─── Top3 决策推荐 ───

    async def get_top3_decisions(self, store_id: str) -> list:
        """Top3 AI 决策推荐（基于数据分析）"""
        await self._set_tenant()

        store_uuid = uuid.UUID(store_id)
        decisions = []

        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)

        # 分析1：滞销菜品
        slow_result = await self.db.execute(
            select(
                OrderItem.item_name,
                func.count(OrderItem.id).label("cnt"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.tenant_id == self._tenant_uuid)
            .where(Order.store_id == store_uuid)
            .where(Order.status == OrderStatus.completed.value)
            .where(Order.order_time >= week_ago)
            .group_by(OrderItem.item_name)
            .order_by(func.count(OrderItem.id).asc())
            .limit(3)
        )
        slow_items = slow_result.all()
        if slow_items:
            names = ", ".join(r[0] for r in slow_items)
            decisions.append({
                "type": "menu_optimization",
                "title": "建议优化滞销菜品",
                "description": f"近 7 天销量最低: {names}，建议调整价格或替换",
                "impact_fen": 0,
                "confidence": 0.75,
            })

        # 分析2：高折扣订单占比
        discount_result = await self.db.execute(
            select(
                func.count(Order.id).label("total"),
                func.count(case((Order.discount_amount_fen > 0, 1))).label("discounted"),
            )
            .where(Order.tenant_id == self._tenant_uuid)
            .where(Order.store_id == store_uuid)
            .where(Order.status == OrderStatus.completed.value)
            .where(Order.order_time >= week_ago)
        )
        d_row = discount_result.one()
        total_orders = d_row[0] or 1
        discounted = d_row[1] or 0
        discount_rate = discounted / total_orders
        if discount_rate > 0.3:
            decisions.append({
                "type": "discount_control",
                "title": "折扣比例偏高",
                "description": f"近7天折扣订单占比 {discount_rate:.0%}，建议加强折扣审批",
                "impact_fen": 0,
                "confidence": 0.80,
            })

        # 分析3：库存风险
        inv_result = await self.db.execute(
            select(func.count(Ingredient.id))
            .where(Ingredient.tenant_id == self._tenant_uuid)
            .where(Ingredient.store_id == store_uuid)
            .where(Ingredient.is_deleted == False)  # noqa: E712
            .where(Ingredient.status.in_([
                InventoryStatus.low.value,
                InventoryStatus.critical.value,
            ]))
        )
        low_count = inv_result.scalar() or 0
        if low_count > 0:
            decisions.append({
                "type": "procurement",
                "title": "建议补货",
                "description": f"{low_count} 种食材库存偏低，建议尽快采购补货",
                "impact_fen": 0,
                "confidence": 0.90,
            })

        return decisions[:3]

    # ─── 内部工具 ───

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> date:
        if not date_str or date_str == "today":
            return date.today()
        return date.fromisoformat(date_str)
