"""预算管理服务 — 预算编制 / 执行跟踪 / 现金流预测

所有金额单位：分（fen）。
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Optional

import structlog
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models.budget import Budget, BudgetExecution

logger = structlog.get_logger()

# ── 合法枚举值 ──────────────────────────────────────────────────

VALID_PERIODS = {"monthly", "quarterly", "yearly"}
VALID_CATEGORIES = {"revenue", "cost", "labor", "material", "marketing", "overhead"}
VALID_STATUSES = {"draft", "approved", "active", "closed"}
VALID_SOURCE_TYPES = {"order", "purchase", "payroll", "expense"}


class BudgetService:
    """预算管理核心服务"""

    # ── 创建预算 ────────────────────────────────────────────────

    async def create_budget(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        department: str,
        period: str,
        period_start: date,
        period_end: date,
        category: str,
        budget_amount_fen: int,
        note: Optional[str] = None,
    ) -> Budget:
        """创建一条预算记录（status=draft）"""
        if period not in VALID_PERIODS:
            raise ValueError(f"Invalid period: {period}. Must be one of {VALID_PERIODS}")
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category: {category}. Must be one of {VALID_CATEGORIES}")
        if period_end <= period_start:
            raise ValueError("period_end must be after period_start")
        if budget_amount_fen < 0:
            raise ValueError("budget_amount_fen must be non-negative")

        budget = Budget(
            tenant_id=tenant_id,
            store_id=store_id,
            department=department,
            period=period,
            period_start=period_start,
            period_end=period_end,
            category=category,
            budget_amount_fen=budget_amount_fen,
            status="draft",
            note=note,
        )
        db.add(budget)
        await db.flush()

        logger.info(
            "budget_created",
            budget_id=str(budget.id),
            store_id=str(store_id),
            category=category,
            amount_fen=budget_amount_fen,
        )
        return budget

    # ── 查询预算列表 ────────────────────────────────────────────

    async def list_budgets(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        store_id: Optional[uuid.UUID] = None,
        department: Optional[str] = None,
        period: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """按条件查询预算列表，支持分页"""
        conditions = [
            Budget.tenant_id == tenant_id,
            Budget.is_deleted.is_(False),
        ]
        if store_id is not None:
            conditions.append(Budget.store_id == store_id)
        if department is not None:
            conditions.append(Budget.department == department)
        if period is not None:
            conditions.append(Budget.period == period)
        if category is not None:
            conditions.append(Budget.category == category)
        if status is not None:
            conditions.append(Budget.status == status)

        where_clause = and_(*conditions)

        # 总数
        count_result = await db.execute(
            select(func.count(Budget.id)).where(where_clause)
        )
        total = count_result.scalar_one()

        # 分页查询
        offset = (page - 1) * size
        result = await db.execute(
            select(Budget)
            .where(where_clause)
            .order_by(Budget.period_start.desc(), Budget.created_at.desc())
            .offset(offset)
            .limit(size)
        )
        items = list(result.scalars().all())

        return {"items": items, "total": total, "page": page, "size": size}

    # ── 审批预算 ────────────────────────────────────────────────

    async def approve_budget(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        budget_id: uuid.UUID,
    ) -> Budget:
        """审批预算：draft → approved"""
        result = await db.execute(
            select(Budget).where(
                Budget.id == budget_id,
                Budget.tenant_id == tenant_id,
                Budget.is_deleted.is_(False),
            )
        )
        budget = result.scalar_one_or_none()
        if budget is None:
            raise LookupError(f"Budget {budget_id} not found")
        if budget.status != "draft":
            raise ValueError(f"Cannot approve budget in status '{budget.status}', must be 'draft'")

        budget.status = "approved"
        await db.flush()

        logger.info("budget_approved", budget_id=str(budget_id))
        return budget

    # ── 记录执行 ────────────────────────────────────────────────

    async def record_execution(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        budget_id: uuid.UUID,
        actual_amount_fen: int,
        recorded_date: date,
        source_type: str,
        description: Optional[str] = None,
    ) -> BudgetExecution:
        """记录一笔实际发生金额，自动计算偏差"""
        if source_type not in VALID_SOURCE_TYPES:
            raise ValueError(f"Invalid source_type: {source_type}. Must be one of {VALID_SOURCE_TYPES}")

        # 查找预算
        result = await db.execute(
            select(Budget).where(
                Budget.id == budget_id,
                Budget.tenant_id == tenant_id,
                Budget.is_deleted.is_(False),
            )
        )
        budget = result.scalar_one_or_none()
        if budget is None:
            raise LookupError(f"Budget {budget_id} not found")
        if budget.status not in ("approved", "active"):
            raise ValueError(f"Cannot record execution for budget in status '{budget.status}'")

        # 如果预算还是 approved，自动激活为 active
        if budget.status == "approved":
            budget.status = "active"

        # 计算累计实际金额
        cumulative_result = await db.execute(
            select(func.coalesce(func.sum(BudgetExecution.actual_amount_fen), 0))
            .where(
                BudgetExecution.budget_id == budget_id,
                BudgetExecution.tenant_id == tenant_id,
                BudgetExecution.is_deleted.is_(False),
            )
        )
        cumulative_fen = int(cumulative_result.scalar_one()) + actual_amount_fen

        # 偏差计算
        variance_fen = cumulative_fen - budget.budget_amount_fen
        variance_pct = (
            round(variance_fen / budget.budget_amount_fen, 4)
            if budget.budget_amount_fen != 0
            else 0.0
        )

        execution = BudgetExecution(
            tenant_id=tenant_id,
            budget_id=budget_id,
            actual_amount_fen=actual_amount_fen,
            variance_fen=variance_fen,
            variance_pct=variance_pct,
            recorded_date=recorded_date,
            source_type=source_type,
            description=description,
        )
        db.add(execution)
        await db.flush()

        logger.info(
            "budget_execution_recorded",
            budget_id=str(budget_id),
            actual_fen=actual_amount_fen,
            cumulative_fen=cumulative_fen,
            variance_pct=variance_pct,
        )
        return execution

    # ── 获取预算执行情况 ────────────────────────────────────────

    async def get_budget_execution(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        category: Optional[str] = None,
    ) -> list[dict]:
        """获取门店各预算的执行概览（预算 vs 实际，偏差率）"""
        conditions = [
            Budget.tenant_id == tenant_id,
            Budget.store_id == store_id,
            Budget.is_deleted.is_(False),
            Budget.status.in_(["approved", "active"]),
        ]
        if category is not None:
            conditions.append(Budget.category == category)

        result = await db.execute(
            select(Budget).where(and_(*conditions)).order_by(Budget.period_start.desc())
        )
        budgets = result.scalars().all()

        execution_summaries: list[dict] = []
        for b in budgets:
            actual_result = await db.execute(
                select(func.coalesce(func.sum(BudgetExecution.actual_amount_fen), 0))
                .where(
                    BudgetExecution.budget_id == b.id,
                    BudgetExecution.tenant_id == tenant_id,
                    BudgetExecution.is_deleted.is_(False),
                )
            )
            actual_fen = int(actual_result.scalar_one())
            variance_fen = actual_fen - b.budget_amount_fen
            variance_pct = (
                round(variance_fen / b.budget_amount_fen, 4)
                if b.budget_amount_fen != 0
                else 0.0
            )
            utilization_pct = (
                round(actual_fen / b.budget_amount_fen, 4)
                if b.budget_amount_fen != 0
                else 0.0
            )

            execution_summaries.append({
                "budget_id": str(b.id),
                "store_id": str(b.store_id),
                "department": b.department,
                "category": b.category,
                "period": b.period,
                "period_start": str(b.period_start),
                "period_end": str(b.period_end),
                "budget_amount_fen": b.budget_amount_fen,
                "actual_amount_fen": actual_fen,
                "variance_fen": variance_fen,
                "variance_pct": variance_pct,
                "utilization_pct": utilization_pct,
                "status": b.status,
            })

        return execution_summaries

    # ── 现金流预测 ──────────────────────────────────────────────

    async def get_cashflow_forecast(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        days: int = 30,
    ) -> list[dict]:
        """基于预算 + 历史执行趋势生成未来 N 天现金流预测

        算法：
        1. 取当前 active 预算，按日均分配预算金额
        2. 根据最近30天的执行记录计算日均实际发生
        3. 用加权平均（预算40% + 历史趋势60%）生成预测
        """
        today = date.today()
        forecast_start = today + timedelta(days=1)
        forecast_end = today + timedelta(days=days)

        # 1) 取 active 预算的日均计划
        active_budgets_result = await db.execute(
            select(Budget).where(
                Budget.tenant_id == tenant_id,
                Budget.store_id == store_id,
                Budget.status.in_(["approved", "active"]),
                Budget.is_deleted.is_(False),
                Budget.period_end >= today,
            )
        )
        active_budgets = active_budgets_result.scalars().all()

        # 按类别汇总日均预算
        daily_budget_by_category: dict[str, float] = {}
        for b in active_budgets:
            period_days = (b.period_end - b.period_start).days or 1
            daily_avg = b.budget_amount_fen / period_days
            daily_budget_by_category[b.category] = (
                daily_budget_by_category.get(b.category, 0.0) + daily_avg
            )

        # 2) 取近30天历史执行日均
        history_start = today - timedelta(days=30)
        history_result = await db.execute(
            select(
                BudgetExecution.source_type,
                func.coalesce(func.sum(BudgetExecution.actual_amount_fen), 0).label("total"),
            )
            .join(Budget, BudgetExecution.budget_id == Budget.id)
            .where(
                BudgetExecution.tenant_id == tenant_id,
                Budget.store_id == store_id,
                BudgetExecution.recorded_date >= history_start,
                BudgetExecution.recorded_date <= today,
                BudgetExecution.is_deleted.is_(False),
            )
            .group_by(BudgetExecution.source_type)
        )
        daily_history_by_source: dict[str, float] = {}
        for row in history_result.all():
            daily_history_by_source[row.source_type] = int(row.total) / 30.0

        # 3) 生成每日预测
        total_daily_budget = sum(daily_budget_by_category.values())
        total_daily_history = sum(daily_history_by_source.values())

        # 加权平均：预算 40% + 历史 60%
        if total_daily_budget > 0 and total_daily_history > 0:
            daily_forecast = total_daily_budget * 0.4 + total_daily_history * 0.6
        elif total_daily_budget > 0:
            daily_forecast = total_daily_budget
        elif total_daily_history > 0:
            daily_forecast = total_daily_history
        else:
            daily_forecast = 0.0

        forecast_items: list[dict] = []
        cumulative_fen = 0
        current = forecast_start
        while current <= forecast_end:
            day_amount = round(daily_forecast)
            cumulative_fen += day_amount
            forecast_items.append({
                "date": str(current),
                "predicted_outflow_fen": day_amount,
                "cumulative_outflow_fen": cumulative_fen,
                "budget_by_category": {
                    k: round(v) for k, v in daily_budget_by_category.items()
                },
            })
            current += timedelta(days=1)

        logger.info(
            "cashflow_forecast_generated",
            store_id=str(store_id),
            days=days,
            daily_forecast_fen=round(daily_forecast),
        )
        return forecast_items
