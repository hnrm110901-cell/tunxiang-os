"""加盟商财务结算服务

核心职责：
1. 月结算单生成（汇总营业额 → royalty_calculator → 生成 draft 结算单）
2. 结算单状态机：draft → sent → confirmed → paid
3. 逾期预警（超期 N 天未付款的 confirmed 结算单）
4. 加盟商对账报表（近 N 个月汇总）

状态机（严格单向，不可逆）：
    draft  ──send()──▶  sent  ──confirm()──▶  confirmed  ──pay()──▶  paid
                         ▲                        ▲                    ▲
                         │                        │                    │
                    只有 draft 才能                只有 sent 才能       只有 confirmed
                    进入此状态                    进入此状态           才能进入此状态
"""

from __future__ import annotations

import calendar
import os

import httpx
import structlog
from datetime import date, datetime, timedelta
from typing import Any, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from ..models.franchise import Franchisee, FranchiseeStatus, RoyaltyTier
from .royalty_calculator import RoyaltyCalculator

logger = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  状态常量与异常
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class SettlementStatus:
    DRAFT = "draft"
    SENT = "sent"
    CONFIRMED = "confirmed"
    PAID = "paid"

    # 已锁定（不可修改金额）的状态
    FINALIZED = {SENT, CONFIRMED, PAID}

    # 合法的状态转换映射
    ALLOWED_TRANSITIONS: dict[str, str] = {
        DRAFT: SENT,
        SENT: CONFIRMED,
        CONFIRMED: PAID,
    }


class InvalidStatusTransitionError(ValueError):
    """不合法的状态转换"""

    def __init__(self, current: str, target: str) -> None:
        allowed = SettlementStatus.ALLOWED_TRANSITIONS.get(current)
        msg = (
            f"结算单状态 {current!r} 不能转换为 {target!r}。"
            f"当前状态允许的下一状态：{allowed!r}"
        )
        super().__init__(msg)


class SettlementAlreadyFinalizedError(ValueError):
    """结算单已锁定，不可修改金额"""

    def __init__(self, settlement_id: str, status: str) -> None:
        super().__init__(
            f"结算单 {settlement_id} 状态为 {status!r}（已锁定），金额不可修改"
        )


class SettlementNotFoundError(LookupError):
    """结算单不存在"""

    def __init__(self, settlement_id: str) -> None:
        super().__init__(f"结算单 {settlement_id!r} 不存在或无访问权限")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  数据模型（Pydantic V2）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class FranchiseSettlementItem(BaseModel):
    """结算单费用明细条目"""

    id: UUID = Field(default_factory=uuid4)
    settlement_id: UUID
    item_type: str = Field(
        ...,
        description="费用类型：royalty/management_fee/training_fee/other",
    )
    description: str = Field(..., max_length=200)
    amount_fen: int = Field(..., ge=0, description="金额（分）")

    model_config = {"json_encoders": {UUID: str}}


class FranchiseSettlement(BaseModel):
    """加盟商月结算单（对应 franchise_settlements 表）"""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    franchisee_id: UUID
    year: int = Field(..., ge=2020, le=2099)
    month: int = Field(..., ge=1, le=12)
    revenue_fen: int = Field(..., ge=0, description="当月营业额（分）")
    royalty_amount_fen: int = Field(..., ge=0, description="特许权金（分）")
    mgmt_fee_fen: int = Field(default=0, ge=0, description="管理费（分）")
    total_amount_fen: int = Field(..., ge=0, description="合计应付（分）")
    status: str = Field(default=SettlementStatus.DRAFT)
    due_date: Optional[date] = None
    paid_at: Optional[datetime] = None
    payment_ref: Optional[str] = None
    items: List[FranchiseSettlementItem] = Field(default_factory=list)

    model_config = {
        "json_encoders": {
            UUID: str,
            datetime: lambda v: v.isoformat(),
            date: str,
        }
    }

    def is_finalized(self) -> bool:
        """结算单是否已锁定（sent 及以后的状态不可修改金额）"""
        return self.status in SettlementStatus.FINALIZED

    def _assert_transition(self, target: str) -> None:
        """校验状态转换合法性，非法则抛出异常"""
        allowed_next = SettlementStatus.ALLOWED_TRANSITIONS.get(self.status)
        if allowed_next != target:
            raise InvalidStatusTransitionError(self.status, target)


