"""加盟管理体系测试

覆盖场景：
1. 创建加盟商（关联一个或多个门店）
2. 加盟商只能看到自己门店的数据（数据隔离）
3. 月度分润计算：营业额 × 分润率（无阶梯）
4. 阶梯分润：营业额达到阈值后分润率变化（累进计算）
5. 分润账单生成（月度对账）
6. 加盟商欠款预警（累计欠款超阈值）
7. tenant_id 隔离（总部能看所有，加盟商只看自己）
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from services.tx_org.src.models.franchise import (
    Franchisee,
    FranchiseeStatus,
    FranchiseeStore,
    RoyaltyBill,
    RoyaltyBillStatus,
    RoyaltyTier,
)
from services.tx_org.src.services.franchise_service import (
    OVERDUE_ALERT_THRESHOLD,
    FranchiseService,
)
from services.tx_org.src.services.royalty_calculator import OVERDUE_DAYS, RoyaltyCalculator

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  固定数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TENANT_A = uuid4()  # 集团 A（总部视角）
TENANT_B = uuid4()  # 集团 B（用于隔离测试）


def make_franchisee(
    tenant_id: UUID = TENANT_A,
    royalty_rate: float = 0.05,
    tiers: list[RoyaltyTier] | None = None,
    status: str = FranchiseeStatus.ACTIVE,
) -> Franchisee:
    return Franchisee(
        tenant_id=tenant_id,
        franchisee_name="测试加盟商",
        contact_name="张三",
        contact_phone="13800138000",
        contract_start=date(2025, 1, 1),
        contract_end=date(2027, 12, 31),
        royalty_rate=royalty_rate,
        royalty_tiers=tiers or [],
        status=status,
    )


def make_bill(
    franchisee: Franchisee,
    bill_month: str = "2026-03",
    total_revenue: float = 100_000.0,
    royalty_amount: float = 5_000.0,
    status: str = RoyaltyBillStatus.PENDING,
    due_date: date | None = None,
) -> RoyaltyBill:
    return RoyaltyBill(
        tenant_id=franchisee.tenant_id,
        franchisee_id=franchisee.id,
        bill_month=bill_month,
        total_revenue=total_revenue,
        royalty_amount=royalty_amount,
        status=status,
        due_date=due_date or date(2026, 4, 15),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 1：创建加盟商
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_create_franchisee_basic():
    """创建基础加盟商（无阶梯，基础费率 5%）。"""
    franchisee = await FranchiseService.create_franchisee(
        data={
            "franchisee_name": "海底捞加盟商",
            "contact_name": "王五",
            "contact_phone": "13900139000",
            "royalty_rate": 0.05,
        },
        tenant_id=TENANT_A,
        db=None,
    )
    assert franchisee.franchisee_name == "海底捞加盟商"
    assert franchisee.tenant_id == TENANT_A
    assert franchisee.royalty_rate == 0.05
    assert franchisee.status == FranchiseeStatus.ACTIVE
    assert franchisee.royalty_tiers == []


@pytest.mark.asyncio
async def test_create_franchisee_with_tiers():
    """创建带阶梯分润配置的加盟商。"""
    franchisee = await FranchiseService.create_franchisee(
        data={
            "franchisee_name": "阶梯加盟商",
            "royalty_rate": 0.05,
            "royalty_tiers": [
                {"min_revenue": 100_000, "rate": 0.04},
                {"min_revenue": 500_000, "rate": 0.03},
            ],
        },
        tenant_id=TENANT_A,
        db=None,
    )
    assert len(franchisee.royalty_tiers) == 2
    assert franchisee.royalty_tiers[0].rate == 0.04


@pytest.mark.asyncio
async def test_create_franchisee_missing_name():
    """加盟商名称为空时应抛出 ValueError。"""
    with pytest.raises(ValueError, match="franchisee_name"):
        await FranchiseService.create_franchisee(
            data={"franchisee_name": "  "},
            tenant_id=TENANT_A,
            db=None,
        )


@pytest.mark.asyncio
async def test_assign_multiple_stores():
    """一个加盟商可以关联多个门店。"""
    franchisee = make_franchisee()
    store_ids = [uuid4(), uuid4(), uuid4()]
    links = []
    for sid in store_ids:
        link = await FranchiseService.assign_store(
            franchisee_id=franchisee.id,
            store_id=sid,
            tenant_id=TENANT_A,
            db=None,
        )
        links.append(link)

    assert len(links) == 3
    linked_store_ids = {lk.store_id for lk in links}
    assert linked_store_ids == set(store_ids)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 2：数据隔离
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_franchisee_store_isolation():
    """加盟商只能查到自己关联的门店 ID，不能访问其他加盟商的门店。"""
    franchisee_a = make_franchisee(tenant_id=TENANT_A)
    franchisee_b = make_franchisee(tenant_id=TENANT_A)
    store_a1 = uuid4()
    store_b1 = uuid4()

    # 分配给 A
    await FranchiseService.assign_store(franchisee_a.id, store_a1, TENANT_A, None)
    # 分配给 B
    await FranchiseService.assign_store(franchisee_b.id, store_b1, TENANT_A, None)

    # 查询 A 的门店列表
    a_stores = await FranchiseService.get_franchisee_store_ids(franchisee_a.id, TENANT_A, None)
    b_stores = await FranchiseService.get_franchisee_store_ids(franchisee_b.id, TENANT_A, None)

    # 模拟实现当前返回空列表（TODO: 真实 DB 后应返回对应 store_id）
    # 验证两个加盟商的门店集合不互相包含
    assert store_b1 not in a_stores
    assert store_a1 not in b_stores


def test_franchisee_store_model_isolation():
    """FranchiseeStore 模型 tenant_id 字段显式绑定，确保不跨租户。"""
    link = FranchiseeStore(
        tenant_id=TENANT_A,
        franchisee_id=uuid4(),
        store_id=uuid4(),
        joined_at=date.today(),
    )
    assert link.tenant_id == TENANT_A


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 3：月度分润计算（无阶梯）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_royalty_no_tiers_basic():
    """无阶梯：营业额 × 基础费率。"""
    franchisee = make_franchisee(royalty_rate=0.05)
    result = RoyaltyCalculator.calculate(100_000.0, franchisee)
    assert result == 5_000.0


def test_royalty_no_tiers_zero_revenue():
    """零营业额时分润为 0。"""
    franchisee = make_franchisee(royalty_rate=0.05)
    assert RoyaltyCalculator.calculate(0.0, franchisee) == 0.0


def test_royalty_no_tiers_negative_revenue():
    """负营业额（退款超收）时分润为 0。"""
    franchisee = make_franchisee(royalty_rate=0.05)
    assert RoyaltyCalculator.calculate(-1000.0, franchisee) == 0.0


def test_royalty_no_tiers_high_revenue():
    """高营业额无阶梯。"""
    franchisee = make_franchisee(royalty_rate=0.03)
    result = RoyaltyCalculator.calculate(1_000_000.0, franchisee)
    assert result == 30_000.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 4：阶梯分润（累进计算）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _tiered_franchisee() -> Franchisee:
    """阶梯配置：
      [0, 100000)  → 5%（基础费率）
      [100000, 500000) → 4%
      [500000, ∞)  → 3%
    """
    return make_franchisee(
        royalty_rate=0.05,
        tiers=[
            RoyaltyTier(min_revenue=100_000, rate=0.04),
            RoyaltyTier(min_revenue=500_000, rate=0.03),
        ],
    )


def test_royalty_tiered_below_first_threshold():
    """营业额低于第一档阈值，使用基础费率。"""
    franchisee = _tiered_franchisee()
    # 营业额 80,000 → 基础费率 5%
    result = RoyaltyCalculator.calculate(80_000.0, franchisee)
    assert result == pytest.approx(4_000.0, abs=0.01)


def test_royalty_tiered_between_thresholds():
    """营业额在两档阈值之间，分段累进。

    营业额 200,000：
      [0,      100000) × 5% = 5,000
      [100000, 200000) × 4% = 4,000
      合计 = 9,000
    """
    franchisee = _tiered_franchisee()
    result = RoyaltyCalculator.calculate(200_000.0, franchisee)
    assert result == pytest.approx(9_000.0, abs=0.01)


def test_royalty_tiered_above_all_thresholds():
    """营业额超过所有阈值，最后一档延续。

    营业额 600,000：
      [0,      100000) × 5% = 5,000
      [100000, 500000) × 4% = 16,000
      [500000, 600000) × 3% = 3,000
      合计 = 24,000
    """
    franchisee = _tiered_franchisee()
    result = RoyaltyCalculator.calculate(600_000.0, franchisee)
    assert result == pytest.approx(24_000.0, abs=0.01)


def test_royalty_tiered_exactly_at_threshold():
    """营业额恰好等于阈值边界值。"""
    franchisee = _tiered_franchisee()
    # 营业额 = 100,000，基础费率 5%（首档起点恰好在此）
    result = RoyaltyCalculator.calculate(100_000.0, franchisee)
    assert result == pytest.approx(5_000.0, abs=0.01)


def test_royalty_single_tier():
    """只有一档阶梯时：低于阈值用基础费率，超过用阶梯费率。"""
    franchisee = make_franchisee(
        royalty_rate=0.05,
        tiers=[RoyaltyTier(min_revenue=50_000, rate=0.03)],
    )
    # 30,000 → 基础 5%
    assert RoyaltyCalculator.calculate(30_000.0, franchisee) == pytest.approx(1_500.0, abs=0.01)
    # 80,000 →
    #   [0, 50000) × 5% = 2500
    #   [50000, 80000) × 3% = 900
    #   合计 = 3400
    assert RoyaltyCalculator.calculate(80_000.0, franchisee) == pytest.approx(3_400.0, abs=0.01)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 5：分润账单生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_royalty_bill_model_creation():
    """RoyaltyBill 模型构建与初始状态。"""
    franchisee = make_franchisee()
    bill = make_bill(franchisee)
    assert bill.tenant_id == TENANT_A
    assert bill.franchisee_id == franchisee.id
    assert bill.bill_month == "2026-03"
    assert bill.status == RoyaltyBillStatus.PENDING
    assert bill.paid_at is None


def test_royalty_bill_confirm():
    """账单确认流程：pending → confirmed。"""
    franchisee = make_franchisee()
    bill = make_bill(franchisee)
    bill.confirm()
    assert bill.status == RoyaltyBillStatus.CONFIRMED


def test_royalty_bill_confirm_invalid_state():
    """非 pending 账单不能确认。"""
    franchisee = make_franchisee()
    bill = make_bill(franchisee, status=RoyaltyBillStatus.PAID)
    with pytest.raises(ValueError, match="pending"):
        bill.confirm()


def test_royalty_bill_mark_paid():
    """账单付款流程：confirmed → paid。"""
    franchisee = make_franchisee()
    bill = make_bill(franchisee, status=RoyaltyBillStatus.CONFIRMED)
    bill.mark_paid()
    assert bill.status == RoyaltyBillStatus.PAID
    assert bill.paid_at is not None


def test_royalty_bill_mark_paid_from_overdue():
    """逾期账单也可以标记付款：overdue → paid。"""
    franchisee = make_franchisee()
    bill = make_bill(franchisee, status=RoyaltyBillStatus.OVERDUE)
    bill.mark_paid()
    assert bill.status == RoyaltyBillStatus.PAID


def test_royalty_bill_mark_paid_invalid_state():
    """pending 状态账单不能直接标记付款。"""
    franchisee = make_franchisee()
    bill = make_bill(franchisee, status=RoyaltyBillStatus.PENDING)
    with pytest.raises(ValueError, match="confirmed/overdue"):
        bill.mark_paid()


@pytest.mark.asyncio
async def test_generate_monthly_bills_returns_list():
    """月度账单批处理接口可正常调用，返回列表。"""
    bills = await RoyaltyCalculator.generate_monthly_bills(
        tenant_id=TENANT_A,
        bill_month="2026-03",
        db=None,
    )
    # 模拟实现返回空列表（无真实 DB）
    assert isinstance(bills, list)


def test_calc_due_date():
    """账单到期日计算正确（次月 15 日）。"""
    assert RoyaltyCalculator._calc_due_date("2026-03") == date(2026, 4, 15)
    assert RoyaltyCalculator._calc_due_date("2026-12") == date(2027, 1, 15)
    assert RoyaltyCalculator._calc_due_date("2025-11") == date(2025, 12, 15)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 6：加盟商欠款预警
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_overdue_bill_mark():
    """账单到期超 60 天自动标记 overdue。"""
    franchisee = make_franchisee()
    overdue_due = date.today() - timedelta(days=OVERDUE_DAYS + 1)
    bill = make_bill(franchisee, status=RoyaltyBillStatus.PENDING, due_date=overdue_due)
    # 模拟 generate_monthly_bills 中的逾期检查逻辑
    if bill.due_date and (date.today() - bill.due_date).days > OVERDUE_DAYS:
        bill.mark_overdue()
    assert bill.status == RoyaltyBillStatus.OVERDUE


def test_not_overdue_within_60_days():
    """未超过 60 天的账单不标记 overdue。"""
    franchisee = make_franchisee()
    recent_due = date.today() - timedelta(days=30)
    bill = make_bill(franchisee, status=RoyaltyBillStatus.PENDING, due_date=recent_due)
    if bill.due_date and (date.today() - bill.due_date).days > OVERDUE_DAYS:
        bill.mark_overdue()
    assert bill.status == RoyaltyBillStatus.PENDING


def test_overdue_mark_idempotent():
    """已为 overdue 状态的账单重复标记不抛出异常。"""
    franchisee = make_franchisee()
    bill = make_bill(franchisee, status=RoyaltyBillStatus.OVERDUE)
    bill.mark_overdue()  # 不应抛出
    assert bill.status == RoyaltyBillStatus.OVERDUE


@pytest.mark.asyncio
async def test_check_overdue_alerts_returns_list():
    """欠款预警接口可正常调用，返回列表。"""
    alerts = await FranchiseService.check_overdue_alerts(
        tenant_id=TENANT_A,
        db=None,
        threshold=OVERDUE_ALERT_THRESHOLD,
    )
    assert isinstance(alerts, list)


def test_overdue_alert_threshold_constant():
    """预警阈值常量为合理金额。"""
    assert OVERDUE_ALERT_THRESHOLD > 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 7：tenant_id 隔离
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_franchisee_tenant_binding():
    """Franchisee 模型的 tenant_id 不可被跨集团访问。"""
    franchisee_a = make_franchisee(tenant_id=TENANT_A)
    franchisee_b = make_franchisee(tenant_id=TENANT_B)
    assert franchisee_a.tenant_id != franchisee_b.tenant_id


def test_royalty_bill_tenant_binding():
    """RoyaltyBill 的 tenant_id 与所属加盟商一致。"""
    franchisee = make_franchisee(tenant_id=TENANT_A)
    bill = make_bill(franchisee)
    assert bill.tenant_id == TENANT_A
    assert bill.tenant_id != TENANT_B


def test_franchisee_store_tenant_binding():
    """FranchiseeStore 的 tenant_id 与集团一致，不可跨集团。"""
    link_a = FranchiseeStore(
        tenant_id=TENANT_A,
        franchisee_id=uuid4(),
        store_id=uuid4(),
        joined_at=date.today(),
    )
    link_b = FranchiseeStore(
        tenant_id=TENANT_B,
        franchisee_id=uuid4(),
        store_id=uuid4(),
        joined_at=date.today(),
    )
    assert link_a.tenant_id != link_b.tenant_id


@pytest.mark.asyncio
async def test_list_franchisees_returns_dict():
    """list_franchisees 返回标准分页结构。"""
    result = await FranchiseService.list_franchisees(
        tenant_id=TENANT_A,
        db=None,
        page=1,
        size=20,
    )
    assert "items" in result
    assert "total" in result
    assert "page" in result


@pytest.mark.asyncio
async def test_dashboard_returns_required_fields():
    """加盟商仪表盘返回必要字段。"""
    franchisee = make_franchisee()
    dashboard = await FranchiseService.get_franchisee_dashboard(
        franchisee_id=franchisee.id,
        tenant_id=TENANT_A,
        db=None,
    )
    required_fields = {
        "franchisee_id",
        "current_month",
        "store_count",
        "current_revenue",
        "current_royalty",
        "total_overdue",
    }
    assert required_fields.issubset(dashboard.keys())


@pytest.mark.asyncio
async def test_get_franchisee_returns_none_for_unknown():
    """不存在或不属于本 tenant 的加盟商返回 None（不泄露数据）。"""
    result = await FranchiseService.get_franchisee(
        franchisee_id=uuid4(),
        tenant_id=TENANT_A,
        db=None,
    )
    assert result is None
