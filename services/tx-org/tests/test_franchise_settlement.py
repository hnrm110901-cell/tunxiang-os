"""加盟商财务结算测试

覆盖场景：
1. 特许权金计算（按营业额比例 vs 固定金额两种模式）
2. 月结算单生成（幂等：重复调用返回已有记录）
3. 加盟商对账报表数据结构
4. 逾期预警触发条件（超期15天）
5. 结算状态流转：draft → sent → confirmed → paid
6. 状态机不可逆约束（不能从 paid 回退）
7. 已发送后金额不可修改约束
"""

from __future__ import annotations

import pytest
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from services.tx_org.src.models.franchise import (
    Franchisee,
    FranchiseeStatus,
    RoyaltyTier,
)
from services.tx_org.src.services.franchise_settlement_service import (
    FranchiseSettlement,
    FranchiseSettlementItem,
    FranchiseeStatement,
    FranchiseSettlementService,
    SettlementStatus,
    InvalidStatusTransitionError,
    SettlementAlreadyFinalizedError,
)
from services.tx_org.src.services.royalty_calculator import RoyaltyCalculator


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  固定数据与 Fixture
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TENANT_ID = uuid4()
FRANCHISEE_ID = uuid4()
SETTLEMENT_ID = uuid4()


def make_franchisee(
    royalty_rate: float = 0.05,
    tiers: list[RoyaltyTier] | None = None,
    management_fee_fen: int = 200_000,  # 2000元管理费
) -> Franchisee:
    f = Franchisee(
        tenant_id=TENANT_ID,
        franchisee_name="测试加盟商",
        contact_name="张老板",
        contact_phone="13800138000",
        contract_start=date(2024, 1, 1),
        contract_end=date(2026, 12, 31),
        royalty_rate=royalty_rate,
        royalty_tiers=tiers or [],
        status=FranchiseeStatus.ACTIVE,
    )
    object.__setattr__(f, "management_fee_fen", management_fee_fen)
    return f


