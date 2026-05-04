"""加盟分润计算器 Tier 1 测试（CLAUDE.md §17 + §20）

零容忍：金额计算必须用分（int）+ Decimal 中间精度，禁止 float 参与。

真实餐厅场景（非边界值）：
  01 test_100w_revenue_5pct_royalty_no_float_error
       — 月营收 1 亿分（100 万元）× 5% = 5 千万分（5 万元），不能有 4999999...
  02 test_tiered_revenue_segment_boundary_precision
       — 阶梯费率在 100w / 200w / 500w 边界上分段精确，无 float 漂移
  03 test_management_fee_calculation_in_fen
       — 管理费按分计算，叠加分润后总额精确等于二者之和
  04 test_zero_revenue_zero_fee
       — 零营收返回零分（int 0），不返回 0.0
  05 test_partial_payment_balance_correct
       — 部分付款（按分）后欠款余额精确至分

Tier 1 验收标准：
  - calculate_fen() 入参/出参全部为 int（分）
  - 内部用 Decimal（精度 ≥ 6 位）做中间计算
  - 收尾 quantize ROUND_HALF_UP 到分（int）
  - 100 万元 × 5% 必须精确等于 5 万元（5_000_000 分），不允许任何 float 误差
"""

from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# 路径注入：让 services/tx-org/src 与仓库根目录可被 import
# ──────────────────────────────────────────────────────────────────────────────
_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ROOT = os.path.abspath(os.path.join(_SRC, "..", "..", ".."))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from models.franchise import (  # noqa: E402
    Franchisee,
    FranchiseeStatus,
    RoyaltyTier,
)
from services.royalty_calculator import RoyaltyCalculator  # noqa: E402

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  固定数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TENANT_ID = uuid4()


def make_franchisee(
    royalty_rate: float = 0.05,
    tiers: list[RoyaltyTier] | None = None,
    management_fee_fen: int = 0,
) -> Franchisee:
    f = Franchisee(
        tenant_id=TENANT_ID,
        franchisee_name="徐记海鲜某加盟店",
        contact_name="王老板",
        contact_phone="13800138000",
        contract_start=date(2024, 1, 1),
        contract_end=date(2027, 12, 31),
        royalty_rate=royalty_rate,
        royalty_tiers=tiers or [],
        status=FranchiseeStatus.ACTIVE,
    )
    object.__setattr__(f, "management_fee_fen", management_fee_fen)
    return f


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 1：100 万元 × 5% 必须精确，禁止 float 误差
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.tier1
def test_100w_revenue_5pct_royalty_no_float_error():
    """月营收 100 万元（1 亿分）× 5% 应得正好 5 万元（500 万分）。

    根因复现：float 表示下，0.05 * 100_000_000 在某些路径会得到 4999999.999...，
              导致与手工对账差 1 分，触发加盟商投诉。

    Tier 1 验收：calculate_fen() 必须返回精确的 int 5_000_000，不允许任何漂移。
    """
    franchisee = make_franchisee(royalty_rate=0.05)
    revenue_fen = 100_000_000  # 100 万元 = 1 亿分

    result_fen = RoyaltyCalculator.calculate_fen(revenue_fen, franchisee)

    assert isinstance(result_fen, int), (
        f"calculate_fen() 必须返回 int（分），实际返回 {type(result_fen).__name__}"
    )
    assert result_fen == 5_000_000, (
        f"100 万元 × 5% 必须精确等于 5 万元（500 万分），实际 {result_fen} 分。"
        " 任何漂移都会触发对账争议（徐记海鲜验收门槛）。"
    )


@pytest.mark.tier1
def test_500w_revenue_3pct_royalty_no_float_error():
    """月营收 500 万元 × 3% 应得正好 15 万元（1500 万分）。

    更高营收 + 更小费率 → float 漂移概率更高。
    """
    franchisee = make_franchisee(royalty_rate=0.03)
    revenue_fen = 500_000_000  # 500 万元

    result_fen = RoyaltyCalculator.calculate_fen(revenue_fen, franchisee)

    assert isinstance(result_fen, int)
    assert result_fen == 15_000_000, f"500 万元 × 3% 必须 = 15 万元（1500 万分），实际 {result_fen}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 2：阶梯费率边界精确（100w / 200w / 500w）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.tier1
