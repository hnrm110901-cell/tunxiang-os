"""借调成本分摊引擎 — 异步 DB 版

编排 DB 读写与纯函数计算。核心计算逻辑复用 store_transfer_service.py。
金额单位统一为"分"（fen）。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

import structlog
from services.store_transfer_service import (
    compute_cost_split,
    compute_time_split,
    generate_cost_analysis_report,
    generate_detail_report,
    generate_summary_report,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class TransferCostEngine:
    """异步 DB 版借调成本分摊引擎。"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    # ── 借调单 CRUD ─────────────────────────────────────────

    async def create_transfer(
        self,
        employee_id: str,
        employee_name: str,
        from_store_id: str,
        from_store_name: str,
        to_store_id: str,
        to_store_name: str,
        start_date: str,
        end_date: str,
        transfer_type: str = "temporary",
        reason: str = "",
    ) -> dict:
        """创建借调单并写入 DB。"""
        if from_store_id == to_store_id:
            raise ValueError("原门店与目标门店不能相同")

        parsed_start = date.fromisoformat(start_date)
        parsed_end = date.fromisoformat(end_date)
        if parsed_end < parsed_start:
            raise ValueError("结束日期不能早于开始日期")

        order_id = str(uuid4())
        now = datetime.now(tz=timezone.utc)

        await self.db.execute(
            text("""
                INSERT INTO store_transfer_orders
                    (id, tenant_id, employee_id, employee_name,
                     from_store_id, from_store_name, to_store_id, to_store_name,
                     transfer_type, start_date, end_date, status, reason,
                     created_at, updated_at)
                VALUES
                    (:id, :tid, :eid, :ename,
                     :fsid, :fsname, :tsid, :tsname,
                     :ttype, :sd, :ed, 'pending', :reason,
                     :now, :now)
            """),
            {
                "id": order_id,
                "tid": self.tenant_id,
                "eid": employee_id,
                "ename": employee_name,
                "fsid": from_store_id,
                "fsname": from_store_name,
                "tsid": to_store_id,
                "tsname": to_store_name,
                "ttype": transfer_type,
                "sd": parsed_start,
                "ed": parsed_end,
                "reason": reason,
                "now": now,
            },
        )
        await self.db.commit()

        log.info("transfer_created", order_id=order_id, employee_id=employee_id)

        return {
            "id": order_id,
            "employee_id": employee_id,
            "employee_name": employee_name,
            "from_store_id": from_store_id,
            "from_store_name": from_store_name,
            "to_store_id": to_store_id,
            "to_store_name": to_store_name,
            "transfer_type": transfer_type,
            "start_date": start_date,
            "end_date": end_date,
            "status": "pending",
            "reason": reason,
            "created_at": now.isoformat(),
        }

    async def get_transfer(self, order_id: str) -> Optional[dict]:
        """获取单个借调单详情。"""
        result = await self.db.execute(
            text("""
                SELECT id, employee_id, employee_name,
                       from_store_id, from_store_name,
                       to_store_id, to_store_name,
                       transfer_type, start_date, end_date,
                       status, reason, approved_by, approved_at,
                       created_at, updated_at
                FROM store_transfer_orders
                WHERE id = :oid AND is_deleted = FALSE
            """),
            {"oid": order_id},
        )
        row = result.mappings().first()
        if not row:
            return None
        return _row_to_dict(row)

    async def approve_transfer(self, order_id: str, approver_id: str) -> dict:
        """审批借调单：pending -> approved。"""
        order = await self.get_transfer(order_id)
        if not order:
            raise ValueError("借调单不存在")
        if order["status"] != "pending":
            raise ValueError(f"借调单状态为 {order['status']}，无法审批")

        now = datetime.now(tz=timezone.utc)
        await self.db.execute(
            text("""
                UPDATE store_transfer_orders
                SET status = 'approved', approved_by = :aid, approved_at = :now, updated_at = :now
                WHERE id = :oid
            """),
            {"oid": order_id, "aid": approver_id, "now": now},
        )
        await self.db.commit()
        log.info("transfer_approved", order_id=order_id, approver_id=approver_id)
        order["status"] = "approved"
        order["approved_by"] = approver_id
        order["approved_at"] = now.isoformat()
        return order

    async def activate_transfer(self, order_id: str) -> dict:
        """激活借调：approved -> active。"""
        order = await self.get_transfer(order_id)
        if not order:
            raise ValueError("借调单不存在")
        if order["status"] != "approved":
            raise ValueError(f"借调单状态为 {order['status']}，无法激活")

        now = datetime.now(tz=timezone.utc)
        await self.db.execute(
            text("UPDATE store_transfer_orders SET status = 'active', updated_at = :now WHERE id = :oid"),
            {"oid": order_id, "now": now},
        )
        await self.db.commit()
        order["status"] = "active"
        return order

    async def complete_transfer(self, order_id: str) -> dict:
        """完成借调：active -> completed。"""
        order = await self.get_transfer(order_id)
        if not order:
            raise ValueError("借调单不存在")
        if order["status"] != "active":
            raise ValueError(f"借调单状态为 {order['status']}，仅 active 状态可完成")

        now = datetime.now(tz=timezone.utc)
        await self.db.execute(
            text("UPDATE store_transfer_orders SET status = 'completed', updated_at = :now WHERE id = :oid"),
            {"oid": order_id, "now": now},
        )
        await self.db.commit()
        order["status"] = "completed"
        return order

    async def cancel_transfer(self, order_id: str) -> dict:
        """取消借调：pending/approved -> cancelled。"""
        order = await self.get_transfer(order_id)
        if not order:
            raise ValueError("借调单不存在")
        if order["status"] not in ("pending", "approved"):
            raise ValueError(f"借调单状态为 {order['status']}，无法取消")

        now = datetime.now(tz=timezone.utc)
        await self.db.execute(
            text("UPDATE store_transfer_orders SET status = 'cancelled', updated_at = :now WHERE id = :oid"),
            {"oid": order_id, "now": now},
        )
        await self.db.commit()
        order["status"] = "cancelled"
        return order

    async def list_transfers(
        self,
        store_id: Optional[str] = None,
        employee_id: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """列表查询借调单。"""
        conditions = ["is_deleted = FALSE"]
        params: Dict[str, Any] = {}

        if store_id:
            conditions.append("(from_store_id = :sid OR to_store_id = :sid)")
            params["sid"] = store_id
        if employee_id:
            conditions.append("employee_id = :eid")
            params["eid"] = employee_id
        if status:
            conditions.append("status = :status")
            params["status"] = status

        where = " AND ".join(conditions)

        count_result = await self.db.execute(
            text(f"SELECT COUNT(*) FROM store_transfer_orders WHERE {where}"),
            params,
        )
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset
        result = await self.db.execute(
            text(f"""
                SELECT id, employee_id, employee_name,
                       from_store_id, from_store_name,
                       to_store_id, to_store_name,
                       transfer_type, start_date, end_date,
                       status, reason, approved_by, approved_at,
                       created_at, updated_at
                FROM store_transfer_orders
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [_row_to_dict(r) for r in result.mappings().all()]

        return {"items": items, "total": total}

    # ── 成本分摊计算 ────────────────────────────────────────

    async def compute_monthly_allocation(
        self,
        employee_id: str,
        month: str,
        salary_data: Dict[str, int],
    ) -> dict:
        """计算某员工某月的工时拆分和成本分摊，结果写入 DB。

        Args:
            employee_id: 员工ID
            month: 月份 YYYY-MM
            salary_data: {"base_fen":, "overtime_fen":, "social_fen":, "bonus_fen":}

        Returns:
            {"time_split": ..., "cost_split": ..., "allocations_saved": N}
        """
        # 1. 查询该员工该月所有有效借调单
        month_start = f"{month}-01"
        # 计算月末
        year, mon = int(month[:4]), int(month[5:7])
        if mon == 12:
            next_month_start = f"{year + 1}-01-01"
        else:
            next_month_start = f"{year}-{mon + 1:02d}-01"

        transfers_result = await self.db.execute(
            text("""
                SELECT id, employee_id, from_store_id, to_store_id, start_date, end_date
                FROM store_transfer_orders
                WHERE employee_id = :eid
                  AND status IN ('active', 'completed', 'approved')
                  AND start_date < :month_end
                  AND (end_date IS NULL OR end_date >= :month_start)
                  AND is_deleted = FALSE
            """),
            {"eid": employee_id, "month_start": month_start, "month_end": next_month_start},
        )
        transfer_rows = transfers_result.mappings().all()
        transfers = [
            {
                "id": str(r["id"]),
                "employee_id": str(r["employee_id"]),
                "from_store_id": str(r["from_store_id"]),
                "to_store_id": str(r["to_store_id"]),
                "start_date": str(r["start_date"]),
                "end_date": str(r["end_date"]) if r["end_date"] else next_month_start,
            }
            for r in transfer_rows
        ]

        # 2. 查询该员工该月考勤记录
        attendance_result = await self.db.execute(
            text("""
                SELECT employee_id, clock_date::TEXT AS date,
                       COALESCE(worked_hours, 0) AS hours, store_id
                FROM attendance_records
                WHERE employee_id = :eid
                  AND clock_date >= :month_start
                  AND clock_date < :month_end
            """),
            {"eid": employee_id, "month_start": month_start, "month_end": next_month_start},
        )
        attendance_rows = attendance_result.mappings().all()
        attendance = [
            {
                "employee_id": str(r["employee_id"]),
                "date": str(r["date"]),
                "hours": float(r["hours"]),
                "store_id": str(r["store_id"]),
            }
            for r in attendance_rows
        ]

        # 3. 调用纯函数计算
        time_split = compute_time_split(transfers, attendance)
        cost_split = compute_cost_split(time_split, salary_data)

        # 4. 写入 transfer_cost_allocations
        # 先清除该员工该月旧记录
        await self.db.execute(
            text("""
                DELETE FROM transfer_cost_allocations
                WHERE tenant_id = :tid AND employee_id = :eid AND month = :month
            """),
            {"tid": self.tenant_id, "eid": employee_id, "month": month},
        )

        saved_count = 0
        emp_cost = cost_split.get(employee_id, {})
        emp_time = time_split.get(employee_id, {})

        # 确定关联的 transfer_order_id（取第一个匹配的借调单）
        transfer_order_id = transfers[0]["id"] if transfers else str(uuid4())

        for store_id, costs in emp_cost.items():
            alloc_id = str(uuid4())
            await self.db.execute(
                text("""
                    INSERT INTO transfer_cost_allocations
                        (id, tenant_id, transfer_order_id, employee_id, store_id, month,
                         worked_hours, wage_fen, social_insurance_fen, bonus_fen,
                         total_fen, ratio, created_at, updated_at)
                    VALUES
                        (:id, :tid, :toid, :eid, :sid, :month,
                         :hours, :wage, :social, :bonus,
                         :total, :ratio, NOW(), NOW())
                """),
                {
                    "id": alloc_id,
                    "tid": self.tenant_id,
                    "toid": transfer_order_id,
                    "eid": employee_id,
                    "sid": store_id,
                    "month": month,
                    "hours": emp_time.get(store_id, 0),
                    "wage": costs.get("wage_fen", 0),
                    "social": costs.get("social_fen", 0),
                    "bonus": costs.get("bonus_fen", 0),
                    "total": costs.get("total_fen", 0),
                    "ratio": costs.get("ratio", 0),
                },
            )
            saved_count += 1

        await self.db.commit()
        log.info(
            "monthly_allocation_computed",
            employee_id=employee_id,
            month=month,
            allocations=saved_count,
        )

        return {
            "time_split": time_split,
            "cost_split": cost_split,
            "allocations_saved": saved_count,
        }

    # ── 报表 ────────────────────────────────────────────────

    async def get_store_transfer_report(
        self,
        store_id: str,
        month: str,
        budget_data: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """门店维度的借调成本报表（三表合一）。"""
        # 查询该门店该月的所有成本分摊记录
        result = await self.db.execute(
            text("""
                SELECT ca.employee_id, ca.store_id, ca.worked_hours,
                       ca.wage_fen, ca.social_insurance_fen, ca.bonus_fen,
                       ca.total_fen, ca.ratio,
                       t.employee_name, t.from_store_id, t.from_store_name,
                       t.to_store_id, t.to_store_name
                FROM transfer_cost_allocations ca
                JOIN store_transfer_orders t ON ca.transfer_order_id = t.id
                WHERE ca.month = :month
                  AND (t.from_store_id = :sid OR t.to_store_id = :sid)
                  AND ca.is_deleted = FALSE
                  AND t.is_deleted = FALSE
            """),
            {"sid": store_id, "month": month},
        )
        rows = result.mappings().all()

        # 构建纯函数所需的数据结构
        employee_map: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            eid = str(r["employee_id"])
            sid = str(r["store_id"])
            if eid not in employee_map:
                employee_map[eid] = {
                    "employee_id": eid,
                    "employee_name": r["employee_name"],
                    "time_split": {},
                    "cost_split": {},
                }
            employee_map[eid]["time_split"][sid] = float(r["worked_hours"])
            employee_map[eid]["cost_split"][sid] = {
                "wage_fen": r["wage_fen"],
                "social_fen": r["social_insurance_fen"],
                "bonus_fen": r["bonus_fen"],
                "total_fen": r["total_fen"],
                "ratio": float(r["ratio"]),
            }

        # 明细表
        detail_reports = []
        for eid, emp in employee_map.items():
            detail = generate_detail_report(eid, emp["time_split"], emp["cost_split"])
            detail["employee_name"] = emp["employee_name"]
            detail_reports.append(detail)

        # 汇总表
        all_emp_cost = [{"employee_id": eid, "cost_split": emp["cost_split"]} for eid, emp in employee_map.items()]
        summary = generate_summary_report(all_emp_cost)

        # 分析表
        analysis = generate_cost_analysis_report(summary, budget_data or {})

        return {
            "month": month,
            "store_id": store_id,
            "detail": detail_reports,
            "summary": summary,
            "analysis": analysis,
        }


def _row_to_dict(row: Any) -> dict:
    """将 SQLAlchemy RowMapping 转为 dict，日期类型转 str。"""
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, (date, datetime)):
            d[k] = v.isoformat()
        elif hasattr(v, "hex"):  # UUID
            d[k] = str(v)
    return d
