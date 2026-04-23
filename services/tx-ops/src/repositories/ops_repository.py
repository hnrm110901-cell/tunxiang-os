"""日清日结 Repository — 封装 E1-E8 核心表的所有 DB 操作

架构约束：
  - 所有方法通过 AsyncSession 操作，由路由层 Depends(get_db) 注入
  - 每次 DB 操作前通过 set_config 设置 RLS tenant_id
  - 金额字段统一使用 int（分），严禁 float
  - 不直接 import 路由层任何模块（单向依赖）
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import and_, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import (
    DailySummary,
    EmployeeDailyPerformance,
    InspectionReport,
    OpsIssue,
    ShiftHandover,
)

logger = structlog.get_logger(__name__)

_SET_TENANT_SQL = text("SELECT set_config('app.tenant_id', :tid, true)")


class OpsRepository:
    """日清日结持久化操作 — Repository 模式

    所有公开方法首先设置 RLS tenant_id，保证数据隔离。
    """

    def __init__(self, session: AsyncSession, tenant_id: str) -> None:
        self.session = session
        self.tenant_id = UUID(tenant_id)
        self._tenant_id_str = tenant_id

    async def _set_rls(self) -> None:
        """设置 RLS 租户上下文 — 每次事务操作前必须调用"""
        await self.session.execute(_SET_TENANT_SQL, {"tid": self._tenant_id_str})

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  E1: 班次交班
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def create_shift(
        self,
        store_id: str,
        shift_date: date,
        shift_type: str,
        handover_by: str,
    ) -> dict[str, Any]:
        """创建班次记录"""
        await self._set_rls()
        now = datetime.now(tz=timezone.utc)
        shift = ShiftHandover(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            store_id=UUID(store_id),
            shift_date=shift_date,
            shift_type=shift_type,
            start_time=now,
            handover_by=handover_by,
            status="pending",
        )
        self.session.add(shift)
        await self.session.flush()
        return self._shift_to_dict(shift)

    async def get_shift(self, shift_id: str) -> Optional[dict[str, Any]]:
        """查询单个班次"""
        await self._set_rls()
        stmt = select(ShiftHandover).where(
            and_(
                ShiftHandover.id == UUID(shift_id),
                ShiftHandover.is_deleted.is_(False),
            )
        )
        result = await self.session.execute(stmt)
        shift = result.scalar_one_or_none()
        return self._shift_to_dict(shift) if shift else None

    async def update_shift(self, shift_id: str, **kwargs: Any) -> Optional[dict[str, Any]]:
        """更新班次字段"""
        await self._set_rls()
        kwargs["updated_at"] = datetime.now(tz=timezone.utc)
        stmt = (
            update(ShiftHandover)
            .where(
                and_(
                    ShiftHandover.id == UUID(shift_id),
                    ShiftHandover.is_deleted.is_(False),
                )
            )
            .values(**kwargs)
            .returning(ShiftHandover)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._shift_to_dict(row) if row else None

    async def list_shifts(
        self,
        store_id: str,
        shift_date: Optional[date] = None,
    ) -> list[dict[str, Any]]:
        """按门店+日期查询班次列表"""
        await self._set_rls()
        conditions = [
            ShiftHandover.store_id == UUID(store_id),
            ShiftHandover.is_deleted.is_(False),
        ]
        if shift_date:
            conditions.append(ShiftHandover.shift_date == shift_date)
        stmt = select(ShiftHandover).where(and_(*conditions)).order_by(ShiftHandover.created_at)
        result = await self.session.execute(stmt)
        return [self._shift_to_dict(s) for s in result.scalars().all()]

    def _shift_to_dict(self, s: ShiftHandover) -> dict[str, Any]:
        return {
            "id": str(s.id),
            "tenant_id": str(s.tenant_id),
            "store_id": str(s.store_id),
            "shift_date": s.shift_date.isoformat() if s.shift_date else None,
            "shift_type": s.shift_type,
            "start_time": s.start_time.isoformat() if s.start_time else None,
            "end_time": s.end_time.isoformat() if s.end_time else None,
            "handover_by": s.handover_by,
            "received_by": s.received_by,
            "cash_counted_fen": s.cash_counted_fen or 0,
            "pos_cash_fen": s.pos_cash_fen or 0,
            "cash_diff_fen": s.cash_diff_fen or 0,
            "device_checklist": s.device_checklist or [],
            "notes": s.notes,
            "status": s.status,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  E2: 日营业汇总
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def upsert_daily_summary(
        self,
        store_id: str,
        summary_date: date,
        aggregated: dict[str, Any],
    ) -> dict[str, Any]:
        """创建或更新日汇总"""
        await self._set_rls()
        now = datetime.now(tz=timezone.utc)
        # 先查是否存在
        stmt = select(DailySummary).where(
            and_(
                DailySummary.store_id == UUID(store_id),
                DailySummary.summary_date == summary_date,
                DailySummary.is_deleted.is_(False),
            )
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            if existing.status == "locked":
                return self._summary_to_dict(existing)
            for k, v in aggregated.items():
                if hasattr(existing, k):
                    setattr(existing, k, v)
            existing.updated_at = now
            await self.session.flush()
            return self._summary_to_dict(existing)

        summary = DailySummary(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            store_id=UUID(store_id),
            summary_date=summary_date,
            status="draft",
            **{k: v for k, v in aggregated.items() if hasattr(DailySummary, k)},
        )
        self.session.add(summary)
        await self.session.flush()
        return self._summary_to_dict(summary)

    async def get_daily_summary(self, store_id: str, summary_date: date) -> Optional[dict[str, Any]]:
        """查询单日汇总"""
        await self._set_rls()
        stmt = select(DailySummary).where(
            and_(
                DailySummary.store_id == UUID(store_id),
                DailySummary.summary_date == summary_date,
                DailySummary.is_deleted.is_(False),
            )
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._summary_to_dict(row) if row else None

    async def confirm_daily_summary(self, summary_id: str, confirmed_by: str) -> Optional[dict[str, Any]]:
        """确认锁定日汇总"""
        await self._set_rls()
        now = datetime.now(tz=timezone.utc)
        stmt = (
            update(DailySummary)
            .where(
                and_(
                    DailySummary.id == UUID(summary_id),
                    DailySummary.is_deleted.is_(False),
                )
            )
            .values(
                status="locked",
                confirmed_by=confirmed_by,
                confirmed_at=now,
                updated_at=now,
            )
            .returning(DailySummary)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._summary_to_dict(row) if row else None

    async def list_daily_summaries(
        self, summary_date: date, store_ids: Optional[list[str]] = None
    ) -> list[dict[str, Any]]:
        """多门店汇总列表"""
        await self._set_rls()
        conditions = [
            DailySummary.summary_date == summary_date,
            DailySummary.is_deleted.is_(False),
        ]
        if store_ids:
            conditions.append(DailySummary.store_id.in_([UUID(s) for s in store_ids]))
        stmt = select(DailySummary).where(and_(*conditions)).order_by(DailySummary.actual_revenue_fen.desc())
        result = await self.session.execute(stmt)
        return [self._summary_to_dict(s) for s in result.scalars().all()]

    def _summary_to_dict(self, s: DailySummary) -> dict[str, Any]:
        return {
            "id": str(s.id),
            "tenant_id": str(s.tenant_id),
            "store_id": str(s.store_id),
            "summary_date": s.summary_date.isoformat() if s.summary_date else None,
            "total_orders": s.total_orders or 0,
            "dine_in_orders": s.dine_in_orders or 0,
            "takeaway_orders": s.takeaway_orders or 0,
            "banquet_orders": s.banquet_orders or 0,
            "total_revenue_fen": s.total_revenue_fen or 0,
            "actual_revenue_fen": s.actual_revenue_fen or 0,
            "total_discount_fen": s.total_discount_fen or 0,
            "avg_table_value_fen": s.avg_table_value_fen or 0,
            "max_discount_pct": s.max_discount_pct,
            "abnormal_discounts": s.abnormal_discounts or 0,
            "status": s.status,
            "confirmed_by": s.confirmed_by,
            "confirmed_at": s.confirmed_at.isoformat() if s.confirmed_at else None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            "is_deleted": s.is_deleted,
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  E5/E6: 问题预警与整改
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def create_issue(
        self,
        store_id: str,
        issue_date: date,
        issue_type: str,
        severity: str,
        title: str,
        description: Optional[str] = None,
        evidence_urls: Optional[list[str]] = None,
        assigned_to: Optional[str] = None,
        due_at: Optional[datetime] = None,
        created_by: Optional[str] = None,
    ) -> dict[str, Any]:
        """创建问题记录"""
        await self._set_rls()
        issue = OpsIssue(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            store_id=UUID(store_id),
            issue_date=issue_date,
            issue_type=issue_type,
            severity=severity,
            title=title,
            description=description,
            evidence_urls=evidence_urls,
            assigned_to=assigned_to,
            due_at=due_at,
            status="open",
            created_by=created_by,
        )
        self.session.add(issue)
        await self.session.flush()
        return self._issue_to_dict(issue)

    async def get_issue(self, issue_id: str) -> Optional[dict[str, Any]]:
        """查询单个问题"""
        await self._set_rls()
        stmt = select(OpsIssue).where(and_(OpsIssue.id == UUID(issue_id), OpsIssue.is_deleted.is_(False)))
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._issue_to_dict(row) if row else None

    async def update_issue(self, issue_id: str, **kwargs: Any) -> Optional[dict[str, Any]]:
        """更新问题字段"""
        await self._set_rls()
        kwargs["updated_at"] = datetime.now(tz=timezone.utc)
        stmt = (
            update(OpsIssue)
            .where(and_(OpsIssue.id == UUID(issue_id), OpsIssue.is_deleted.is_(False)))
            .values(**kwargs)
            .returning(OpsIssue)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._issue_to_dict(row) if row else None

    async def list_issues(
        self,
        store_id: Optional[str] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        issue_type: Optional[str] = None,
        issue_date: Optional[date] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """查询问题列表（分页）"""
        await self._set_rls()
        conditions = [OpsIssue.is_deleted.is_(False)]
        if store_id:
            conditions.append(OpsIssue.store_id == UUID(store_id))
        if status:
            conditions.append(OpsIssue.status == status)
        if severity:
            conditions.append(OpsIssue.severity == severity)
        if issue_type:
            conditions.append(OpsIssue.issue_type == issue_type)
        if issue_date:
            conditions.append(OpsIssue.issue_date == issue_date)

        count_stmt = select(func.count()).select_from(OpsIssue).where(and_(*conditions))
        total = (await self.session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(OpsIssue)
            .where(and_(*conditions))
            .order_by(OpsIssue.severity, OpsIssue.created_at)
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await self.session.execute(stmt)
        items = [self._issue_to_dict(i) for i in result.scalars().all()]
        return items, total

    async def count_open_critical_issues(self, store_id: str, issue_date: date) -> dict[str, int]:
        """统计当日未处理关键问题数"""
        await self._set_rls()
        conditions = [
            OpsIssue.store_id == UUID(store_id),
            OpsIssue.issue_date == issue_date,
            OpsIssue.is_deleted.is_(False),
        ]
        total_stmt = select(func.count()).select_from(OpsIssue).where(and_(*conditions))
        total = (await self.session.execute(total_stmt)).scalar() or 0

        open_conditions = conditions + [
            OpsIssue.status.in_(["open", "in_progress"]),
            OpsIssue.severity.in_(["critical", "high"]),
        ]
        open_stmt = select(func.count()).select_from(OpsIssue).where(and_(*open_conditions))
        open_critical = (await self.session.execute(open_stmt)).scalar() or 0

        open_all_conditions = conditions + [OpsIssue.status.in_(["open", "in_progress"])]
        open_all_stmt = select(func.count()).select_from(OpsIssue).where(and_(*open_all_conditions))
        open_all = (await self.session.execute(open_all_stmt)).scalar() or 0

        return {"total": total, "open_critical_high": open_critical, "open_all": open_all}

    def _issue_to_dict(self, i: OpsIssue) -> dict[str, Any]:
        return {
            "id": str(i.id),
            "tenant_id": str(i.tenant_id),
            "store_id": str(i.store_id),
            "issue_date": i.issue_date.isoformat() if i.issue_date else None,
            "issue_type": i.issue_type,
            "severity": i.severity,
            "title": i.title,
            "description": i.description,
            "evidence_urls": i.evidence_urls or [],
            "assigned_to": i.assigned_to,
            "due_at": i.due_at.isoformat() if i.due_at else None,
            "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
            "resolution_notes": i.resolution_notes,
            "status": i.status,
            "created_by": i.created_by,
            "created_at": i.created_at.isoformat() if i.created_at else None,
            "updated_at": i.updated_at.isoformat() if i.updated_at else None,
            "is_deleted": i.is_deleted,
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  E8: 巡店质检
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def create_inspection(
        self,
        store_id: str,
        inspection_date: date,
        inspector_id: str,
        overall_score: Optional[float] = None,
        dimensions: Optional[list[dict]] = None,
        photos: Optional[list[dict]] = None,
        action_items: Optional[list[dict]] = None,
    ) -> dict[str, Any]:
        """创建巡店报告"""
        await self._set_rls()
        report = InspectionReport(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            store_id=UUID(store_id),
            inspection_date=inspection_date,
            inspector_id=inspector_id,
            overall_score=overall_score,
            dimensions=dimensions,
            photos=photos,
            action_items=action_items,
            status="draft",
        )
        self.session.add(report)
        await self.session.flush()
        return self._inspection_to_dict(report)

    async def get_inspection(self, report_id: str) -> Optional[dict[str, Any]]:
        """查询单个巡店报告"""
        await self._set_rls()
        stmt = select(InspectionReport).where(
            and_(
                InspectionReport.id == UUID(report_id),
                InspectionReport.is_deleted.is_(False),
            )
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._inspection_to_dict(row) if row else None

    async def update_inspection(self, report_id: str, **kwargs: Any) -> Optional[dict[str, Any]]:
        """更新巡店报告"""
        await self._set_rls()
        kwargs["updated_at"] = datetime.now(tz=timezone.utc)
        stmt = (
            update(InspectionReport)
            .where(
                and_(
                    InspectionReport.id == UUID(report_id),
                    InspectionReport.is_deleted.is_(False),
                )
            )
            .values(**kwargs)
            .returning(InspectionReport)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._inspection_to_dict(row) if row else None

    async def list_inspections(
        self,
        store_id: Optional[str] = None,
        inspector_id: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """查询巡店报告列表（分页）"""
        await self._set_rls()
        conditions = [InspectionReport.is_deleted.is_(False)]
        if store_id:
            conditions.append(InspectionReport.store_id == UUID(store_id))
        if inspector_id:
            conditions.append(InspectionReport.inspector_id == inspector_id)
        if status:
            conditions.append(InspectionReport.status == status)
        if start_date:
            conditions.append(InspectionReport.inspection_date >= start_date)
        if end_date:
            conditions.append(InspectionReport.inspection_date <= end_date)

        count_stmt = select(func.count()).select_from(InspectionReport).where(and_(*conditions))
        total = (await self.session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(InspectionReport)
            .where(and_(*conditions))
            .order_by(InspectionReport.inspection_date.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await self.session.execute(stmt)
        items = [self._inspection_to_dict(r) for r in result.scalars().all()]
        return items, total

    def _inspection_to_dict(self, r: InspectionReport) -> dict[str, Any]:
        return {
            "id": str(r.id),
            "tenant_id": str(r.tenant_id),
            "store_id": str(r.store_id),
            "inspection_date": r.inspection_date.isoformat() if r.inspection_date else None,
            "inspector_id": r.inspector_id,
            "overall_score": r.overall_score,
            "dimensions": r.dimensions or [],
            "photos": r.photos or [],
            "action_items": r.action_items or [],
            "status": r.status,
            "acknowledged_by": r.acknowledged_by,
            "acknowledged_at": r.acknowledged_at.isoformat() if r.acknowledged_at else None,
            "notes": r.notes,
            "ack_notes": r.ack_notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "is_deleted": r.is_deleted,
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  E7: 员工日绩效
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def upsert_performance(
        self,
        store_id: str,
        perf_date: date,
        employee_id: str,
        employee_name: str,
        role: str,
        orders_handled: int = 0,
        revenue_generated_fen: int = 0,
        dishes_completed: int = 0,
        tables_served: int = 0,
        avg_service_score: Optional[float] = None,
        base_commission_fen: int = 0,
    ) -> dict[str, Any]:
        """创建或更新员工日绩效"""
        await self._set_rls()
        now = datetime.now(tz=timezone.utc)
        stmt = select(EmployeeDailyPerformance).where(
            and_(
                EmployeeDailyPerformance.store_id == UUID(store_id),
                EmployeeDailyPerformance.perf_date == perf_date,
                EmployeeDailyPerformance.employee_id == employee_id,
                EmployeeDailyPerformance.is_deleted.is_(False),
            )
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.employee_name = employee_name
            existing.role = role
            existing.orders_handled = orders_handled
            existing.revenue_generated_fen = revenue_generated_fen
            existing.dishes_completed = dishes_completed
            existing.tables_served = tables_served
            existing.avg_service_score = avg_service_score
            existing.base_commission_fen = base_commission_fen
            existing.updated_at = now
            await self.session.flush()
            return self._perf_to_dict(existing)

        perf = EmployeeDailyPerformance(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            store_id=UUID(store_id),
            perf_date=perf_date,
            employee_id=employee_id,
            employee_name=employee_name,
            role=role,
            orders_handled=orders_handled,
            revenue_generated_fen=revenue_generated_fen,
            dishes_completed=dishes_completed,
            tables_served=tables_served,
            avg_service_score=avg_service_score,
            base_commission_fen=base_commission_fen,
        )
        self.session.add(perf)
        await self.session.flush()
        return self._perf_to_dict(perf)

    async def list_performance(
        self,
        store_id: str,
        perf_date: date,
        role: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """查询员工绩效列表（分页）"""
        await self._set_rls()
        conditions = [
            EmployeeDailyPerformance.store_id == UUID(store_id),
            EmployeeDailyPerformance.perf_date == perf_date,
            EmployeeDailyPerformance.is_deleted.is_(False),
        ]
        if role:
            conditions.append(EmployeeDailyPerformance.role == role)

        count_stmt = select(func.count()).select_from(EmployeeDailyPerformance).where(and_(*conditions))
        total = (await self.session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(EmployeeDailyPerformance)
            .where(and_(*conditions))
            .order_by(EmployeeDailyPerformance.base_commission_fen.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await self.session.execute(stmt)
        items = [self._perf_to_dict(p) for p in result.scalars().all()]
        return items, total

    async def get_performance_ranking(
        self,
        perf_date: date,
        store_id: Optional[str] = None,
        role: Optional[str] = None,
        top_n: int = 10,
    ) -> list[dict[str, Any]]:
        """员工绩效排行"""
        await self._set_rls()
        conditions = [
            EmployeeDailyPerformance.perf_date == perf_date,
            EmployeeDailyPerformance.is_deleted.is_(False),
        ]
        if store_id:
            conditions.append(EmployeeDailyPerformance.store_id == UUID(store_id))
        if role:
            conditions.append(EmployeeDailyPerformance.role == role)

        stmt = (
            select(EmployeeDailyPerformance)
            .where(and_(*conditions))
            .order_by(EmployeeDailyPerformance.base_commission_fen.desc())
            .limit(top_n)
        )
        result = await self.session.execute(stmt)
        items = [self._perf_to_dict(p) for p in result.scalars().all()]
        for i, p in enumerate(items):
            p["rank"] = i + 1
        return items

    def _perf_to_dict(self, p: EmployeeDailyPerformance) -> dict[str, Any]:
        return {
            "id": str(p.id),
            "tenant_id": str(p.tenant_id),
            "store_id": str(p.store_id),
            "perf_date": p.perf_date.isoformat() if p.perf_date else None,
            "employee_id": p.employee_id,
            "employee_name": p.employee_name or "",
            "role": p.role,
            "orders_handled": p.orders_handled or 0,
            "revenue_generated_fen": p.revenue_generated_fen or 0,
            "dishes_completed": p.dishes_completed or 0,
            "tables_served": p.tables_served or 0,
            "avg_service_score": p.avg_service_score,
            "base_commission_fen": p.base_commission_fen or 0,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }
