"""
预算管理服务
负责预算的全生命周期管理：创建/审批/分配/调整/执行率统计/快照。

金额约定：所有金额存储为分(fen)，入参/出参统一用分，展示层负责转换。
update_used_amount 使用原子 SQL 更新，避免并发竞态条件。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models.budget import Budget, BudgetAdjustment, BudgetAllocation, BudgetSnapshot

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _today() -> date:
    return date.today()


# ─────────────────────────────────────────────────────────────────────────────
# BudgetService
# ─────────────────────────────────────────────────────────────────────────────

class BudgetService:
    """预算管理服务，所有方法显式传入 tenant_id 确保 RLS 安全隔离。"""

    # ── 基础 CRUD ─────────────────────────────────────────────────────────────

    async def create_budget(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        created_by: uuid.UUID,
        data: dict,
    ) -> Budget:
        """创建预算。

        data 字段：
            budget_name (str, required)
            budget_year (int, required)
            budget_month (int | None): None=年度预算，1-12=月度预算
            budget_type (str): expense/travel/procurement，默认 expense
            store_id (UUID | None): None=集团预算
            department (str | None)
            total_amount (int, required): 预算总额，单位分
            status (str): draft/active/locked/expired，默认 active
            notes (str | None)
        """
        log = logger.bind(tenant_id=str(tenant_id), created_by=str(created_by))

        budget = Budget(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            budget_name=data["budget_name"],
            budget_year=data["budget_year"],
            budget_month=data.get("budget_month"),
            budget_type=data.get("budget_type", "expense"),
            store_id=data.get("store_id"),
            department=data.get("department"),
            total_amount=data["total_amount"],
            used_amount=0,
            status=data.get("status", "active"),
            notes=data.get("notes"),
            created_by=created_by,
        )
        db.add(budget)
        await db.flush()

        log.info(
            "budget_created",
            budget_id=str(budget.id),
            budget_year=budget.budget_year,
            budget_month=budget.budget_month,
            budget_type=budget.budget_type,
            total_amount=budget.total_amount,
        )
        return budget

    async def get_budget(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        budget_id: uuid.UUID,
    ) -> Budget:
        """查询单个预算，预加载 allocations。

        Raises:
            LookupError: 找不到或跨租户访问时抛出。
        """
        stmt = (
            select(Budget)
            .where(
                Budget.id == budget_id,
                Budget.tenant_id == tenant_id,
                Budget.is_deleted == False,  # noqa: E712
            )
            .options(selectinload(Budget.allocations))
        )
        result = await db.execute(stmt)
        budget = result.scalar_one_or_none()

        if budget is None:
            raise LookupError(f"Budget {budget_id} not found for tenant {tenant_id}")
        return budget

    async def list_budgets(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        filters: dict,
    ) -> list[Budget]:
        """列出预算，支持多条件过滤，按 budget_year DESC, budget_month DESC 排序。

        filters 支持字段：
            year (int)
            month (int | None): 0 表示查询年度预算（budget_month IS NULL）
            budget_type (str)
            store_id (UUID | None)
            status (str)
        """
        where = [
            Budget.tenant_id == tenant_id,
            Budget.is_deleted == False,  # noqa: E712
        ]

        if "year" in filters and filters["year"] is not None:
            where.append(Budget.budget_year == filters["year"])
        if "month" in filters and filters["month"] is not None:
            month_val = filters["month"]
            if month_val == 0:
                where.append(Budget.budget_month == None)  # noqa: E711
            else:
                where.append(Budget.budget_month == month_val)
        if "budget_type" in filters and filters["budget_type"] is not None:
            where.append(Budget.budget_type == filters["budget_type"])
        if "store_id" in filters:
            store_id_val = filters["store_id"]
            if store_id_val is None:
                where.append(Budget.store_id == None)  # noqa: E711
            else:
                where.append(Budget.store_id == store_id_val)
        if "status" in filters and filters["status"] is not None:
            where.append(Budget.status == filters["status"])

        stmt = (
            select(Budget)
            .where(*where)
            .order_by(Budget.budget_year.desc(), Budget.budget_month.desc())
            .options(selectinload(Budget.allocations))
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def update_budget(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        budget_id: uuid.UUID,
        data: dict,
    ) -> Budget:
        """更新预算字段（仅允许 draft/active 状态更新）。

        可更新字段：budget_name, department, total_amount, status, notes
        """
        budget = await self.get_budget(db, tenant_id, budget_id)

        if budget.status in ("locked", "expired"):
            raise ValueError(
                f"Cannot update budget in status '{budget.status}'. "
                "Only draft/active budgets can be edited."
            )

        allowed_fields = {"budget_name", "department", "total_amount", "status", "notes"}
        for field in allowed_fields:
            if field in data:
                setattr(budget, field, data[field])

        await db.flush()

        logger.info(
            "budget_updated",
            tenant_id=str(tenant_id),
            budget_id=str(budget_id),
            updated_fields=list(data.keys()),
        )
        return budget

    async def approve_budget(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        budget_id: uuid.UUID,
        approved_by: uuid.UUID,
    ) -> Budget:
        """审批预算：将状态从 draft 变更为 active，记录审批人。"""
        budget = await self.get_budget(db, tenant_id, budget_id)

        if budget.status != "draft":
            raise ValueError(
                f"Cannot approve budget in status '{budget.status}'. "
                "Only draft budgets can be approved."
            )

        budget.status = "active"
        budget.approved_by = approved_by
        await db.flush()

        logger.info(
            "budget_approved",
            tenant_id=str(tenant_id),
            budget_id=str(budget_id),
            approved_by=str(approved_by),
        )
        return budget

    # ── 科目分配 ──────────────────────────────────────────────────────────────

    async def add_allocation(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        budget_id: uuid.UUID,
        category_code: str,
        amount: int,
    ) -> BudgetAllocation:
        """为预算添加科目分配。

        amount: 分配金额（分）
        """
        # 验证预算存在且属于本租户
        budget = await self.get_budget(db, tenant_id, budget_id)

        allocation = BudgetAllocation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            budget_id=budget_id,
            category_code=category_code,
            allocated_amount=amount,
            used_amount=0,
        )
        db.add(allocation)
        await db.flush()

        logger.info(
            "budget_allocation_added",
            tenant_id=str(tenant_id),
            budget_id=str(budget_id),
            category_code=category_code,
            allocated_amount=amount,
        )
        return allocation

    # ── 预算调整 ──────────────────────────────────────────────────────────────

    async def adjust_budget(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        budget_id: uuid.UUID,
        adjustment_type: str,
        amount: int,
        reason: Optional[str],
        approved_by: Optional[uuid.UUID],
        created_by: uuid.UUID,
    ) -> BudgetAdjustment:
        """记录预算调整并更新 total_amount。

        adjustment_type: increase/decrease/reallocate
        amount: 调整金额（分，正增负减）
        """
        budget = await self.get_budget(db, tenant_id, budget_id)

        if budget.status == "locked":
            raise ValueError("Cannot adjust a locked budget.")
        if budget.status == "expired":
            raise ValueError("Cannot adjust an expired budget.")

        # 记录调整记录
        adjustment = BudgetAdjustment(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            budget_id=budget_id,
            adjustment_type=adjustment_type,
            amount=amount,
            reason=reason,
            approved_by=approved_by,
            created_by=created_by,
        )
        db.add(adjustment)

        # 同步更新 total_amount
        budget.total_amount = budget.total_amount + amount
        await db.flush()

        logger.info(
            "budget_adjusted",
            tenant_id=str(tenant_id),
            budget_id=str(budget_id),
            adjustment_type=adjustment_type,
            amount=amount,
            new_total=budget.total_amount,
        )
        return adjustment

    # ── 执行率 ────────────────────────────────────────────────────────────────

    async def get_execution_rate(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        budget_id: uuid.UUID,
    ) -> dict:
        """计算预算执行率详情。

        Returns::
            {
                "budget_id": str,
                "total": int,         # 预算总额（分）
                "used": int,          # 已使用（分）
                "remaining": int,     # 剩余（分）
                "rate": float,        # 执行率，total=0 时返回 -1
                "allocations": [
                    {
                        "category_code": str,
                        "allocated": int,   # 分配额（分）
                        "used": int,        # 已使用（分）
                        "rate": float,
                    }
                ]
            }
        """
        budget = await self.get_budget(db, tenant_id, budget_id)

        total = budget.total_amount
        used = budget.used_amount
        remaining = total - used
        rate = round(used / total, 4) if total > 0 else -1.0

        # 查询科目分配执行明细
        alloc_stmt = select(BudgetAllocation).where(
            BudgetAllocation.budget_id == budget_id,
            BudgetAllocation.tenant_id == tenant_id,
        )
        alloc_result = await db.execute(alloc_stmt)
        allocations = list(alloc_result.scalars().all())

        alloc_details = []
        for a in allocations:
            a_rate = round(a.used_amount / a.allocated_amount, 4) if a.allocated_amount > 0 else -1.0
            alloc_details.append({
                "category_code": a.category_code,
                "allocated": a.allocated_amount,
                "used": a.used_amount,
                "rate": a_rate,
            })

        return {
            "budget_id": str(budget_id),
            "total": total,
            "used": used,
            "remaining": remaining,
            "rate": rate,
            "allocations": alloc_details,
        }

    # ── 原子更新 used_amount ──────────────────────────────────────────────────

    async def update_used_amount(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        budget_id: uuid.UUID,
        delta_fen: int,
    ) -> None:
        """原子性更新 used_amount（申请审批通过时调用）。

        使用 UPDATE ... SET used_amount = used_amount + :delta 原子语句，
        避免读取-修改-写入的并发竞态条件。

        delta_fen: 变化量（分），正值增加，负值减少（如撤销时用负值）。
        """
        stmt = (
            update(Budget)
            .where(
                Budget.id == budget_id,
                Budget.tenant_id == tenant_id,
                Budget.is_deleted == False,  # noqa: E712
            )
            .values(used_amount=Budget.used_amount + delta_fen)
        )
        result = await db.execute(stmt)

        if result.rowcount == 0:
            logger.error(
                "budget_update_used_amount_not_found",
                tenant_id=str(tenant_id),
                budget_id=str(budget_id),
                delta_fen=delta_fen,
            )
            raise LookupError(f"Budget {budget_id} not found for tenant {tenant_id}")

        logger.info(
            "budget_used_amount_updated",
            tenant_id=str(tenant_id),
            budget_id=str(budget_id),
            delta_fen=delta_fen,
        )

    # ── 当前预算查找 ───────────────────────────────────────────────────────────

    async def get_current_budget(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        budget_type: str,
        store_id: Optional[uuid.UUID] = None,
    ) -> Optional[Budget]:
        """查找当前年月的 active 预算。

        先查月度预算（budget_month=当前月），找不到再查年度预算（budget_month=NULL）。
        store_id 传 None 时查集团预算。
        """
        today = _today()

        # 先找月度预算
        monthly = await self._find_budget(
            db=db,
            tenant_id=tenant_id,
            budget_type=budget_type,
            year=today.year,
            month=today.month,
            store_id=store_id,
        )
        if monthly is not None:
            return monthly

        # 再找年度预算
        annual = await self._find_budget(
            db=db,
            tenant_id=tenant_id,
            budget_type=budget_type,
            year=today.year,
            month=None,
            store_id=store_id,
        )
        return annual

    async def _find_budget(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        budget_type: str,
        year: int,
        month: Optional[int],
        store_id: Optional[uuid.UUID],
    ) -> Optional[Budget]:
        """内部：按精确条件查找单个预算。"""
        where = [
            Budget.tenant_id == tenant_id,
            Budget.budget_type == budget_type,
            Budget.budget_year == year,
            Budget.status == "active",
            Budget.is_deleted == False,  # noqa: E712
        ]

        if month is None:
            where.append(Budget.budget_month == None)  # noqa: E711
        else:
            where.append(Budget.budget_month == month)

        if store_id is None:
            where.append(Budget.store_id == None)  # noqa: E711
        else:
            where.append(Budget.store_id == store_id)

        stmt = select(Budget).where(*where).limit(1)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    # ── 快照 ─────────────────────────────────────────────────────────────────

    async def take_snapshot(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        budget_id: uuid.UUID,
    ) -> BudgetSnapshot:
        """为指定预算创建今日快照。"""
        budget = await self.get_budget(db, tenant_id, budget_id)
        today = _today()

        total = budget.total_amount
        used = budget.used_amount
        rate = Decimal(str(round(used / total, 4))) if total > 0 else Decimal("0")

        # 查询分配明细
        alloc_stmt = select(BudgetAllocation).where(
            BudgetAllocation.budget_id == budget_id,
            BudgetAllocation.tenant_id == tenant_id,
        )
        alloc_result = await db.execute(alloc_stmt)
        allocations = list(alloc_result.scalars().all())

        alloc_data = [
            {
                "category_code": a.category_code,
                "allocated_amount": a.allocated_amount,
                "used_amount": a.used_amount,
                "rate": round(a.used_amount / a.allocated_amount, 4) if a.allocated_amount > 0 else 0,
            }
            for a in allocations
        ]

        snapshot_data = {
            "budget_name": budget.budget_name,
            "budget_year": budget.budget_year,
            "budget_month": budget.budget_month,
            "budget_type": budget.budget_type,
            "store_id": str(budget.store_id) if budget.store_id else None,
            "total_amount": total,
            "used_amount": used,
            "execution_rate": float(rate),
            "allocations": alloc_data,
        }

        snapshot = BudgetSnapshot(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            budget_id=budget_id,
            snapshot_date=today,
            total_amount=total,
            used_amount=used,
            execution_rate=rate,
            snapshot_data=snapshot_data,
        )
        db.add(snapshot)
        await db.flush()

        logger.info(
            "budget_snapshot_created",
            tenant_id=str(tenant_id),
            budget_id=str(budget_id),
            snapshot_date=today.isoformat(),
            execution_rate=float(rate),
        )
        return snapshot

    async def run_monthly_snapshot(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> int:
        """批量为租户所有 active 预算创建今日快照，返回快照数量。"""
        stmt = select(Budget).where(
            Budget.tenant_id == tenant_id,
            Budget.status == "active",
            Budget.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        budgets = list(result.scalars().all())

        count = 0
        for budget in budgets:
            try:
                await self.take_snapshot(db=db, tenant_id=tenant_id, budget_id=budget.id)
                count += 1
            except (OperationalError, SQLAlchemyError) as exc:
                logger.error(
                    "budget_monthly_snapshot_item_failed",
                    tenant_id=str(tenant_id),
                    budget_id=str(budget.id),
                    error=str(exc),
                    exc_info=True,
                )

        logger.info(
            "budget_monthly_snapshot_complete",
            tenant_id=str(tenant_id),
            snapshot_count=count,
            total_budgets=len(budgets),
        )
        return count

    # ── 年度统计 ──────────────────────────────────────────────────────────────

    async def get_budget_stats(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        year: int,
    ) -> dict:
        """年度预算汇总统计（各月执行率趋势）。

        Returns::
            {
                "year": int,
                "total_budget": int,      # 全年预算总额（分）
                "total_used": int,        # 全年已使用（分）
                "overall_rate": float,
                "monthly_trend": [
                    {
                        "month": int,
                        "budget_count": int,
                        "total_budget": int,
                        "total_used": int,
                        "avg_rate": float,
                    }
                ],
                "by_type": {
                    budget_type: {"total_budget": int, "total_used": int, "rate": float}
                },
            }
        """
        stmt = select(Budget).where(
            Budget.tenant_id == tenant_id,
            Budget.budget_year == year,
            Budget.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        budgets = list(result.scalars().all())

        total_budget = sum(b.total_amount for b in budgets)
        total_used = sum(b.used_amount for b in budgets)
        overall_rate = round(total_used / total_budget, 4) if total_budget > 0 else 0.0

        # 按月份分组
        monthly: dict[int, dict] = {}
        for b in budgets:
            if b.budget_month is None:
                continue
            m = b.budget_month
            if m not in monthly:
                monthly[m] = {"month": m, "budget_count": 0, "total_budget": 0, "total_used": 0}
            monthly[m]["budget_count"] += 1
            monthly[m]["total_budget"] += b.total_amount
            monthly[m]["total_used"] += b.used_amount

        monthly_trend = []
        for m in sorted(monthly.keys()):
            item = monthly[m]
            avg_rate = round(item["total_used"] / item["total_budget"], 4) if item["total_budget"] > 0 else 0.0
            monthly_trend.append({**item, "avg_rate": avg_rate})

        # 按预算类型分组
        by_type: dict[str, dict] = {}
        for b in budgets:
            t = b.budget_type
            if t not in by_type:
                by_type[t] = {"total_budget": 0, "total_used": 0}
            by_type[t]["total_budget"] += b.total_amount
            by_type[t]["total_used"] += b.used_amount

        for t in by_type:
            tb = by_type[t]["total_budget"]
            tu = by_type[t]["total_used"]
            by_type[t]["rate"] = round(tu / tb, 4) if tb > 0 else 0.0

        return {
            "year": year,
            "total_budget": total_budget,
            "total_used": total_used,
            "overall_rate": overall_rate,
            "monthly_trend": monthly_trend,
            "by_type": by_type,
        }

    # ── 按科目/门店查找适用预算 ────────────────────────────────────────────────

    async def find_budget_for_expense(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        category_code: str,
        store_id: Optional[uuid.UUID] = None,
    ) -> Optional[Budget]:
        """按科目/门店查找当前适用预算。

        查找策略（优先级递减）：
        1. 门店级月度预算（含该科目分配）
        2. 集团级月度预算（含该科目分配）
        3. 门店级年度预算
        4. 集团级年度预算

        Returns:
            找到的 Budget，或 None（未配置预算）。
        """
        today = _today()

        search_candidates = [
            # (store_id, is_monthly)
            (store_id, True),   # 1. 门店月度
            (None, True),       # 2. 集团月度
            (store_id, False),  # 3. 门店年度
            (None, False),      # 4. 集团年度
        ]

        for sid, is_monthly in search_candidates:
            if sid is None and store_id is None and is_monthly is False:
                # 门店年度和集团年度均为 None 时合并去重
                pass

            month = today.month if is_monthly else None

            # 先找含指定科目分配的预算
            alloc_stmt = (
                select(Budget)
                .join(BudgetAllocation, BudgetAllocation.budget_id == Budget.id)
                .where(
                    Budget.tenant_id == tenant_id,
                    Budget.budget_year == today.year,
                    Budget.status == "active",
                    Budget.is_deleted == False,  # noqa: E712
                    BudgetAllocation.tenant_id == tenant_id,
                    BudgetAllocation.category_code == category_code,
                    Budget.budget_month == month if month is not None else Budget.budget_month == None,  # noqa: E711
                    Budget.store_id == sid if sid is not None else Budget.store_id == None,  # noqa: E711
                )
                .limit(1)
            )
            alloc_result = await db.execute(alloc_stmt)
            budget = alloc_result.scalar_one_or_none()
            if budget is not None:
                return budget

            # 其次找不限科目（无分配记录）的通用预算
            generic = await self._find_budget(
                db=db,
                tenant_id=tenant_id,
                budget_type="expense",
                year=today.year,
                month=month,
                store_id=sid,
            )
            if generic is not None:
                return generic

        return None
