"""预算管理服务 v1 — 门店预算编制 + 执行跟踪（v101）

功能：
  - 创建/审批/更新预算计划（budget_plans）
  - 录入实际执行金额（budget_executions 追加写入）
  - 查询预算执行进度（计划 vs 实际 vs 差异）
  - 多门店/多科目预算汇总
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

VALID_CATEGORIES = (
    "revenue", "ingredient_cost", "labor_cost",
    "fixed_cost", "marketing_cost", "total",
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
        log.info("budget_plan_upserted", store_id=store_id, period=period,
                 category=category, budget_fen=budget_fen, tenant_id=self.tenant_id)
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
        log.info("budget_plan_approved", plan_id=plan_id, approved_by=approved_by,
                 tenant_id=self.tenant_id)
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
        log.info("budget_execution_recorded", plan_id=plan_id, actual_fen=actual_fen,
                 variance_fen=variance_fen, tenant_id=self.tenant_id)

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
            "execution_status": "over_budget" if variance_fen > 0 else "under_budget" if variance_fen < 0 else "on_budget",
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
        plans = {r.category: {"plan_id": str(r.id), "budget_fen": r.budget_fen, "status": r.status}
                 for r in plans_result.fetchall()}

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
        executions = {str(r.budget_plan_id): {
            "actual_fen": r.actual_fen,
            "variance_fen": r.variance_fen,
            "tracked_at": str(r.tracked_at),
        } for r in exec_result.fetchall()}

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
            categories.append({
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
            })

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