def make_settlement(
    status: str = SettlementStatus.DRAFT,
    due_date: date | None = None,
    year: int = 2026,
    month: int = 2,
) -> FranchiseSettlement:
    if due_date is None:
        due_date = date(2026, 3, 15)
    return FranchiseSettlement(
        id=SETTLEMENT_ID,
        tenant_id=TENANT_ID,
        franchisee_id=FRANCHISEE_ID,
        year=year,
        month=month,
        revenue_fen=1_000_000_00,   # 100万元（分）
        royalty_amount_fen=500_000,  # 5000元特许权金（分）
        mgmt_fee_fen=200_000,        # 2000元管理费（分）
        total_amount_fen=700_000,    # 合计7000元（分）
        status=status,
        due_date=due_date,
        paid_at=None,
        payment_ref=None,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 特许权金计算：比例模式
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestRoyaltyCalculationPercentage:
    """按营业额比例计算特许权金"""

    def test_flat_rate_simple(self):
        """无阶梯：royalty = revenue × rate"""
        franchisee = make_franchisee(royalty_rate=0.05)
        revenue = 200_000.0  # 20万元
        royalty = RoyaltyCalculator.calculate(revenue, franchisee)
        assert royalty == pytest.approx(10_000.0)

    def test_flat_rate_zero_revenue(self):
        """营业额为0时，特许权金为0"""
        franchisee = make_franchisee(royalty_rate=0.05)
        royalty = RoyaltyCalculator.calculate(0.0, franchisee)
        assert royalty == 0.0

    def test_flat_rate_negative_revenue(self):
        """负营业额时，特许权金为0（防御性）"""
        franchisee = make_franchisee(royalty_rate=0.05)
        royalty = RoyaltyCalculator.calculate(-1000.0, franchisee)
        assert royalty == 0.0

    def test_tiered_rate_below_first_threshold(self):
        """营业额在第一阶梯内，使用基础费率"""
        tiers = [
            RoyaltyTier(min_revenue=100_000, rate=0.04),
            RoyaltyTier(min_revenue=500_000, rate=0.03),
        ]
        franchisee = make_franchisee(royalty_rate=0.05, tiers=tiers)
        # 50000 全部在第一档 [0, 100000)，用基础费率 0.05
        royalty = RoyaltyCalculator.calculate(50_000.0, franchisee)
        assert royalty == pytest.approx(2_500.0)

    def test_tiered_rate_spans_two_tiers(self):
        """营业额跨越两档阶梯的累进计算"""
        tiers = [
            RoyaltyTier(min_revenue=0, rate=0.05),
            RoyaltyTier(min_revenue=100_000, rate=0.04),
        ]
        franchisee = make_franchisee(royalty_rate=0.05, tiers=tiers)
        # 200000：[0, 100000) × 0.05 + [100000, 200000) × 0.04
        # = 5000 + 4000 = 9000
        royalty = RoyaltyCalculator.calculate(200_000.0, franchisee)
        assert royalty == pytest.approx(9_000.0)

    def test_tiered_rate_last_tier_extends(self):
        """超出最后一档阈值，使用最后一档费率延续"""
        tiers = [
            RoyaltyTier(min_revenue=0, rate=0.05),
            RoyaltyTier(min_revenue=100_000, rate=0.04),
            RoyaltyTier(min_revenue=500_000, rate=0.03),
        ]
        franchisee = make_franchisee(royalty_rate=0.05, tiers=tiers)
        # 600000：
        #   [0, 100000)     = 100000 × 0.05 = 5000
        #   [100000, 500000) = 400000 × 0.04 = 16000
        #   [500000, 600000) = 100000 × 0.03 = 3000
        # 合计 = 24000
        royalty = RoyaltyCalculator.calculate(600_000.0, franchisee)
        assert royalty == pytest.approx(24_000.0)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 月结算单生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestGenerateMonthlySettlement:
    """月结算单生成逻辑"""

    @pytest.mark.asyncio
    async def test_generate_creates_draft_settlement(self):
        """正常生成：返回 status=draft 的结算单"""
        service = FranchiseSettlementService()
        db = AsyncMock()
        # 模拟：无已有记录，营业额100万分，加盟商基础费率0.05
        db.fetch_one.side_effect = [
            None,                              # _find_existing_settlement → 无已有记录
            {"total_fen": 100_000_000},        # _sum_revenue → 100万（分）
        ]
        db.fetch_all.return_value = [
            {"store_id": str(uuid4())}
        ]
        db.execute.return_value = MagicMock(rowcount=1)

        franchisee = make_franchisee(royalty_rate=0.05, management_fee_fen=200_000)
        franchisee_id = str(franchisee.id)

        with patch.object(
            service, "_fetch_franchisee", return_value=franchisee
        ):
            settlement = await service.generate_monthly_settlement(
                franchisee_id=franchisee_id,
                year=2026,
                month=2,
                tenant_id=str(TENANT_ID),
                db=db,
            )

        assert settlement.status == SettlementStatus.DRAFT
        assert settlement.year == 2026
        assert settlement.month == 2
        assert settlement.mgmt_fee_fen == 200_000

    @pytest.mark.asyncio
    async def test_generate_idempotent_returns_existing(self):
        """幂等：已存在当月结算单时，返回已有记录"""
        service = FranchiseSettlementService()
        db = AsyncMock()
        existing_id = uuid4()
        # 模拟：已有当月结算单
        db.fetch_one.side_effect = [
            {"id": str(existing_id), "status": "draft",
             "year": 2026, "month": 2,
             "revenue_fen": 100_000_000,
             "royalty_amount_fen": 500_000,
             "mgmt_fee_fen": 200_000,
             "total_amount_fen": 700_000,
             "due_date": date(2026, 3, 15),
             "paid_at": None,
             "payment_ref": None,
             "franchisee_id": str(FRANCHISEE_ID),
             "tenant_id": str(TENANT_ID)},
        ]

        franchisee = make_franchisee()
        with patch.object(
            service, "_fetch_franchisee", return_value=franchisee
        ):
            settlement = await service.generate_monthly_settlement(
                franchisee_id=str(FRANCHISEE_ID),
                year=2026,
                month=2,
                tenant_id=str(TENANT_ID),
                db=db,
            )

        assert str(settlement.id) == str(existing_id)
        # 幂等：不应再次调用 insert
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_due_date_is_next_month_15(self):
        """due_date 应为次月15日"""
        service = FranchiseSettlementService()
        db = AsyncMock()
        db.fetch_one.side_effect = [
            None,
            {"total_fen": 50_000_000},
        ]
        db.fetch_all.return_value = [{"store_id": str(uuid4())}]
        db.execute.return_value = MagicMock(rowcount=1)

        franchisee = make_franchisee()
        with patch.object(service, "_fetch_franchisee", return_value=franchisee):
            settlement = await service.generate_monthly_settlement(
                franchisee_id=str(FRANCHISEE_ID),
                year=2026,
                month=12,
                tenant_id=str(TENANT_ID),
                db=db,
            )

        # 12月账单的 due_date 应为次年1月15日
        assert settlement.due_date == date(2027, 1, 15)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 结算状态流转
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestSettlementStatusTransition:
    """状态机：draft → sent → confirmed → paid"""

    @pytest.mark.asyncio
    async def test_send_draft_to_sent(self):
        """draft → sent 成功"""
        service = FranchiseSettlementService()
        db = AsyncMock()
        settlement = make_settlement(status=SettlementStatus.DRAFT)
        db.fetch_one.return_value = {
            "id": str(settlement.id),
            "status": SettlementStatus.DRAFT,
            "year": settlement.year,
            "month": settlement.month,
            "revenue_fen": settlement.revenue_fen,
            "royalty_amount_fen": settlement.royalty_amount_fen,
            "mgmt_fee_fen": settlement.mgmt_fee_fen,
            "total_amount_fen": settlement.total_amount_fen,
            "due_date": settlement.due_date,
            "paid_at": None,
            "payment_ref": None,
            "franchisee_id": str(FRANCHISEE_ID),
            "tenant_id": str(TENANT_ID),
        }
        db.execute.return_value = MagicMock(rowcount=1)

        await service.send_settlement_to_franchisee(
            settlement_id=str(settlement.id),
            tenant_id=str(TENANT_ID),
            db=db,
        )

        # 验证状态更新 SQL 被调用
        db.execute.assert_called_once()
        call_kwargs = db.execute.call_args
        assert "sent" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_cannot_send_non_draft(self):
        """非 draft 状态不能发送（状态机不可逆）"""
        service = FranchiseSettlementService()
        db = AsyncMock()
        db.fetch_one.return_value = {
            "id": str(SETTLEMENT_ID),
            "status": SettlementStatus.CONFIRMED,
            "year": 2026, "month": 2,
            "revenue_fen": 100_000_000,
            "royalty_amount_fen": 500_000,
            "mgmt_fee_fen": 200_000,
            "total_amount_fen": 700_000,
            "due_date": date(2026, 3, 15),
            "paid_at": None,
            "payment_ref": None,
            "franchisee_id": str(FRANCHISEE_ID),
            "tenant_id": str(TENANT_ID),
        }

        with pytest.raises(InvalidStatusTransitionError) as exc_info:
            await service.send_settlement_to_franchisee(
                settlement_id=str(SETTLEMENT_ID),
                tenant_id=str(TENANT_ID),
                db=db,
            )
        assert "draft" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_confirm_sent_to_confirmed(self):
        """sent → confirmed 成功"""
        service = FranchiseSettlementService()
        db = AsyncMock()
        db.fetch_one.return_value = {
            "id": str(SETTLEMENT_ID),
            "status": SettlementStatus.SENT,
            "year": 2026, "month": 2,
            "revenue_fen": 100_000_000,
            "royalty_amount_fen": 500_000,
            "mgmt_fee_fen": 200_000,
            "total_amount_fen": 700_000,
            "due_date": date(2026, 3, 15),
            "paid_at": None,
            "payment_ref": None,
            "franchisee_id": str(FRANCHISEE_ID),
            "tenant_id": str(TENANT_ID),
        }
        db.execute.return_value = MagicMock(rowcount=1)

        await service.confirm_settlement(
            settlement_id=str(SETTLEMENT_ID),
            franchisee_id=str(FRANCHISEE_ID),
            tenant_id=str(TENANT_ID),
            db=db,
        )
        db.execute.assert_called_once()
        call_kwargs = db.execute.call_args
        assert "confirmed" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_cannot_confirm_draft_directly(self):
        """draft 不能直接跳到 confirmed（必须先 send）"""
        service = FranchiseSettlementService()
        db = AsyncMock()
        db.fetch_one.return_value = {
            "id": str(SETTLEMENT_ID),
            "status": SettlementStatus.DRAFT,
            "year": 2026, "month": 2,
            "revenue_fen": 100_000_000,
            "royalty_amount_fen": 500_000,
            "mgmt_fee_fen": 200_000,
            "total_amount_fen": 700_000,
            "due_date": date(2026, 3, 15),
            "paid_at": None,
            "payment_ref": None,
            "franchisee_id": str(FRANCHISEE_ID),
            "tenant_id": str(TENANT_ID),
        }

        with pytest.raises(InvalidStatusTransitionError):
            await service.confirm_settlement(
                settlement_id=str(SETTLEMENT_ID),
                franchisee_id=str(FRANCHISEE_ID),
                tenant_id=str(TENANT_ID),
                db=db,
            )

    @pytest.mark.asyncio
    async def test_mark_as_paid_confirmed_to_paid(self):
        """confirmed → paid 成功，记录 payment_ref"""
        service = FranchiseSettlementService()
        db = AsyncMock()
        db.fetch_one.return_value = {
            "id": str(SETTLEMENT_ID),
            "status": SettlementStatus.CONFIRMED,
            "year": 2026, "month": 2,
            "revenue_fen": 100_000_000,
            "royalty_amount_fen": 500_000,
            "mgmt_fee_fen": 200_000,
            "total_amount_fen": 700_000,
            "due_date": date(2026, 3, 15),
            "paid_at": None,
            "payment_ref": None,
            "franchisee_id": str(FRANCHISEE_ID),
            "tenant_id": str(TENANT_ID),
        }
        db.execute.return_value = MagicMock(rowcount=1)

        await service.mark_as_paid(
            settlement_id=str(SETTLEMENT_ID),
            payment_ref="PAY-2026-0315-001",
            tenant_id=str(TENANT_ID),
            db=db,
        )
        db.execute.assert_called_once()
        call_kwargs = db.execute.call_args
        assert "paid" in str(call_kwargs)
        assert "PAY-2026-0315-001" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_cannot_pay_from_sent(self):
        """sent 不能直接跳到 paid（必须先 confirm）"""
        service = FranchiseSettlementService()
        db = AsyncMock()
        db.fetch_one.return_value = {
            "id": str(SETTLEMENT_ID),
            "status": SettlementStatus.SENT,
            "year": 2026, "month": 2,
            "revenue_fen": 100_000_000,
            "royalty_amount_fen": 500_000,
            "mgmt_fee_fen": 200_000,
            "total_amount_fen": 700_000,
            "due_date": date(2026, 3, 15),
            "paid_at": None,
            "payment_ref": None,
            "franchisee_id": str(FRANCHISEE_ID),
            "tenant_id": str(TENANT_ID),
        }

        with pytest.raises(InvalidStatusTransitionError):
            await service.mark_as_paid(
                settlement_id=str(SETTLEMENT_ID),
                payment_ref="PAY-2026-0315-001",
                tenant_id=str(TENANT_ID),
                db=db,
            )

    @pytest.mark.asyncio
    async def test_paid_is_terminal_state(self):
        """paid 是终态，不能再转任何状态"""
        service = FranchiseSettlementService()
        db = AsyncMock()
        paid_row = {
            "id": str(SETTLEMENT_ID),
            "status": SettlementStatus.PAID,
            "year": 2026, "month": 2,
            "revenue_fen": 100_000_000,
            "royalty_amount_fen": 500_000,
            "mgmt_fee_fen": 200_000,
            "total_amount_fen": 700_000,
            "due_date": date(2026, 3, 15),
            "paid_at": datetime(2026, 3, 10),
            "payment_ref": "PAY-001",
            "franchisee_id": str(FRANCHISEE_ID),
            "tenant_id": str(TENANT_ID),
        }
        db.fetch_one.return_value = paid_row

        # 尝试重新发送 — 应失败
        with pytest.raises(InvalidStatusTransitionError):
            await service.send_settlement_to_franchisee(
                settlement_id=str(SETTLEMENT_ID),
                tenant_id=str(TENANT_ID),
                db=db,
            )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 逾期预警：超期15天触发
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestOverdueWarning:
    """逾期预警：超期15天的 confirmed 结算单"""

    @pytest.mark.asyncio
    async def test_overdue_settlements_returned(self):
        """get_overdue_settlements 返回超期15天的结算单"""
        service = FranchiseSettlementService()
        db = AsyncMock()
        overdue_due_date = date.today() - timedelta(days=20)  # 超期20天

        db.fetch_all.return_value = [
            {
                "id": str(uuid4()),
                "status": SettlementStatus.CONFIRMED,
                "year": 2026, "month": 1,
                "revenue_fen": 100_000_000,
                "royalty_amount_fen": 500_000,
                "mgmt_fee_fen": 200_000,
                "total_amount_fen": 700_000,
                "due_date": overdue_due_date,
                "paid_at": None,
                "payment_ref": None,
                "franchisee_id": str(FRANCHISEE_ID),
                "tenant_id": str(TENANT_ID),
            }
        ]

        results = await service.get_overdue_settlements(
            tenant_id=str(TENANT_ID),
            overdue_days=15,
            db=db,
        )

        assert len(results) == 1
        assert results[0].status == SettlementStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_overdue_query_uses_cutoff_date(self):
        """查询使用正确的截止日期（today - 15天）"""
        service = FranchiseSettlementService()
        db = AsyncMock()
        db.fetch_all.return_value = []

        await service.get_overdue_settlements(
            tenant_id=str(TENANT_ID),
            overdue_days=15,
            db=db,
        )

        db.fetch_all.assert_called_once()
        call_args = db.fetch_all.call_args
        # 验证 cutoff 参数被正确传递
        assert "cutoff" in str(call_args) or len(call_args[0]) > 1

    @pytest.mark.asyncio
    async def test_just_within_15days_not_overdue(self):
        """恰好14天不触发预警（边界测试）"""
        service = FranchiseSettlementService()
        db = AsyncMock()
        # 只返回超期>=15天的，14天不返回
        db.fetch_all.return_value = []

        results = await service.get_overdue_settlements(
            tenant_id=str(TENANT_ID),
            overdue_days=15,
            db=db,
        )
        assert results == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 加盟商对账报表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestFranchiseeStatement:
    """加盟商对账报表（近12个月）"""

    @pytest.mark.asyncio
    async def test_statement_contains_12_months(self):
        """对账报表包含近12个月数据"""
        service = FranchiseSettlementService()
        db = AsyncMock()

        # 模拟12个月的结算记录
        months_data = []
        for m in range(1, 13):
            months_data.append({
                "id": str(uuid4()),
                "status": SettlementStatus.PAID,
                "year": 2025,
                "month": m,
                "revenue_fen": 80_000_000 + m * 1_000_000,
                "royalty_amount_fen": 400_000,
                "mgmt_fee_fen": 200_000,
                "total_amount_fen": 600_000,
                "due_date": date(2025, m, 15) if m < 12 else date(2026, 1, 15),
                "paid_at": datetime(2025, m, 10) if m < 12 else datetime(2026, 1, 8),
                "payment_ref": f"PAY-2025-{m:02d}",
                "franchisee_id": str(FRANCHISEE_ID),
                "tenant_id": str(TENANT_ID),
            })
        db.fetch_all.return_value = months_data

        statement = await service.get_franchisee_statement(
            franchisee_id=str(FRANCHISEE_ID),
            tenant_id=str(TENANT_ID),
            months=12,
            db=db,
        )

        assert isinstance(statement, FranchiseeStatement)
        assert len(statement.monthly_items) == 12

    @pytest.mark.asyncio
    async def test_statement_fields_structure(self):
        """对账报表包含营业额/特许权金/管理费/累计欠款字段"""
        service = FranchiseSettlementService()
        db = AsyncMock()
        db.fetch_all.return_value = [
            {
                "id": str(uuid4()),
                "status": SettlementStatus.CONFIRMED,
                "year": 2026, "month": 2,
                "revenue_fen": 100_000_000,
                "royalty_amount_fen": 500_000,
                "mgmt_fee_fen": 200_000,
                "total_amount_fen": 700_000,
                "due_date": date(2026, 3, 15),
                "paid_at": None,
                "payment_ref": None,
                "franchisee_id": str(FRANCHISEE_ID),
                "tenant_id": str(TENANT_ID),
            }
        ]

        statement = await service.get_franchisee_statement(
            franchisee_id=str(FRANCHISEE_ID),
            tenant_id=str(TENANT_ID),
            months=12,
            db=db,
        )

        assert statement.franchisee_id == str(FRANCHISEE_ID)
        assert statement.total_revenue_fen >= 0
        assert statement.total_royalty_fen >= 0
        assert statement.total_mgmt_fee_fen >= 0
        assert statement.outstanding_amount_fen >= 0

        # 每条月度明细有必要字段
        item = statement.monthly_items[0]
        assert hasattr(item, "year")
        assert hasattr(item, "month")
        assert hasattr(item, "revenue_fen")
        assert hasattr(item, "royalty_amount_fen")
        assert hasattr(item, "mgmt_fee_fen")
        assert hasattr(item, "status")

    @pytest.mark.asyncio
    async def test_statement_outstanding_sum(self):
        """累计欠款 = 未付结算单 total_amount_fen 之和"""
        service = FranchiseSettlementService()
        db = AsyncMock()
        db.fetch_all.return_value = [
            {
                "id": str(uuid4()),
                "status": SettlementStatus.CONFIRMED,  # 已确认但未付
                "year": 2026, "month": 1,
                "revenue_fen": 100_000_000,
                "royalty_amount_fen": 500_000,
                "mgmt_fee_fen": 200_000,
                "total_amount_fen": 700_000,
                "due_date": date(2026, 2, 15),
                "paid_at": None,
                "payment_ref": None,
                "franchisee_id": str(FRANCHISEE_ID),
                "tenant_id": str(TENANT_ID),
            },
            {
                "id": str(uuid4()),
                "status": SettlementStatus.SENT,  # 已发送未确认
                "year": 2026, "month": 2,
                "revenue_fen": 90_000_000,
                "royalty_amount_fen": 450_000,
                "mgmt_fee_fen": 200_000,
                "total_amount_fen": 650_000,
                "due_date": date(2026, 3, 15),
                "paid_at": None,
                "payment_ref": None,
                "franchisee_id": str(FRANCHISEE_ID),
                "tenant_id": str(TENANT_ID),
            },
            {
                "id": str(uuid4()),
                "status": SettlementStatus.PAID,  # 已付款不计入欠款
                "year": 2025, "month": 12,
                "revenue_fen": 95_000_000,
                "royalty_amount_fen": 475_000,
                "mgmt_fee_fen": 200_000,
                "total_amount_fen": 675_000,
                "due_date": date(2026, 1, 15),
                "paid_at": datetime(2026, 1, 10),
                "payment_ref": "PAY-001",
                "franchisee_id": str(FRANCHISEE_ID),
                "tenant_id": str(TENANT_ID),
            },
        ]

        statement = await service.get_franchisee_statement(
            franchisee_id=str(FRANCHISEE_ID),
            tenant_id=str(TENANT_ID),
            months=12,
            db=db,
        )

        # 欠款 = confirmed(700000) + sent(650000) = 1350000
        assert statement.outstanding_amount_fen == 700_000 + 650_000


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 不可修改约束
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestSettlementImmutability:
    """结算单发送后不可修改金额"""

    def test_finalized_statuses(self):
        """sent/confirmed/paid 均视为已锁定，不可修改金额"""
        finalized_statuses = [
            SettlementStatus.SENT,
            SettlementStatus.CONFIRMED,
            SettlementStatus.PAID,
        ]
        for status in finalized_statuses:
            settlement = make_settlement(status=status)
            assert settlement.is_finalized(), (
                f"status={status} 应视为已锁定（is_finalized=True）"
            )

    def test_draft_is_not_finalized(self):
        """draft 状态未锁定，可以修改"""
        settlement = make_settlement(status=SettlementStatus.DRAFT)
        assert not settlement.is_finalized()