def test_tiered_revenue_segment_boundary_precision():
    """阶梯：[0,100w)→5%, [100w,500w)→4%, [500w,∞)→3%

    案例 1：营收 100 万元（恰好在第一档边界）
      [0, 100w) × 5% = 5 万元 = 5_000_000 分

    案例 2：营收 200 万元（横跨两档）
      [0, 100w) × 5% = 5 万元   = 5_000_000 分
      [100w, 200w) × 4% = 4 万元 = 4_000_000 分
      合计 = 9 万元 = 9_000_000 分

    案例 3：营收 600 万元（横跨三档）
      [0, 100w) × 5% = 5 万元    = 5_000_000 分
      [100w, 500w) × 4% = 16 万元 = 16_000_000 分
      [500w, 600w) × 3% = 3 万元  = 3_000_000 分
      合计 = 24 万元 = 24_000_000 分
    """
    franchisee = make_franchisee(
        royalty_rate=0.05,
        tiers=[
            RoyaltyTier(min_revenue=1_000_000, rate=0.04),  # 100 万元
            RoyaltyTier(min_revenue=5_000_000, rate=0.03),  # 500 万元
        ],
    )

    # 案例 1：100 万元 = 1 亿分
    r1 = RoyaltyCalculator.calculate_fen(100_000_000, franchisee)
    assert r1 == 5_000_000, f"边界 100 万元应得 5 万元，实际 {r1}"

    # 案例 2：200 万元 = 2 亿分
    r2 = RoyaltyCalculator.calculate_fen(200_000_000, franchisee)
    assert r2 == 9_000_000, f"跨两档 200 万元应得 9 万元，实际 {r2}"

    # 案例 3：600 万元 = 6 亿分
    r3 = RoyaltyCalculator.calculate_fen(600_000_000, franchisee)
    assert r3 == 24_000_000, f"跨三档 600 万元应得 24 万元，实际 {r3}"


@pytest.mark.tier1
def test_tiered_segment_sum_equals_total_revenue_x_effective_rate():
    """阶梯分段加和 = ∑(段宽 × 段费率)，整型精确。

    任意营收 X 不能因为 float 累加误差导致 ±1 分。
    """
    franchisee = make_franchisee(
        royalty_rate=0.05,
        tiers=[
            RoyaltyTier(min_revenue=1_000_000, rate=0.04),
            RoyaltyTier(min_revenue=5_000_000, rate=0.03),
        ],
    )
    # 营收 350 万元（横跨两段）
    # [0, 100w) × 5% = 5 万元
    # [100w, 350w) × 4% = 250w × 4% = 10 万元
    # 合计 = 15 万元 = 15_000_000 分
    r = RoyaltyCalculator.calculate_fen(350_000_000, franchisee)
    assert r == 15_000_000, f"350 万元应得 15 万元，实际 {r}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 3：管理费按分叠加
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.tier1
def test_management_fee_calculation_in_fen():
    """月度账单 = 分润金额（分）+ 管理费（分），全程 int。

    场景：徐记海鲜某加盟店
      - 月营收 80 万元 = 80_000_000 分
      - 基础费率 5%
      - 固定管理费 3000 元 = 300_000 分
      预期：分润 4 万元 + 管理费 3000 元 = 4 万 3 千元 = 4_300_000 分
    """
    franchisee = make_franchisee(royalty_rate=0.05, management_fee_fen=300_000)
    revenue_fen = 80_000_000

    royalty_fen = RoyaltyCalculator.calculate_fen(revenue_fen, franchisee)
    assert royalty_fen == 4_000_000, f"80w × 5% 应得 4 万元（4_000_000 分），实际 {royalty_fen}"

    total_due_fen = royalty_fen + franchisee.management_fee_fen  # type: ignore[attr-defined]
    assert total_due_fen == 4_300_000, f"分润 + 管理费应等于 4_300_000 分，实际 {total_due_fen}"
    # 必须保持 int 类型（避免 float 渗透）
    assert isinstance(total_due_fen, int)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 4：零营收零费用
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.tier1
def test_zero_revenue_zero_fee():
    """零营收（新店当月无开业）返回 int 0，不返回 0.0。"""
    franchisee = make_franchisee(royalty_rate=0.05)
    result = RoyaltyCalculator.calculate_fen(0, franchisee)
    assert result == 0
    assert isinstance(result, int), f"零营收必须返回 int 0，实际类型 {type(result).__name__}"


@pytest.mark.tier1
def test_negative_revenue_returns_zero_fen():
    """负营收（退款超收异常）返回 0 分（防御性）。"""
    franchisee = make_franchisee(royalty_rate=0.05)
    result = RoyaltyCalculator.calculate_fen(-1000, franchisee)
    assert result == 0
    assert isinstance(result, int)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 5：部分付款后余额精确
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.tier1
def test_partial_payment_balance_correct():
    """加盟商分 3 次付清月度账单，每次扣减后余额精确至分。

    场景：
      - 月度账单 = 分润 5 万元 + 管理费 3000 元 = 53_000 元 = 5_300_000 分
      - 第 1 次付 2 万元 = 2_000_000 分 → 余 3_300_000 分
      - 第 2 次付 2 万元 = 2_000_000 分 → 余 1_300_000 分
      - 第 3 次付 13_000 元 = 1_300_000 分 → 余 0 分
    """
    franchisee = make_franchisee(royalty_rate=0.05, management_fee_fen=300_000)
    revenue_fen = 100_000_000  # 100 万元

    royalty_fen = RoyaltyCalculator.calculate_fen(revenue_fen, franchisee)
    total_due_fen = royalty_fen + franchisee.management_fee_fen  # type: ignore[attr-defined]
    assert total_due_fen == 5_300_000

    balance = total_due_fen
    for paid_fen in [2_000_000, 2_000_000, 1_300_000]:
        balance -= paid_fen
        assert isinstance(balance, int)

    assert balance == 0, f"分次付清后余额必须为 0 分，实际 {balance}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 6：calculate_fen 内部用 Decimal（隔离 float 误差源）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.tier1