class FranchiseeStatementItem(BaseModel):
    """对账报表月度明细"""

    year: int
    month: int
    revenue_fen: int
    royalty_amount_fen: int
    mgmt_fee_fen: int
    total_amount_fen: int
    status: str
    due_date: Optional[date] = None
    paid_at: Optional[datetime] = None

    model_config = {
        "json_encoders": {datetime: lambda v: v.isoformat(), date: str}
    }


class FranchiseeStatement(BaseModel):
    """加盟商对账报表（近 N 个月汇总）"""

    franchisee_id: str
    tenant_id: str
    months: int
    total_revenue_fen: int
    total_royalty_fen: int
    total_mgmt_fee_fen: int
    outstanding_amount_fen: int = Field(
        ..., description="累计欠款（未付结算单合计）"
    )
    monthly_items: List[FranchiseeStatementItem]

    model_config = {"json_encoders": {UUID: str}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  结算服务
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class FranchiseSettlementService:
    """加盟商财务结算服务（无状态，所有方法均为 async）"""

    # ──────────────────────────────────────────────────────
    #  月结算单生成
    # ──────────────────────────────────────────────────────

    async def generate_monthly_settlement(
        self,
        franchisee_id: str,
        year: int,
        month: int,
        tenant_id: str,
        db: Any,
    ) -> FranchiseSettlement:
        """生成月结算单。

        步骤：
        1. 检查是否已存在当月结算单（幂等：已有则直接返回）
        2. 从 orders 表汇总该加盟商当月营业额
        3. 调用 royalty_calculator 计算特许权金
        4. 加管理费等固定项目
        5. 生成结算单（status=draft），写入 DB

        参数：
            franchisee_id — 加盟商 ID
            year          — 年份
            month         — 月份（1-12）
            tenant_id     — 集团 tenant_id
            db            — 数据库连接

        返回：FranchiseSettlement（新建或已有）
        """
        log = logger.bind(
            tenant_id=tenant_id,
            franchisee_id=franchisee_id,
            year=year,
            month=month,
        )
        log.info("franchise_settlement.generate.start")

        # Step 1: 幂等检查
        existing_row = await self._find_existing_settlement(
            tenant_id=tenant_id,
            franchisee_id=franchisee_id,
            year=year,
            month=month,
            db=db,
        )
        if existing_row:
            log.info(
                "franchise_settlement.generate.already_exists",
                settlement_id=str(existing_row["id"]),
            )
            return self._row_to_settlement(existing_row)

        # Step 2: 获取加盟商信息（计算特许权金需要费率/阶梯）
        franchisee = await self._fetch_franchisee(
            franchisee_id=franchisee_id,
            tenant_id=tenant_id,
            db=db,
        )

        # Step 3: 汇总当月营业额
        period_start, period_end = self._month_range(year, month)
        store_ids = await self._fetch_franchisee_store_ids(
            franchisee_id=franchisee_id,
            tenant_id=tenant_id,
            db=db,
        )
        revenue_fen: int = await self._sum_store_revenue_fen(
            store_ids=store_ids,
            period_start=period_start,
            period_end=period_end,
            tenant_id=tenant_id,
            db=db,
        )
        total_revenue = revenue_fen / 100.0

        # Step 4: 计算特许权金
        royalty_amount = RoyaltyCalculator.calculate(total_revenue, franchisee)
        royalty_amount_fen = int(round(royalty_amount * 100))

        # Step 5: 管理费（从加盟商档案读取固定管理费）
        mgmt_fee_fen: int = getattr(franchisee, "management_fee_fen", 0)
        total_amount_fen = royalty_amount_fen + mgmt_fee_fen

        # Step 6: 计算到期日（次月15日）
        due_date = self._calc_due_date(year, month)

        # Step 7: 构建结算单对象
        settlement_id = uuid4()
        items = [
            FranchiseSettlementItem(
                settlement_id=settlement_id,
                item_type="royalty",
                description=f"{year}年{month}月特许权金",
                amount_fen=royalty_amount_fen,
            ),
        ]
        if mgmt_fee_fen > 0:
            items.append(
                FranchiseSettlementItem(
                    settlement_id=settlement_id,
                    item_type="management_fee",
                    description=f"{year}年{month}月管理费",
                    amount_fen=mgmt_fee_fen,
                )
            )

        settlement = FranchiseSettlement(
            id=settlement_id,
            tenant_id=UUID(tenant_id),
            franchisee_id=UUID(franchisee_id),
            year=year,
            month=month,
            revenue_fen=revenue_fen,
            royalty_amount_fen=royalty_amount_fen,
            mgmt_fee_fen=mgmt_fee_fen,
            total_amount_fen=total_amount_fen,
            status=SettlementStatus.DRAFT,
            due_date=due_date,
            items=items,
        )

        # Step 8: 写入数据库
        await self._insert_settlement(settlement=settlement, db=db)

        log.info(
            "franchise_settlement.generate.done",
            settlement_id=str(settlement_id),
            revenue_fen=revenue_fen,
            royalty_amount_fen=royalty_amount_fen,
            total_amount_fen=total_amount_fen,
        )
        return settlement

    # ──────────────────────────────────────────────────────
    #  状态流转
    # ──────────────────────────────────────────────────────

    async def send_settlement_to_franchisee(
        self,
        settlement_id: str,
        tenant_id: str,
        db: Any,
    ) -> None:
        """发送结算单给加盟商（draft → sent）。

        校验：当前状态必须为 draft。
        副作用：触发企业微信通知（WeCom）。
        """
        log = logger.bind(tenant_id=tenant_id, settlement_id=settlement_id)

        settlement = await self._load_settlement(settlement_id, tenant_id, db)
        settlement._assert_transition(SettlementStatus.SENT)

        await db.execute(
            """
            UPDATE franchise_settlements
               SET status = :status,
                   updated_at = NOW()
             WHERE id = :id
               AND tenant_id = :tenant_id
            """,
            {
                "status": SettlementStatus.SENT,
                "id": settlement_id,
                "tenant_id": tenant_id,
            },
        )

        log.info(
            "franchise_settlement.sent",
            franchisee_id=str(settlement.franchisee_id),
        )

        # 企业微信通知（非阻塞，失败不影响主流程）
        await self._notify_wecom_settlement_sent(settlement, log)

    async def confirm_settlement(
        self,
        settlement_id: str,
        franchisee_id: str,
        tenant_id: str,
        db: Any,
    ) -> None:
        """加盟商确认结算单（sent → confirmed）。

        校验：
        1. 当前状态必须为 sent
        2. 操作人必须是该结算单对应的加盟商
        """
        log = logger.bind(
            tenant_id=tenant_id,
            settlement_id=settlement_id,
            franchisee_id=franchisee_id,
        )

        settlement = await self._load_settlement(settlement_id, tenant_id, db)
        settlement._assert_transition(SettlementStatus.CONFIRMED)

        if str(settlement.franchisee_id) != franchisee_id:
            raise PermissionError(
                f"加盟商 {franchisee_id!r} 无权确认结算单 {settlement_id!r}"
            )

        await db.execute(
            """
            UPDATE franchise_settlements
               SET status = :status,
                   updated_at = NOW()
             WHERE id = :id
               AND tenant_id = :tenant_id
            """,
            {
                "status": SettlementStatus.CONFIRMED,
                "id": settlement_id,
                "tenant_id": tenant_id,
            },
        )
        log.info("franchise_settlement.confirmed")

    async def mark_as_paid(
        self,
        settlement_id: str,
        payment_ref: str,
        tenant_id: str,
        db: Any,
    ) -> None:
        """标记已收款（confirmed → paid），记录打款凭证。

        校验：当前状态必须为 confirmed。
        """
        log = logger.bind(
            tenant_id=tenant_id,
            settlement_id=settlement_id,
            payment_ref=payment_ref,
        )

        settlement = await self._load_settlement(settlement_id, tenant_id, db)
        settlement._assert_transition(SettlementStatus.PAID)

        await db.execute(
            """
            UPDATE franchise_settlements
               SET status = :status,
                   paid_at = NOW(),
                   payment_ref = :payment_ref,
                   updated_at = NOW()
             WHERE id = :id
               AND tenant_id = :tenant_id
            """,
            {
                "status": SettlementStatus.PAID,
                "payment_ref": payment_ref,
                "id": settlement_id,
                "tenant_id": tenant_id,
            },
        )
        log.info("franchise_settlement.paid")

    # ──────────────────────────────────────────────────────
    #  逾期预警
    # ──────────────────────────────────────────────────────

    async def get_overdue_settlements(
        self,
        tenant_id: str,
        overdue_days: int = 15,
        db: Any = None,
    ) -> List[FranchiseSettlement]:
        """查询逾期未付款结算单（confirmed 且超期 N 天）。

        逾期判断：due_date < today - overdue_days
        只查 confirmed 状态（sent 状态视为还未到确认，不计入逾期）
        """
        cutoff = date.today() - timedelta(days=overdue_days)
        log = logger.bind(tenant_id=tenant_id, cutoff=str(cutoff))
        log.info("franchise_settlement.get_overdue.start")

        rows = await db.fetch_all(
            """
            SELECT id, tenant_id, franchisee_id,
                   year, month,
                   revenue_fen, royalty_amount_fen, mgmt_fee_fen, total_amount_fen,
                   status, due_date, paid_at, payment_ref
              FROM franchise_settlements
             WHERE tenant_id = :tenant_id
               AND status = :status
               AND due_date < :cutoff
             ORDER BY due_date ASC
            """,
            {
                "tenant_id": tenant_id,
                "status": SettlementStatus.CONFIRMED,
                "cutoff": cutoff,
            },
        )

        results = [self._row_to_settlement(row) for row in rows]
        log.info("franchise_settlement.get_overdue.done", count=len(results))
        return results

    # ──────────────────────────────────────────────────────
    #  加盟商对账报表
    # ──────────────────────────────────────────────────────

    async def get_franchisee_statement(
        self,
        franchisee_id: str,
        tenant_id: str,
        months: int = 12,
        db: Any = None,
    ) -> FranchiseeStatement:
        """加盟商对账报表（近 N 个月）。

        汇总字段：
        - 每月营业额 / 特许权金 / 管理费 / 状态
        - 累计欠款（未付结算单合计）
        """
        today = date.today()
        # 往前推 months 个月的起点
        if today.month > months % 12:
            start_year = today.year - months // 12
            start_month = today.month - months % 12
        else:
            start_year = today.year - months // 12 - 1
            start_month = today.month - months % 12 + 12

        rows = await db.fetch_all(
            """
            SELECT id, tenant_id, franchisee_id,
                   year, month,
                   revenue_fen, royalty_amount_fen, mgmt_fee_fen, total_amount_fen,
                   status, due_date, paid_at, payment_ref
              FROM franchise_settlements
             WHERE tenant_id = :tenant_id
               AND franchisee_id = :franchisee_id
               AND (year > :start_year
                    OR (year = :start_year AND month >= :start_month))
             ORDER BY year DESC, month DESC
             LIMIT :limit
            """,
            {
                "tenant_id": tenant_id,
                "franchisee_id": franchisee_id,
                "start_year": start_year,
                "start_month": start_month,
                "limit": months,
            },
        )

        monthly_items: List[FranchiseeStatementItem] = []
        total_revenue_fen = 0
        total_royalty_fen = 0
        total_mgmt_fee_fen = 0
        outstanding_amount_fen = 0

        _unpaid_statuses = {SettlementStatus.SENT, SettlementStatus.CONFIRMED}

        for row in rows:
            monthly_items.append(
                FranchiseeStatementItem(
                    year=row["year"],
                    month=row["month"],
                    revenue_fen=row["revenue_fen"],
                    royalty_amount_fen=row["royalty_amount_fen"],
                    mgmt_fee_fen=row["mgmt_fee_fen"],
                    total_amount_fen=row["total_amount_fen"],
                    status=row["status"],
                    due_date=row["due_date"],
                    paid_at=row["paid_at"],
                )
            )
            total_revenue_fen += row["revenue_fen"]
            total_royalty_fen += row["royalty_amount_fen"]
            total_mgmt_fee_fen += row["mgmt_fee_fen"]
            if row["status"] in _unpaid_statuses:
                outstanding_amount_fen += row["total_amount_fen"]

        return FranchiseeStatement(
            franchisee_id=franchisee_id,
            tenant_id=tenant_id,
            months=months,
            total_revenue_fen=total_revenue_fen,
            total_royalty_fen=total_royalty_fen,
            total_mgmt_fee_fen=total_mgmt_fee_fen,
            outstanding_amount_fen=outstanding_amount_fen,
            monthly_items=monthly_items,
        )

    # ──────────────────────────────────────────────────────
    #  私有辅助方法
    # ──────────────────────────────────────────────────────

    async def _load_settlement(
        self,
        settlement_id: str,
        tenant_id: str,
        db: Any,
    ) -> FranchiseSettlement:
        """从 DB 加载结算单，不存在则抛出 SettlementNotFoundError。"""
        row = await db.fetch_one(
            """
            SELECT id, tenant_id, franchisee_id,
                   year, month,
                   revenue_fen, royalty_amount_fen, mgmt_fee_fen, total_amount_fen,
                   status, due_date, paid_at, payment_ref
              FROM franchise_settlements
             WHERE id = :id
               AND tenant_id = :tenant_id
             LIMIT 1
            """,
            {"id": settlement_id, "tenant_id": tenant_id},
        )
        if not row:
            raise SettlementNotFoundError(settlement_id)
        return self._row_to_settlement(row)

    async def _find_existing_settlement(
        self,
        tenant_id: str,
        franchisee_id: str,
        year: int,
        month: int,
        db: Any,
    ) -> Optional[Any]:
        """查询是否已存在该加盟商指定月的结算单（幂等保护）。"""
        return await db.fetch_one(
            """
            SELECT id, tenant_id, franchisee_id,
                   year, month,
                   revenue_fen, royalty_amount_fen, mgmt_fee_fen, total_amount_fen,
                   status, due_date, paid_at, payment_ref
              FROM franchise_settlements
             WHERE tenant_id = :tenant_id
               AND franchisee_id = :franchisee_id
               AND year = :year
               AND month = :month
             LIMIT 1
            """,
            {
                "tenant_id": tenant_id,
                "franchisee_id": franchisee_id,
                "year": year,
                "month": month,
            },
        )

    async def _fetch_franchisee(
        self,
        franchisee_id: str,
        tenant_id: str,
        db: Any,
    ) -> Franchisee:
        """从 DB 加载加盟商档案（含费率和管理费）。"""
        row = await db.fetch_one(
            """
            SELECT id, tenant_id, name AS franchisee_name,
                   contact_name, contact_phone,
                   contract_start, contract_end,
                   royalty_rate, royalty_tiers,
                   management_fee_fen, status, created_at
              FROM franchisees
             WHERE id = :id
               AND tenant_id = :tenant_id
             LIMIT 1
            """,
            {"id": franchisee_id, "tenant_id": tenant_id},
        )
        if not row:
            raise LookupError(f"加盟商 {franchisee_id!r} 不存在")

        tiers_raw = row["royalty_tiers"] or []
        tiers = [RoyaltyTier(**t) for t in tiers_raw] if tiers_raw else []

        f = Franchisee(
            id=UUID(str(row["id"])),
            tenant_id=UUID(str(row["tenant_id"])),
            franchisee_name=row["franchisee_name"],
            contact_name=row["contact_name"],
            contact_phone=row["contact_phone"],
            contract_start=row["contract_start"],
            contract_end=row["contract_end"],
            royalty_rate=float(row["royalty_rate"]),
            royalty_tiers=tiers,
            status=row["status"],
            created_at=row["created_at"],
        )
        object.__setattr__(f, "management_fee_fen", row["management_fee_fen"] or 0)
        return f

    async def _fetch_franchisee_store_ids(
        self,
        franchisee_id: str,
        tenant_id: str,
        db: Any,
    ) -> List[str]:
        """查询加盟商旗下所有 active 门店 ID。"""
        rows = await db.fetch_all(
            """
            SELECT store_id
              FROM franchisee_stores
             WHERE franchisee_id = :franchisee_id
               AND tenant_id = :tenant_id
               AND status = 'active'
            """,
            {"franchisee_id": franchisee_id, "tenant_id": tenant_id},
        )
        return [str(row["store_id"]) for row in rows]

    async def _sum_store_revenue_fen(
        self,
        store_ids: List[str],
        period_start: date,
        period_end: date,
        tenant_id: str,
        db: Any,
    ) -> int:
        """汇总门店在指定区间内的营业额（分），仅统计 completed 订单。"""
        if not store_ids:
            return 0
        row = await db.fetch_one(
            """
            SELECT COALESCE(SUM(paid_amount_fen), 0) AS total_fen
              FROM orders
             WHERE tenant_id = :tenant_id
               AND store_id = ANY(:store_ids)
               AND status = 'completed'
               AND created_at::date >= :period_start
               AND created_at::date <= :period_end
            """,
            {
                "tenant_id": tenant_id,
                "store_ids": store_ids,
                "period_start": period_start,
                "period_end": period_end,
            },
        )
        return int(row["total_fen"]) if row else 0

    async def _insert_settlement(
        self,
        settlement: FranchiseSettlement,
        db: Any,
    ) -> None:
        """将结算单写入 franchise_settlements 表，并插入明细条目。"""
        await db.execute(
            """
            INSERT INTO franchise_settlements (
                id, tenant_id, franchisee_id,
                year, month,
                revenue_fen, royalty_amount_fen, mgmt_fee_fen, total_amount_fen,
                status, due_date,
                created_at, updated_at
            ) VALUES (
                :id, :tenant_id, :franchisee_id,
                :year, :month,
                :revenue_fen, :royalty_amount_fen, :mgmt_fee_fen, :total_amount_fen,
                :status, :due_date,
                NOW(), NOW()
            )
            """,
            {
                "id": str(settlement.id),
                "tenant_id": str(settlement.tenant_id),
                "franchisee_id": str(settlement.franchisee_id),
                "year": settlement.year,
                "month": settlement.month,
                "revenue_fen": settlement.revenue_fen,
                "royalty_amount_fen": settlement.royalty_amount_fen,
                "mgmt_fee_fen": settlement.mgmt_fee_fen,
                "total_amount_fen": settlement.total_amount_fen,
                "status": settlement.status,
                "due_date": settlement.due_date,
            },
        )

        for item in settlement.items:
            await db.execute(
                """
                INSERT INTO franchise_settlement_items (
                    id, settlement_id, item_type, description, amount_fen, created_at
                ) VALUES (
                    :id, :settlement_id, :item_type, :description, :amount_fen, NOW()
                )
                """,
                {
                    "id": str(item.id),
                    "settlement_id": str(item.settlement_id),
                    "item_type": item.item_type,
                    "description": item.description,
                    "amount_fen": item.amount_fen,
                },
            )

    async def _notify_wecom_settlement_sent(
        self,
        settlement: FranchiseSettlement,
        log: Any,
    ) -> None:
        """企业微信通知（发送结算单）。

        非阻塞：失败只记录日志，不影响主流程。
        实际集成时通过 WeCom HTTP API 发送消息。
        """
        try:
            log.info(
                "franchise_settlement.wecom_notify",
                franchisee_id=str(settlement.franchisee_id),
                year=settlement.year,
                month=settlement.month,
                total_amount_fen=settlement.total_amount_fen,
            )
            # 通过企业微信 WeCom HTTP API 发送结算单通知
            # 需要环境变量：WECOM_CORP_ID, WECOM_CORP_SECRET, WECOM_AGENT_ID
            corp_id = os.getenv("WECOM_CORP_ID")
            corp_secret = os.getenv("WECOM_CORP_SECRET")
            agent_id = os.getenv("WECOM_AGENT_ID")
            wecom_to_user = os.getenv("WECOM_FRANCHISEE_TOUSER", "@all")

            if corp_id and corp_secret and agent_id:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    # Step 1: 获取 access_token
                    token_resp = await client.get(
                        "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                        params={"corpid": corp_id, "corpsecret": corp_secret},
                    )
                    token_data = token_resp.json()
                    access_token = token_data.get("access_token", "")

                    if access_token:
                        # Step 2: 发送文字消息
                        total_yuan = settlement.total_amount_fen / 100
                        content = (
                            f"【结算单通知】{settlement.year}年{settlement.month}月结算单已生成\n"
                            f"加盟商ID：{settlement.franchisee_id}\n"
                            f"结算金额：¥{total_yuan:.2f}"
                        )
                        await client.post(
                            f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}",
                            json={
                                "touser": wecom_to_user,
                                "msgtype": "text",
                                "agentid": int(agent_id),
                                "text": {"content": content},
                            },
                        )
                        log.info(
                            "franchise_settlement.wecom_notify.sent",
                            franchisee_id=str(settlement.franchisee_id),
                        )
            else:
                log.warning(
                    "franchise_settlement.wecom_notify.skipped",
                    reason="WECOM_CORP_ID/WECOM_CORP_SECRET/WECOM_AGENT_ID not configured",
                )
        except (OSError, httpx.HTTPError) as e:
            log.warning(
                "franchise_settlement.wecom_notify.failed",
                error=str(e),
            )

    @staticmethod
    def _row_to_settlement(row: Any) -> FranchiseSettlement:
        """将 DB 行转换为 FranchiseSettlement 对象。"""
        return FranchiseSettlement(
            id=UUID(str(row["id"])),
            tenant_id=UUID(str(row["tenant_id"])),
            franchisee_id=UUID(str(row["franchisee_id"])),
            year=row["year"],
            month=row["month"],
            revenue_fen=row["revenue_fen"],
            royalty_amount_fen=row["royalty_amount_fen"],
            mgmt_fee_fen=row["mgmt_fee_fen"],
            total_amount_fen=row["total_amount_fen"],
            status=row["status"],
            due_date=row["due_date"],
            paid_at=row["paid_at"],
            payment_ref=row["payment_ref"],
        )

    @staticmethod
    def _month_range(year: int, month: int) -> tuple[date, date]:
        """返回指定年月的起止日期（闭区间）。"""
        start = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        end = date(year, month, last_day)
        return start, end

    @staticmethod
    def _calc_due_date(year: int, month: int) -> date:
        """计算结算单到期日（次月15日）。"""
        if month == 12:
            return date(year + 1, 1, 15)
        return date(year, month + 1, 15)
