"""预算管理服务 — 预算编制 / 执行跟踪 / 现金流预测

所有金额单位：分（fen）。

预算管理服务 v1 — 门店预算编制 + 执行跟踪（v101）

功能：
  - 创建/审批/更新预算计划（budget_plans）
  - 录入实际执行金额（budget_executions 追加写入）
  - 查询预算执行进度（计划 vs 实际 vs 差异）
  - 多门店/多科目预算汇总
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Optional

import structlog
from models.budget import Budget, BudgetExecution
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
        count_result = await db.execute(select(func.count(Budget.id)).where(where_clause))
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
            select(func.coalesce(func.sum(BudgetExecution.actual_amount_fen), 0)).where(
                BudgetExecution.budget_id == budget_id,
                BudgetExecution.tenant_id == tenant_id,
                BudgetExecution.is_deleted.is_(False),
            )
        )
        cumulative_fen = int(cumulative_result.scalar_one()) + actual_amount_fen

        # 偏差计算
        variance_fen = cumulative_fen - budget.budget_amount_fen
        variance_pct = round(variance_fen / budget.budget_amount_fen, 4) if budget.budget_amount_fen != 0 else 0.0

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

        result = await db.execute(select(Budget).where(and_(*conditions)).order_by(Budget.period_start.desc()))
        budgets = result.scalars().all()

        execution_summaries: list[dict] = []
        for b in budgets:
            actual_result = await db.execute(
                select(func.coalesce(func.sum(BudgetExecution.actual_amount_fen), 0)).where(
                    BudgetExecution.budget_id == b.id,
                    BudgetExecution.tenant_id == tenant_id,
                    BudgetExecution.is_deleted.is_(False),
                )
            )
            actual_fen = int(actual_result.scalar_one())
            variance_fen = actual_fen - b.budget_amount_fen
            variance_pct = round(variance_fen / b.budget_amount_fen, 4) if b.budget_amount_fen != 0 else 0.0
            utilization_pct = round(actual_fen / b.budget_amount_fen, 4) if b.budget_amount_fen != 0 else 0.0

            execution_summaries.append(
                {
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
                }
            )

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
            daily_budget_by_category[b.category] = daily_budget_by_category.get(b.category, 0.0) + daily_avg

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
            forecast_items.append(
                {
                    "date": str(current),
                    "predicted_outflow_fen": day_amount,
                    "cumulative_outflow_fen": cumulative_fen,
                    "budget_by_category": {k: round(v) for k, v in daily_budget_by_category.items()},
                }
            )
            current += timedelta(days=1)

        logger.info(
            "cashflow_forecast_generated",
            store_id=str(store_id),
            days=days,
            daily_forecast_fen=round(daily_forecast),
        )
        return forecast_items


from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

VALID_CATEGORIES = (
    "revenue",
    "ingredient_cost",
    "labor_cost",
    "fixed_cost",
    "marketing_cost",
    "total",
)
VALID_PERIOD_TYPES = ("monthly", "quarterly", "yearly")
VALID_STATUSES = ("draft", "approved", "locked")


class BudgetService:
    """预算管理数据访问层 + 业务逻辑"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._tid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ══════════════════════════════════════════════════════
    # 预算计划 CRUD
    # ══════════════════════════════════════════════════════

    async def upsert_plan(
        self,
        store_id: str,
        period_type: str,
        period: str,
        category: str,
        budget_fen: int,
        note: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建或更新预算计划（同门店+期间+科目 UPSERT）"""
        await self._set_tenant()
        if period_type not in VALID_PERIOD_TYPES:
            raise ValueError(f"period_type 必须是: {', '.join(VALID_PERIOD_TYPES)}")
        if category not in VALID_CATEGORIES:
            raise ValueError(f"category 必须是: {', '.join(VALID_CATEGORIES)}")

        sid = uuid.UUID(store_id)
        cb = uuid.UUID(created_by) if created_by else None

        result = await self.db.execute(
            text("""
                INSERT INTO budget_plans
                    (tenant_id, store_id, period_type, period, category,
                     budget_fen, note, created_by, status)
                VALUES
                    (:tid, :sid, :ptype, :period, :cat,
                     :fen, :note, :cb, 'draft')
                ON CONFLICT (tenant_id, store_id, period_type, period, category)
                DO UPDATE SET
                    budget_fen = EXCLUDED.budget_fen,
                    note       = COALESCE(EXCLUDED.note, budget_plans.note),
                    updated_at = NOW()
                RETURNING id, store_id, period_type, period, category,
                          budget_fen, note, status, created_at, updated_at
            """),
            {
                "tid": self._tid,
                "sid": sid,
                "ptype": period_type,
                "period": period,
                "cat": category,
                "fen": budget_fen,
                "note": note,
                "cb": cb,
            },
        )
        row = result.fetchone()
        await self.db.flush()
        log.info(
            "budget_plan_upserted",
            store_id=store_id,
            period=period,
            category=category,
            budget_fen=budget_fen,
            tenant_id=self.tenant_id,
        )
        return self._plan_row(row)

    async def get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """查询单个预算计划"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, store_id, period_type, period, category,
                       budget_fen, note, created_by, approved_by, approved_at,
                       status, created_at, updated_at
                FROM budget_plans
                WHERE id = :id AND tenant_id = :tid
            """),
            {"id": uuid.UUID(plan_id), "tid": self._tid},
        )
        row = result.fetchone()
        return self._plan_row(row) if row else None

    async def list_plans(
        self,
        store_id: Optional[str] = None,
        period_type: Optional[str] = None,
        period: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """查询预算计划列表"""
        await self._set_tenant()
        sql = """
            SELECT id, store_id, period_type, period, category,
                   budget_fen, note, created_by, approved_by, approved_at,
                   status, created_at, updated_at
            FROM budget_plans
            WHERE tenant_id = :tid
        """
        params: Dict[str, Any] = {"tid": self._tid}
        if store_id:
            sql += " AND store_id = :sid"
            params["sid"] = uuid.UUID(store_id)
        if period_type:
            sql += " AND period_type = :ptype"
            params["ptype"] = period_type
        if period:
            sql += " AND period = :period"
            params["period"] = period
        if category:
            sql += " AND category = :cat"
            params["cat"] = category
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY period DESC, store_id, category"

        result = await self.db.execute(text(sql), params)
        return [self._plan_row(r) for r in result.fetchall()]

    async def approve_plan(self, plan_id: str, approved_by: str) -> Dict[str, Any]:
        """审批预算计划 draft → approved"""
        await self._set_tenant()
        plan = await self.get_plan(plan_id)
        if not plan:
            raise ValueError(f"预算计划 {plan_id} 不存在")
        if plan["status"] != "draft":
            raise ValueError(f"只有 draft 状态可审批，当前状态: {plan['status']}")

        now = datetime.now(timezone.utc)
        await self.db.execute(
            text("""
                UPDATE budget_plans
                SET status = 'approved', approved_by = :approver,
                    approved_at = :now, updated_at = :now
                WHERE id = :id AND tenant_id = :tid
            """),
            {
                "approver": uuid.UUID(approved_by),
                "now": now,
                "id": uuid.UUID(plan_id),
                "tid": self._tid,
            },
        )
        await self.db.flush()
        log.info("budget_plan_approved", plan_id=plan_id, approved_by=approved_by, tenant_id=self.tenant_id)
        return await self.get_plan(plan_id)  # type: ignore[return-value]

    # ══════════════════════════════════════════════════════
    # 预算执行
    # ══════════════════════════════════════════════════════

    async def record_execution(
        self,
        plan_id: str,
        actual_fen: int,
        tracked_at: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """录入实际执行金额（追加写入，不覆盖历史）"""
        await self._set_tenant()
        plan = await self.get_plan(plan_id)
        if not plan:
            raise ValueError(f"预算计划 {plan_id} 不存在")

        budget_fen = plan["budget_fen"]
        variance_fen = actual_fen - budget_fen
        variance_pct = round(variance_fen / budget_fen * 100, 4) if budget_fen != 0 else None
        t_date = date.fromisoformat(tracked_at) if tracked_at else date.today()

        exec_id = uuid.uuid4()
        await self.db.execute(
            text("""
                INSERT INTO budget_executions
                    (id, tenant_id, budget_plan_id, actual_fen,
                     variance_fen, variance_pct, tracked_at, note)
                VALUES
                    (:id, :tid, :pid, :actual,
                     :var_fen, :var_pct, :tracked, :note)
            """),
            {
                "id": exec_id,
                "tid": self._tid,
                "pid": uuid.UUID(plan_id),
                "actual": actual_fen,
                "var_fen": variance_fen,
                "var_pct": variance_pct,
                "tracked": t_date,
                "note": note,
            },
        )
        await self.db.flush()
        log.info(
            "budget_execution_recorded",
            plan_id=plan_id,
            actual_fen=actual_fen,
            variance_fen=variance_fen,
            tenant_id=self.tenant_id,
        )

        return {
            "execution_id": str(exec_id),
            "plan_id": plan_id,
            "budget_fen": budget_fen,
            "actual_fen": actual_fen,
            "variance_fen": variance_fen,
            "variance_pct": variance_pct,
            "status": "over_budget" if variance_fen > 0 else "under_budget" if variance_fen < 0 else "on_budget",
            "tracked_at": str(t_date),
        }

    async def get_execution_progress(self, plan_id: str) -> Dict[str, Any]:
        """获取预算执行进度（最新一次 execution）"""
        await self._set_tenant()
        plan = await self.get_plan(plan_id)
        if not plan:
            raise ValueError(f"预算计划 {plan_id} 不存在")

        result = await self.db.execute(
            text("""
                SELECT actual_fen, variance_fen, variance_pct, tracked_at, note, created_at
                FROM budget_executions
                WHERE tenant_id = :tid AND budget_plan_id = :pid
                ORDER BY tracked_at DESC, created_at DESC
                LIMIT 1
            """),
            {"tid": self._tid, "pid": uuid.UUID(plan_id)},
        )
        row = result.fetchone()

        budget_fen = plan["budget_fen"]
        if row:
            actual_fen = row.actual_fen
            variance_fen = row.variance_fen
            variance_pct = float(row.variance_pct) if row.variance_pct is not None else None
            completion_rate = round(actual_fen / budget_fen * 100, 2) if budget_fen > 0 else 0.0
        else:
            actual_fen = 0
            variance_fen = -budget_fen
            variance_pct = -100.0 if budget_fen > 0 else None
            completion_rate = 0.0

        return {
            "plan_id": plan_id,
            "store_id": plan["store_id"],
            "period": plan["period"],
            "category": plan["category"],
            "budget_fen": budget_fen,
            "budget_yuan": round(budget_fen / 100, 2),
            "actual_fen": actual_fen,
            "actual_yuan": round(actual_fen / 100, 2),
            "variance_fen": variance_fen,
            "variance_yuan": round(variance_fen / 100, 2),
            "variance_pct": variance_pct,
            "completion_rate": completion_rate,
            "execution_status": "over_budget"
            if variance_fen > 0
            else "under_budget"
            if variance_fen < 0
            else "on_budget",
            "last_tracked_at": str(row.tracked_at) if row else None,
        }

    # ══════════════════════════════════════════════════════
    # 多维汇总
    # ══════════════════════════════════════════════════════

    async def get_store_budget_summary(
        self,
        store_id: str,
        period_type: str,
        period: str,
    ) -> Dict[str, Any]:
        """获取一个门店某期间各科目的预算 vs 实际汇总"""
        await self._set_tenant()
        sid = uuid.UUID(store_id)

        # 预算计划
        plans_result = await self.db.execute(
            text("""
                SELECT id, category, budget_fen, status
                FROM budget_plans
                WHERE tenant_id = :tid AND store_id = :sid
                  AND period_type = :ptype AND period = :period
                ORDER BY category
            """),
            {"tid": self._tid, "sid": sid, "ptype": period_type, "period": period},
        )
        plans = {
            r.category: {"plan_id": str(r.id), "budget_fen": r.budget_fen, "status": r.status}
            for r in plans_result.fetchall()
        }

        if not plans:
            return {
                "store_id": store_id,
                "period_type": period_type,
                "period": period,
                "categories": [],
                "total_budget_fen": 0,
                "total_actual_fen": 0,
            }

        plan_ids = [uuid.UUID(p["plan_id"]) for p in plans.values()]

        # 最新执行金额（每个 plan 取最新一条）
        exec_result = await self.db.execute(
            text("""
                SELECT DISTINCT ON (budget_plan_id)
                    budget_plan_id, actual_fen, variance_fen, variance_pct, tracked_at
                FROM budget_executions
                WHERE tenant_id = :tid AND budget_plan_id = ANY(:pids)
                ORDER BY budget_plan_id, tracked_at DESC, created_at DESC
            """),
            {"tid": self._tid, "pids": plan_ids},
        )
        executions = {
            str(r.budget_plan_id): {
                "actual_fen": r.actual_fen,
                "variance_fen": r.variance_fen,
                "tracked_at": str(r.tracked_at),
            }
            for r in exec_result.fetchall()
        }

        categories = []
        total_budget = 0
        total_actual = 0
        for cat, p in plans.items():
            exc = executions.get(p["plan_id"], {})
            bfen = p["budget_fen"]
            afen = exc.get("actual_fen", 0)
            vfen = afen - bfen
            total_budget += bfen
            total_actual += afen
            categories.append(
                {
                    "category": cat,
                    "plan_id": p["plan_id"],
                    "budget_fen": bfen,
                    "budget_yuan": round(bfen / 100, 2),
                    "actual_fen": afen,
                    "actual_yuan": round(afen / 100, 2),
                    "variance_fen": vfen,
                    "variance_pct": round(vfen / bfen * 100, 2) if bfen != 0 else None,
                    "completion_rate": round(afen / bfen * 100, 2) if bfen > 0 else 0.0,
                    "plan_status": p["status"],
                    "last_tracked_at": exc.get("tracked_at"),
                }
            )

        return {
            "store_id": store_id,
            "period_type": period_type,
            "period": period,
            "categories": categories,
            "total_budget_fen": total_budget,
            "total_budget_yuan": round(total_budget / 100, 2),
            "total_actual_fen": total_actual,
            "total_actual_yuan": round(total_actual / 100, 2),
            "total_variance_fen": total_actual - total_budget,
            "overall_completion_rate": round(total_actual / total_budget * 100, 2) if total_budget > 0 else 0.0,
        }

    # ══════════════════════════════════════════════════════
    # 内部工具
    # ══════════════════════════════════════════════════════

    def _plan_row(self, row) -> Dict[str, Any]:
        return {
            "plan_id": str(row.id),
            "tenant_id": self.tenant_id,
            "store_id": str(row.store_id),
            "period_type": row.period_type,
            "period": row.period,
            "category": row.category,
            "budget_fen": row.budget_fen,
            "budget_yuan": round(row.budget_fen / 100, 2),
            "note": getattr(row, "note", None),
            "created_by": str(row.created_by) if getattr(row, "created_by", None) else None,
            "approved_by": str(row.approved_by) if getattr(row, "approved_by", None) else None,
            "approved_at": row.approved_at.isoformat() if getattr(row, "approved_at", None) else None,
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
