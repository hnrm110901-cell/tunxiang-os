"""加盟管理服务

核心职责：
- 加盟商 CRUD
- 门店分配（franchise_stores 关联）
- 加盟商仪表盘（本月营业额、分润、累计欠款）
- 欠款预警（超阈值通知总部财务）
- 数据隔离：加盟商只能看自己 franchisee_stores 关联的门店
"""

from __future__ import annotations

import structlog
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from ..models.franchise import (
    Franchisee,
    FranchiseeStatus,
    FranchiseeStore,
    RoyaltyBill,
    RoyaltyBillStatus,
    RoyaltyTier,
)
from .royalty_calculator import RoyaltyCalculator

logger = structlog.get_logger(__name__)

# 累计欠款预警阈值（元）——超过此金额触发通知
OVERDUE_ALERT_THRESHOLD = 50_000.0


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
        """创建加盟商。

        参数：
            data       — 加盟商字段（franchisee_name 必填）
            tenant_id  — 集团 tenant_id（显式传入，不从 session 读取）
            db         — 数据库会话

        返回已创建的 Franchisee 对象。
        """
        log = logger.bind(tenant_id=str(tenant_id))

        franchisee_name = data.get("franchisee_name", "").strip()
        if not franchisee_name:
            raise ValueError("franchisee_name 不能为空")

        # 构建阶梯分润
        tiers_raw: List[Dict[str, Any]] = data.get("royalty_tiers", [])
        tiers = [RoyaltyTier(**t) for t in tiers_raw]

        franchisee = Franchisee(
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

        # TODO: INSERT INTO franchisees ...（真实 DB 写入）
        log.info("franchise.create_franchisee", franchisee_id=str(franchisee.id))
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
        # TODO: SELECT * FROM franchisees WHERE tenant_id = :tenant_id [AND status = :status]
        return {"items": [], "total": 0, "page": page, "size": size}

    @staticmethod
    async def get_franchisee(
        franchisee_id: UUID,
        tenant_id: UUID,
        db: Any,
    ) -> Optional[Franchisee]:
        """按 ID 查询加盟商（需校验 tenant_id 归属）。"""
        # TODO: SELECT * FROM franchisees WHERE id = :franchisee_id AND tenant_id = :tenant_id
        return None

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  门店分配（数据隔离核心）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    async def assign_store(
        franchisee_id: UUID,
        store_id: UUID,
        tenant_id: UUID,
        db: Any,
    ) -> FranchiseeStore:
        """将门店分配给加盟商。

        一个门店只能归属于一个加盟商（UNIQUE(tenant_id, store_id)）。
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            franchisee_id=str(franchisee_id),
            store_id=str(store_id),
        )

        # 校验加盟商存在且属于本 tenant
        # TODO: 从 DB 查询加盟商
        # franchisee = await FranchiseService.get_franchisee(franchisee_id, tenant_id, db)
        # if franchisee is None:
        #     raise ValueError(f"加盟商 {franchisee_id} 不存在或无权限")

        link = FranchiseeStore(
            tenant_id=tenant_id,
            franchisee_id=franchisee_id,
            store_id=store_id,
            joined_at=date.today(),
        )

        # TODO: INSERT INTO franchisee_stores ...（需处理 UNIQUE 冲突）
        log.info("franchise.assign_store")
        return link

    @staticmethod
    async def get_franchisee_store_ids(
        franchisee_id: UUID,
        tenant_id: UUID,
        db: Any,
    ) -> List[UUID]:
        """获取加盟商关联的所有门店 ID（数据隔离过滤入口）。

        所有加盟商视角的数据查询必须先调用此方法获取允许访问的 store_id 列表，
        再以此列表过滤业务数据，确保不泄露其他加盟商的门店数据。
        """
        # TODO: SELECT store_id FROM franchisee_stores
        #       WHERE franchisee_id = :franchisee_id AND tenant_id = :tenant_id
        return []

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  加盟商仪表盘
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    async def get_franchisee_dashboard(
        franchisee_id: UUID,
        tenant_id: UUID,
        db: Any,
    ) -> Dict[str, Any]:
        """加盟商仪表盘：本月营业额、本月分润、累计欠款。

        数据隔离：营业额汇总只涉及 franchisee_stores 关联的门店。
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            franchisee_id=str(franchisee_id),
        )

        # 当前月份
        today = date.today()
        current_month = today.strftime("%Y-%m")

        # 获取允许访问的门店 ID（数据隔离）
        store_ids = await FranchiseService.get_franchisee_store_ids(
            franchisee_id, tenant_id, db
        )

        # 本月营业额（模拟；实际跨域调用 tx-finance）
        current_revenue: float = 0.0
        # TODO: SUM(revenue) FROM store_monthly_revenue
        #       WHERE store_id = ANY(:store_ids) AND month = :current_month

        # 获取加盟商配置（模拟）
        franchisee = await FranchiseService.get_franchisee(franchisee_id, tenant_id, db)

        # 本月分润
        current_royalty: float = 0.0
        if franchisee:
            current_royalty = RoyaltyCalculator.calculate(current_revenue, franchisee)

        # 累计欠款（pending + overdue 账单合计）
        total_overdue: float = await FranchiseService._sum_unpaid_bills(
            franchisee_id, tenant_id, db
        )

        log.info(
            "franchise.dashboard",
            current_revenue=current_revenue,
            current_royalty=current_royalty,
            total_overdue=total_overdue,
        )

        return {
            "franchisee_id": str(franchisee_id),
            "current_month": current_month,
            "store_count": len(store_ids),
            "current_revenue": current_revenue,
            "current_royalty": current_royalty,
            "total_overdue": total_overdue,
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  账单管理
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    async def list_bills(
        tenant_id: UUID,
        db: Any,
        franchisee_id: Optional[UUID] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        """账单列表（支持按加盟商过滤）。"""
        # TODO: SELECT * FROM royalty_bills WHERE tenant_id = :tenant_id
        #       [AND franchisee_id = :franchisee_id] ORDER BY bill_month DESC
        return {"items": [], "total": 0, "page": page, "size": size}

    @staticmethod
    async def get_bill(bill_id: UUID, tenant_id: UUID, db: Any) -> Optional[RoyaltyBill]:
        """按 ID 查询账单（需校验 tenant_id 归属）。"""
        # TODO: SELECT * FROM royalty_bills WHERE id = :bill_id AND tenant_id = :tenant_id
        return None

    @staticmethod
    async def confirm_bill(
        bill_id: UUID,
        tenant_id: UUID,
        db: Any,
    ) -> RoyaltyBill:
        """总部确认账单（pending → confirmed）。"""
        log = logger.bind(tenant_id=str(tenant_id), bill_id=str(bill_id))

        bill = await FranchiseService.get_bill(bill_id, tenant_id, db)
        if bill is None:
            raise ValueError(f"账单 {bill_id} 不存在或无权限")

        bill.confirm()
        # TODO: UPDATE royalty_bills SET status = 'confirmed' WHERE id = :bill_id
        log.info("franchise.bill_confirmed")
        return bill

    @staticmethod
    async def mark_bill_paid(
        bill_id: UUID,
        tenant_id: UUID,
        db: Any,
    ) -> RoyaltyBill:
        """标记账单已付款（confirmed/overdue → paid）。"""
        log = logger.bind(tenant_id=str(tenant_id), bill_id=str(bill_id))

        bill = await FranchiseService.get_bill(bill_id, tenant_id, db)
        if bill is None:
            raise ValueError(f"账单 {bill_id} 不存在或无权限")

        bill.mark_paid()
        # TODO: UPDATE royalty_bills SET status = 'paid', paid_at = NOW() WHERE id = :bill_id
        log.info("franchise.bill_paid")
        return bill

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  欠款预警
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    async def check_overdue_alerts(
        tenant_id: UUID,
        db: Any,
        threshold: float = OVERDUE_ALERT_THRESHOLD,
    ) -> List[Dict[str, Any]]:
        """欠款预警：累计欠款超阈值的加盟商列表，供总部财务处理。

        返回需要预警的加盟商列表，每项包含：
          franchisee_id, franchisee_name, total_overdue, bill_count
        """
        log = logger.bind(tenant_id=str(tenant_id), threshold=threshold)

        # TODO: 实际查询逻辑：
        # SELECT f.id, f.franchisee_name,
        #        SUM(b.royalty_amount) AS total_overdue,
        #        COUNT(*) AS bill_count
        # FROM royalty_bills b
        # JOIN franchisees f ON f.id = b.franchisee_id
        # WHERE b.tenant_id = :tenant_id
        #   AND b.status IN ('pending', 'overdue')
        # GROUP BY f.id, f.franchisee_name
        # HAVING SUM(b.royalty_amount) > :threshold

        alerts: List[Dict[str, Any]] = []
        log.info("franchise.check_overdue_alerts", alert_count=len(alerts))
        return alerts

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  私有辅助
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    async def _sum_unpaid_bills(
        franchisee_id: UUID,
        tenant_id: UUID,
        db: Any,
    ) -> float:
        """汇总加盟商未付账单总金额（pending + overdue）。"""
        # TODO: SELECT SUM(royalty_amount) FROM royalty_bills
        #       WHERE franchisee_id = :franchisee_id AND tenant_id = :tenant_id
        #         AND status IN ('pending', 'overdue')
        return 0.0
