"""加盟管理服务

核心职责：
- 加盟商 CRUD
- 门店分配（franchisee_stores 关联）
- 加盟商仪表盘（本月营业额、分润、累计欠款）
- 欠款预警（超阈值通知总部财务）
- 数据隔离：加盟商只能看自己 franchisee_stores 关联的门店
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import structlog

from ..models.franchise import (
    Franchisee,
    FranchiseeStatus,
    FranchiseeStore,
    RoyaltyBill,
    RoyaltyBillStatus,
    RoyaltyTier,
)
from .royalty_calculator import FranchiseeDashboard, RoyaltyCalculator

logger = structlog.get_logger(__name__)

# 累计欠款预警阈值（分）——超过此金额触发通知
OVERDUE_ALERT_THRESHOLD_FEN = 5_000_000  # 5万元


class RoyaltyReport:
    """月度特许权费用汇总报表"""

    def __init__(
        self,
        tenant_id: UUID,
        year: int,
        month: int,
        total_franchisees: int,
        billed_franchisees: int,
        total_revenue_fen: int,
        total_royalty_fen: int,
        total_management_fee_fen: int,
        total_due_fen: int,
        paid_fen: int,
        pending_fen: int,
        overdue_fen: int,
        items: List[Dict[str, Any]],
    ) -> None:
        self.tenant_id = tenant_id
        self.year = year
        self.month = month
        self.total_franchisees = total_franchisees
        self.billed_franchisees = billed_franchisees
        self.total_revenue_fen = total_revenue_fen
        self.total_royalty_fen = total_royalty_fen
        self.total_management_fee_fen = total_management_fee_fen
        self.total_due_fen = total_due_fen
        self.paid_fen = paid_fen
        self.pending_fen = pending_fen
        self.overdue_fen = overdue_fen
        self.items = items

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": str(self.tenant_id),
            "year": self.year,
            "month": self.month,
            "total_franchisees": self.total_franchisees,
            "billed_franchisees": self.billed_franchisees,
            "total_revenue_fen": self.total_revenue_fen,
            "total_royalty_fen": self.total_royalty_fen,
            "total_management_fee_fen": self.total_management_fee_fen,
            "total_due_fen": self.total_due_fen,
            "paid_fen": self.paid_fen,
            "pending_fen": self.pending_fen,
            "overdue_fen": self.overdue_fen,
            "items": self.items,
        }


class FranchiseService:
    """加盟管理服务（无状态，所有方法均为 async）"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  加盟商管理
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    async def create_franchisee(
        data: Dict[str, Any],
        tenant_id: UUID,
        db: Any,
    ) -> Franchisee:
        """创建加盟商档案。

        参数：
            data       — 加盟商字段（franchisee_name 必填）
            tenant_id  — 集团 tenant_id（显式传入，不从 session 读取）
            db         — 数据库连接

        返回已创建的 Franchisee 对象。
        """
        log = logger.bind(tenant_id=str(tenant_id))

        franchisee_name = data.get("franchisee_name", "").strip()
        if not franchisee_name:
            raise ValueError("franchisee_name 不能为空")

        tiers_raw: List[Dict[str, Any]] = data.get("royalty_tiers", [])
        tiers = [RoyaltyTier(**t) for t in tiers_raw]

        new_id = uuid4()
        franchisee = Franchisee(
            id=new_id,
            tenant_id=tenant_id,
            franchisee_name=franchisee_name,
            contact_name=data.get("contact_name"),
            contact_phone=data.get("contact_phone"),
            contract_start=data.get("contract_start"),
            contract_end=data.get("contract_end"),
            royalty_rate=float(data.get("royalty_rate", 0.05)),
            royalty_tiers=tiers,
            status=FranchiseeStatus.ACTIVE,
        )

        if db is not None:
            await db.execute(
                """
                INSERT INTO franchisees (
                    id, tenant_id, name, contact_name, contact_phone,
                    contact_email, region,
                    contract_start, contract_end,
                    royalty_rate, royalty_tiers,
                    management_fee_fen, brand_usage_fee_fen,
                    status, created_at
                ) VALUES (
                    :id, :tenant_id, :name, :contact_name, :contact_phone,
                    :contact_email, :region,
                    :contract_start, :contract_end,
                    :royalty_rate, :royalty_tiers,
                    :management_fee_fen, :brand_usage_fee_fen,
                    'active', NOW()
                )
                """,
                {
                    "id": str(new_id),
                    "tenant_id": str(tenant_id),
                    "name": franchisee_name,
                    "contact_name": data.get("contact_name"),
                    "contact_phone": data.get("contact_phone"),
                    "contact_email": data.get("contact_email"),
                    "region": data.get("region"),
                    "contract_start": data.get("contract_start"),
                    "contract_end": data.get("contract_end"),
                    "royalty_rate": float(data.get("royalty_rate", 0.05)),
                    "royalty_tiers": [t.model_dump() for t in tiers],
                    "management_fee_fen": int(data.get("management_fee_fen", 0)),
                    "brand_usage_fee_fen": int(data.get("brand_usage_fee_fen", 0)),
                },
            )

        log.info("franchise.create_franchisee", franchisee_id=str(new_id))
        return franchisee

    @staticmethod
    async def list_franchisees(
        tenant_id: UUID,
        db: Any,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        """总部视角：查询加盟商列表（支持按状态过滤、分页）。"""
        if db is None:
            return {"items": [], "total": 0, "page": page, "size": size}

        offset = (page - 1) * size
        params: Dict[str, Any] = {"tenant_id": str(tenant_id), "limit": size, "offset": offset}
        status_clause = ""
        if status:
            status_clause = "AND status = :status"
            params["status"] = status

        rows = await db.fetch_all(
            f"""
            SELECT id, tenant_id, name AS franchisee_name,
                   contact_name, contact_phone, contact_email, region,
                   status, contract_start, contract_end,
                   royalty_rate, royalty_tiers,
                   management_fee_fen, brand_usage_fee_fen, created_at
              FROM franchisees
             WHERE tenant_id = :tenant_id
               {status_clause}
             ORDER BY name
             LIMIT :limit OFFSET :offset
            """,
            params,
        )
        count_row = await db.fetch_one(
            f"""
            SELECT COUNT(*) AS total
              FROM franchisees
             WHERE tenant_id = :tenant_id
               {status_clause}
            """,
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = int(count_row["total"]) if count_row else 0
        items = [dict(row) for row in rows]
        return {"items": items, "total": total, "page": page, "size": size}

    @staticmethod
    async def get_franchisee(
        franchisee_id: UUID,
        tenant_id: UUID,
        db: Any,
    ) -> Optional[Franchisee]:
        """按 ID 查询加盟商（需校验 tenant_id 归属）。"""
        if db is None:
            return None
        row = await db.fetch_one(
            """
            SELECT id, tenant_id, name AS franchisee_name,
                   contact_name, contact_phone,
                   contract_start, contract_end,
                   royalty_rate, royalty_tiers,
                   management_fee_fen, status, created_at
              FROM franchisees
             WHERE id = :franchisee_id
               AND tenant_id = :tenant_id
            """,
            {"franchisee_id": str(franchisee_id), "tenant_id": str(tenant_id)},
        )
        if not row:
            return None
        f = Franchisee(
            id=row["id"],
            tenant_id=row["tenant_id"],
            franchisee_name=row["franchisee_name"],
            contact_name=row["contact_name"],
            contact_phone=row["contact_phone"],
            contract_start=row["contract_start"],
            contract_end=row["contract_end"],
            royalty_rate=float(row["royalty_rate"]),
            royalty_tiers=row["royalty_tiers"] or [],
            status=row["status"],
            created_at=row["created_at"],
        )
        object.__setattr__(f, "management_fee_fen", row["management_fee_fen"] or 0)
        return f

    @staticmethod
    async def update_franchisee_status(
        franchisee_id: UUID,
        tenant_id: UUID,
        new_status: str,
        db: Any,
    ) -> Franchisee:
        """更新加盟商状态（active / suspended / terminated）。"""
        log = logger.bind(
            tenant_id=str(tenant_id),
            franchisee_id=str(franchisee_id),
            new_status=new_status,
        )

        allowed = {FranchiseeStatus.ACTIVE, FranchiseeStatus.SUSPENDED, FranchiseeStatus.TERMINATED}
        if new_status not in allowed:
            raise ValueError(f"无效状态：{new_status}，允许值：{allowed}")

        franchisee = await FranchiseService.get_franchisee(franchisee_id, tenant_id, db)
        if franchisee is None:
            raise ValueError(f"加盟商 {franchisee_id} 不存在或无权限")

        if db is not None:
            await db.execute(
                """
                UPDATE franchisees
                   SET status = :status
                 WHERE id = :franchisee_id
                   AND tenant_id = :tenant_id
                """,
                {
                    "status": new_status,
                    "franchisee_id": str(franchisee_id),
                    "tenant_id": str(tenant_id),
                },
            )

        franchisee.status = new_status
        log.info("franchise.update_status")
        return franchisee

    @staticmethod
    async def update_franchisee(
        franchisee_id: UUID,
        tenant_id: UUID,
        data: Dict[str, Any],
        db: Any,
    ) -> Franchisee:
        """更新加盟商基本信息（联系人/合同期/费率等）。"""
        log = logger.bind(tenant_id=str(tenant_id), franchisee_id=str(franchisee_id))

        franchisee = await FranchiseService.get_franchisee(franchisee_id, tenant_id, db)
        if franchisee is None:
            raise ValueError(f"加盟商 {franchisee_id} 不存在或无权限")

        updatable = {
            "name": data.get("franchisee_name"),
            "contact_name": data.get("contact_name"),
            "contact_phone": data.get("contact_phone"),
            "contact_email": data.get("contact_email"),
            "region": data.get("region"),
            "contract_start": data.get("contract_start"),
            "contract_end": data.get("contract_end"),
            "royalty_rate": data.get("royalty_rate"),
            "management_fee_fen": data.get("management_fee_fen"),
            "brand_usage_fee_fen": data.get("brand_usage_fee_fen"),
        }
        set_clauses = []
        params: Dict[str, Any] = {
            "franchisee_id": str(franchisee_id),
            "tenant_id": str(tenant_id),
        }
        for col, val in updatable.items():
            if val is not None:
                set_clauses.append(f"{col} = :{col}")
                params[col] = val

        if set_clauses and db is not None:
            await db.execute(
                f"UPDATE franchisees SET {', '.join(set_clauses)} WHERE id = :franchisee_id AND tenant_id = :tenant_id",
                params,
            )

        # 重新查询最新状态
        updated = await FranchiseService.get_franchisee(franchisee_id, tenant_id, db)
        if updated is None:
            raise ValueError(f"更新后查询加盟商 {franchisee_id} 失败")
        log.info("franchise.update_franchisee")
        return updated

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  门店分配
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    async def assign_store(
        franchisee_id: UUID,
        store_id: UUID,
        tenant_id: UUID,
        db: Any,
        join_date: Optional[date] = None,
        initial_fee_fen: int = 0,
    ) -> FranchiseeStore:
        """将门店分配给加盟商。

        一个门店只能归属于一个加盟商（UNIQUE(tenant_id, store_id)）。
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            franchisee_id=str(franchisee_id),
            store_id=str(store_id),
        )

        franchisee = await FranchiseService.get_franchisee(franchisee_id, tenant_id, db)
        if franchisee is None:
            raise ValueError(f"加盟商 {franchisee_id} 不存在或无权限")

        effective_join_date = join_date or date.today()
        new_id = uuid4()
        link = FranchiseeStore(
            id=new_id,
            tenant_id=tenant_id,
            franchisee_id=franchisee_id,
            store_id=store_id,
            joined_at=effective_join_date,
        )

        if db is not None:
            await db.execute(
                """
                INSERT INTO franchisee_stores (
                    id, tenant_id, franchisee_id, store_id,
                    join_date, initial_fee_fen, status, created_at
                ) VALUES (
                    :id, :tenant_id, :franchisee_id, :store_id,
                    :join_date, :initial_fee_fen, 'active', NOW()
                )
                ON CONFLICT (tenant_id, store_id) DO NOTHING
                """,
                {
                    "id": str(new_id),
                    "tenant_id": str(tenant_id),
                    "franchisee_id": str(franchisee_id),
                    "store_id": str(store_id),
                    "join_date": effective_join_date,
                    "initial_fee_fen": initial_fee_fen,
                },
            )

        log.info("franchise.assign_store")
        return link

    @staticmethod
    async def list_franchisee_stores(
        tenant_id: UUID,
        franchisee_id: UUID,
        db: Any,
    ) -> List[Dict[str, Any]]:
        """查询加盟商旗下门店列表（含运营数据）。"""
        if db is None:
            return []

        rows = await db.fetch_all(
            """
            SELECT fs.id, fs.tenant_id, fs.franchisee_id, fs.store_id,
                   fs.join_date, fs.initial_fee_fen, fs.status, fs.created_at
              FROM franchisee_stores fs
             WHERE fs.tenant_id = :tenant_id
               AND fs.franchisee_id = :franchisee_id
             ORDER BY fs.join_date DESC
            """,
            {"tenant_id": str(tenant_id), "franchisee_id": str(franchisee_id)},
        )
        return [dict(row) for row in rows]

    @staticmethod
    async def get_franchisee_store_ids(
        franchisee_id: UUID,
        tenant_id: UUID,
        db: Any,
    ) -> List[UUID]:
        """获取加盟商关联的所有门店 ID（数据隔离过滤入口）。"""
        if db is None:
            return []
        rows = await db.fetch_all(
            """
            SELECT store_id
              FROM franchisee_stores
             WHERE franchisee_id = :franchisee_id
               AND tenant_id = :tenant_id
               AND status = 'active'
            """,
            {"franchisee_id": str(franchisee_id), "tenant_id": str(tenant_id)},
        )
        return [UUID(str(row["store_id"])) for row in rows]

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  加盟商仪表盘
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    async def get_franchisee_dashboard(
        franchisee_id: UUID,
        tenant_id: UUID,
        db: Any,
    ) -> Dict[str, Any]:
        """加盟商仪表盘：本月营业额、本月分润、累计欠款。"""
        dashboard: FranchiseeDashboard = await RoyaltyCalculator.get_franchisee_dashboard(
            tenant_id=tenant_id,
            franchisee_id=franchisee_id,
            db=db,
        )
        return dashboard.to_dict()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  账单管理
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    async def create_royalty_bill_batch(
        tenant_id: UUID,
        year: int,
        month: int,
        db: Any,
    ) -> Dict[str, Any]:
        """批量生成当月所有活跃加盟商的特许权费用账单。"""
        bill_month = f"{year:04d}-{month:02d}"
        bills = await RoyaltyCalculator.generate_monthly_bills(
            tenant_id=tenant_id,
            bill_month=bill_month,
            db=db,
        )
        return {
            "bill_month": bill_month,
            "generated": len(bills),
            "bills": [b.to_dict() for b in bills],
        }

    @staticmethod
    async def get_royalty_report(
        tenant_id: UUID,
        year: int,
        month: int,
        db: Any,
    ) -> RoyaltyReport:
        """月度特许权费用汇总报表。"""
        bill_month = f"{year:04d}-{month:02d}"
        import calendar as _cal

        period_start = date(year, month, 1)
        period_end = date(year, month, _cal.monthrange(year, month)[1])

        # 活跃加盟商总数
        total_franchisees = 0
        if db is not None:
            row = await db.fetch_one(
                "SELECT COUNT(*) AS cnt FROM franchisees WHERE tenant_id = :tenant_id AND status = 'active'",
                {"tenant_id": str(tenant_id)},
            )
            total_franchisees = int(row["cnt"]) if row else 0

        # 本月账单汇总
        items: List[Dict[str, Any]] = []
        total_revenue_fen = 0
        total_royalty_fen = 0
        total_management_fee_fen = 0
        total_due_fen = 0
        paid_fen = 0
        pending_fen = 0
        overdue_fen = 0
        billed_franchisees = 0

        if db is not None:
            rows = await db.fetch_all(
                """
                SELECT rb.id, rb.franchisee_id, f.name AS franchisee_name,
                       rb.revenue_fen, rb.royalty_amount_fen, rb.management_fee_fen,
                       rb.total_due_fen, rb.status, rb.due_date, rb.paid_at
                  FROM royalty_bills rb
                  JOIN franchisees f ON f.id = rb.franchisee_id
                 WHERE rb.tenant_id = :tenant_id
                   AND rb.period_start = :period_start
                   AND rb.period_end = :period_end
                 ORDER BY f.name
                """,
                {
                    "tenant_id": str(tenant_id),
                    "period_start": period_start,
                    "period_end": period_end,
                },
            )
            billed_franchisees = len(rows)
            for row in rows:
                total_revenue_fen += row["revenue_fen"] or 0
                total_royalty_fen += row["royalty_amount_fen"] or 0
                total_management_fee_fen += row["management_fee_fen"] or 0
                due = row["total_due_fen"] or 0
                total_due_fen += due
                if row["status"] == "paid":
                    paid_fen += due
                elif row["status"] == "overdue":
                    overdue_fen += due
                else:
                    pending_fen += due
                items.append(dict(row))

        return RoyaltyReport(
            tenant_id=tenant_id,
            year=year,
            month=month,
            total_franchisees=total_franchisees,
            billed_franchisees=billed_franchisees,
            total_revenue_fen=total_revenue_fen,
            total_royalty_fen=total_royalty_fen,
            total_management_fee_fen=total_management_fee_fen,
            total_due_fen=total_due_fen,
            paid_fen=paid_fen,
            pending_fen=pending_fen,
            overdue_fen=overdue_fen,
            items=items,
        )

    @staticmethod
    async def list_bills(
        tenant_id: UUID,
        db: Any,
        franchisee_id: Optional[UUID] = None,
        status: Optional[str] = None,
        year: Optional[int] = None,
        month: Optional[int] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        """账单列表（支持按加盟商/状态/月份过滤，分页）。"""
        if db is None:
            return {"items": [], "total": 0, "page": page, "size": size}

        offset = (page - 1) * size
        conditions = ["rb.tenant_id = :tenant_id"]
        params: Dict[str, Any] = {"tenant_id": str(tenant_id), "limit": size, "offset": offset}

        if franchisee_id:
            conditions.append("rb.franchisee_id = :franchisee_id")
            params["franchisee_id"] = str(franchisee_id)
        if status:
            conditions.append("rb.status = :status")
            params["status"] = status
        if year and month:
            import calendar as _cal

            params["period_start"] = date(year, month, 1)
            params["period_end"] = date(year, month, _cal.monthrange(year, month)[1])
            conditions.append("rb.period_start = :period_start AND rb.period_end = :period_end")

        where = " AND ".join(conditions)
        rows = await db.fetch_all(
            f"""
            SELECT rb.id, rb.tenant_id, rb.franchisee_id, f.name AS franchisee_name,
                   rb.period_start, rb.period_end,
                   rb.revenue_fen, rb.royalty_rate, rb.royalty_amount_fen,
                   rb.management_fee_fen, rb.total_due_fen,
                   rb.status, rb.due_date, rb.paid_at, rb.created_at
              FROM royalty_bills rb
              JOIN franchisees f ON f.id = rb.franchisee_id
             WHERE {where}
             ORDER BY rb.period_start DESC, f.name
             LIMIT :limit OFFSET :offset
            """,
            params,
        )
        count_row = await db.fetch_one(
            f"SELECT COUNT(*) AS total FROM royalty_bills rb WHERE {where}",
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = int(count_row["total"]) if count_row else 0
        return {"items": [dict(r) for r in rows], "total": total, "page": page, "size": size}

    @staticmethod
    async def get_bill(bill_id: UUID, tenant_id: UUID, db: Any) -> Optional[RoyaltyBill]:
        """按 ID 查询账单（需校验 tenant_id 归属）。"""
        if db is None:
            return None
        row = await db.fetch_one(
            """
            SELECT id, tenant_id, franchisee_id,
                   period_start, period_end,
                   revenue_fen, royalty_rate, royalty_amount_fen,
                   management_fee_fen, total_due_fen,
                   status, due_date, paid_at, created_at
              FROM royalty_bills
             WHERE id = :bill_id
               AND tenant_id = :tenant_id
            """,
            {"bill_id": str(bill_id), "tenant_id": str(tenant_id)},
        )
        if not row:
            return None
        period_start: date = row["period_start"]
        bill_month = period_start.strftime("%Y-%m")
        revenue_fen = row["revenue_fen"] or 0
        royalty_fen = row["royalty_amount_fen"] or 0
        return RoyaltyBill(
            id=row["id"],
            tenant_id=row["tenant_id"],
            franchisee_id=row["franchisee_id"],
            bill_month=bill_month,
            total_revenue=revenue_fen / 100.0,
            royalty_amount=royalty_fen / 100.0,
            status=row["status"],
            due_date=row["due_date"],
            paid_at=row["paid_at"],
            created_at=row["created_at"],
        )

    @staticmethod
    async def mark_bill_paid(
        bill_id: UUID,
        tenant_id: UUID,
        db: Any,
    ) -> RoyaltyBill:
        """标记账单已付款（pending/overdue → paid）。"""
        log = logger.bind(tenant_id=str(tenant_id), bill_id=str(bill_id))

        bill = await FranchiseService.get_bill(bill_id, tenant_id, db)
        if bill is None:
            raise ValueError(f"账单 {bill_id} 不存在或无权限")

        if bill.status not in (RoyaltyBillStatus.PENDING, RoyaltyBillStatus.OVERDUE):
            raise ValueError(f"只有 pending/overdue 状态可标记付款，当前状态：{bill.status}")

        if db is not None:
            await db.execute(
                """
                UPDATE royalty_bills
                   SET status = 'paid', paid_at = NOW()
                 WHERE id = :bill_id
                   AND tenant_id = :tenant_id
                """,
                {"bill_id": str(bill_id), "tenant_id": str(tenant_id)},
            )

        bill.status = RoyaltyBillStatus.PAID
        bill.paid_at = datetime.now()
        log.info("franchise.bill_paid")
        return bill

    @staticmethod
    async def check_overdue_bills(
        tenant_id: UUID,
        db: Any,
    ) -> int:
        """检查并标记逾期账单（due_date < today，status=pending → overdue）。

        返回已标记条数。
        """
        from datetime import date as _date

        cutoff = _date.today()
        return await RoyaltyCalculator.mark_overdue_bills(tenant_id, cutoff, db)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  巡店审计
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    async def create_audit(
        tenant_id: UUID,
        data: Dict[str, Any],
        db: Any,
    ) -> Dict[str, Any]:
        """新建巡店审计记录。"""
        log = logger.bind(tenant_id=str(tenant_id))

        franchisee_id_str = data.get("franchisee_id")
        store_id_str = data.get("store_id")
        audit_date_val = data.get("audit_date") or date.today()

        if not franchisee_id_str:
            raise ValueError("franchisee_id 不能为空")
        if not store_id_str:
            raise ValueError("store_id 不能为空")

        new_id = uuid4()
        record = {
            "id": str(new_id),
            "tenant_id": str(tenant_id),
            "franchisee_id": str(franchisee_id_str),
            "store_id": str(store_id_str),
            "audit_date": audit_date_val,
            "score": data.get("score"),
            "findings": data.get("findings", {}),
            "auditor_id": data.get("auditor_id"),
        }

        if db is not None:
            await db.execute(
                """
                INSERT INTO franchise_audits (
                    id, tenant_id, franchisee_id, store_id,
                    audit_date, score, findings, auditor_id, created_at
                ) VALUES (
                    :id, :tenant_id, :franchisee_id, :store_id,
                    :audit_date, :score, :findings, :auditor_id, NOW()
                )
                """,
                record,
            )

        log.info("franchise.create_audit", audit_id=str(new_id))
        return record

    @staticmethod
    async def list_audits(
        tenant_id: UUID,
        db: Any,
        franchisee_id: Optional[UUID] = None,
        store_id: Optional[UUID] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        """巡店审计列表（支持按加盟商/门店过滤，分页）。"""
        if db is None:
            return {"items": [], "total": 0, "page": page, "size": size}

        offset = (page - 1) * size
        conditions = ["fa.tenant_id = :tenant_id"]
        params: Dict[str, Any] = {"tenant_id": str(tenant_id), "limit": size, "offset": offset}

        if franchisee_id:
            conditions.append("fa.franchisee_id = :franchisee_id")
            params["franchisee_id"] = str(franchisee_id)
        if store_id:
            conditions.append("fa.store_id = :store_id")
            params["store_id"] = str(store_id)

        where = " AND ".join(conditions)
        rows = await db.fetch_all(
            f"""
            SELECT fa.id, fa.tenant_id, fa.franchisee_id, f.name AS franchisee_name,
                   fa.store_id, fa.audit_date, fa.score, fa.findings,
                   fa.auditor_id, fa.created_at
              FROM franchise_audits fa
              JOIN franchisees f ON f.id = fa.franchisee_id
             WHERE {where}
             ORDER BY fa.audit_date DESC, fa.created_at DESC
             LIMIT :limit OFFSET :offset
            """,
            params,
        )
        count_row = await db.fetch_one(
            f"SELECT COUNT(*) AS total FROM franchise_audits fa WHERE {where}",
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = int(count_row["total"]) if count_row else 0
        return {"items": [dict(r) for r in rows], "total": total, "page": page, "size": size}

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  欠款预警
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    async def check_overdue_alerts(
        tenant_id: UUID,
        db: Any,
        threshold: float = OVERDUE_ALERT_THRESHOLD_FEN / 100.0,
    ) -> List[Dict[str, Any]]:
        """欠款预警：累计欠款超阈值的加盟商列表，供总部财务处理。

        返回需要预警的加盟商列表，每项包含：
          franchisee_id, franchisee_name, total_overdue_fen, bill_count
        """
        log = logger.bind(tenant_id=str(tenant_id), threshold=threshold)

        if db is None:
            return []

        threshold_fen = int(threshold * 100)
        rows = await db.fetch_all(
            """
            SELECT f.id AS franchisee_id,
                   f.name AS franchisee_name,
                   SUM(b.total_due_fen) AS total_overdue_fen,
                   COUNT(*) AS bill_count
              FROM royalty_bills b
              JOIN franchisees f ON f.id = b.franchisee_id
             WHERE b.tenant_id = :tenant_id
               AND b.status IN ('pending', 'overdue')
             GROUP BY f.id, f.name
            HAVING SUM(b.total_due_fen) > :threshold_fen
             ORDER BY total_overdue_fen DESC
            """,
            {"tenant_id": str(tenant_id), "threshold_fen": threshold_fen},
        )

        alerts = [
            {
                "franchisee_id": str(row["franchisee_id"]),
                "franchisee_name": row["franchisee_name"],
                "total_overdue_fen": int(row["total_overdue_fen"]),
                "bill_count": int(row["bill_count"]),
            }
            for row in rows
        ]
        log.info("franchise.check_overdue_alerts", alert_count=len(alerts))
        return alerts

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  私有辅助（保留旧接口兼容性）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    async def _sum_unpaid_bills(
        franchisee_id: UUID,
        tenant_id: UUID,
        db: Any,
    ) -> float:
        """汇总加盟商未付账单总金额（pending + overdue），返回元。"""
        fen = await RoyaltyCalculator._sum_pending_due_fen(franchisee_id, tenant_id, db)
        return fen / 100.0