def test_calculate_fen_uses_decimal_for_high_precision_rates():
    """高精度费率（如 4.5%）下，10 亿分（1000 万元）× 4.5% 必须精确。

    验证内部用 Decimal 而非 float：
      Decimal("0.045") × 1_000_000_000 = 45_000_000.000  → 4500 万分（精确）
      float 0.045 × 1_000_000_000 = 45000000.00000001     → ±1 漂移
    """
    franchisee = make_franchisee(royalty_rate=0.045)
    revenue_fen = 1_000_000_000  # 1000 万元

    result = RoyaltyCalculator.calculate_fen(revenue_fen, franchisee)

    assert result == 45_000_000, f"1000w × 4.5% 应得 45 万元（4500 万分），实际 {result}"
    assert isinstance(result, int)


@pytest.mark.tier1
def test_calculate_fen_rounding_half_up():
    """收尾舍入策略：ROUND_HALF_UP（金融业惯例，非银行家舍入）。

    场景：单价导致末位 0.5 分时，向上进位。
      revenue = 1 分，rate = 0.5 → 0.5 分 → 进位为 1 分
    """
    franchisee = make_franchisee(royalty_rate=0.5)
    # 1 分 × 50% = 0.5 分，按 ROUND_HALF_UP 应进位为 1 分
    result = RoyaltyCalculator.calculate_fen(1, franchisee)
    assert result == 1, f"0.5 分按 ROUND_HALF_UP 应进位为 1，实际 {result}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 7：与旧 float API 兼容（保留 calculate(yuan) → yuan 用于回归）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.tier1
def test_legacy_calculate_yuan_still_works_via_fen_path():
    """旧的 calculate(yuan) API 必须仍可用（暂不删除），但内部走 calculate_fen。

    100 万元 × 5% 旧 API 必须返回 5 万元（float 5_0000.0），即 calculate_fen
    转回元后无误差。
    """
    franchisee = make_franchisee(royalty_rate=0.05)
    # 旧入参：元（float）；旧出参：元（float）
    legacy = RoyaltyCalculator.calculate(1_000_000.0, franchisee)
    assert legacy == 50_000.0, f"旧 API 100 万元 × 5% 必须 = 5 万元，实际 {legacy}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 8：Decimal 精度策略验证（防止内部退化为 float）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.tier1
def test_no_float_intermediate_in_high_value_tiered_calculation():
    """超大营收 + 阶梯：1 亿元营收阶梯计算下不允许 float 漂移。

    阶梯：[0,100w)→5%, [100w,500w)→4%, [500w,∞)→3%
    营收 1 亿元 = 10_000_000_000 分：
      [0, 100w)        × 5% = 5 万元    = 5_000_000 分
      [100w, 500w)     × 4% = 16 万元   = 16_000_000 分
      [500w, 1 亿)     × 3% = 285 万元  = 285_000_000 分（9500w × 3%）
      合计 = 306 万元 = 306_000_000 分
    """
    franchisee = make_franchisee(
        royalty_rate=0.05,
        tiers=[
            RoyaltyTier(min_revenue=1_000_000, rate=0.04),
            RoyaltyTier(min_revenue=5_000_000, rate=0.03),
        ],
    )
    revenue_fen = 10_000_000_000  # 1 亿元
    result = RoyaltyCalculator.calculate_fen(revenue_fen, franchisee)
    assert result == 306_000_000, (
        f"1 亿元阶梯应精确得 306 万元（306_000_000 分），实际 {result}。"
        f" 差额 {result - 306_000_000} 分会触发对账失败。"
    )
    assert isinstance(result, int)


@pytest.mark.tier1
def test_decimal_quantize_used_internally_smoke():
    """烟雾测试：calculate_fen 输出必须可被 Decimal 精确表示（无 float 渗透）。"""
    franchisee = make_franchisee(royalty_rate=0.0375)  # 3.75%（特殊费率）
    revenue_fen = 88_888_800  # 88.8888 万元
    result = RoyaltyCalculator.calculate_fen(revenue_fen, franchisee)
    # 88_888_800 × 0.0375 = 3_333_330（精确）
    expected = int(
        (Decimal(revenue_fen) * Decimal("0.0375")).quantize(Decimal("1"))
    )
    assert result == expected, f"3.75% 费率精确计算失败，期望 {expected}，实际 {result}"
