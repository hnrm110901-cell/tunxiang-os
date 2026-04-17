"""
D12 个税累计预扣法 — 单元测试
覆盖：
  1) 7 级税率表切换（月收入 5k/10k/50k/100k）
  2) 基本减除费用 5000×月数
  3) 专项附加扣除（累计扣）
  4) 中途入职（tax_month_num=1 起算）
  5) 累计预扣逻辑 — 跨月份税额正确
"""

# ── mock src.core.config 以便在无 pydantic_settings 校验环境下可独立运行 ──
import sys
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest

from src.services.personal_tax_service import (
    PersonalTaxService,
    compute_cumulative_tax_fen,
)


# ── 1) 税率表切换 ─────────────────────────────────────────────
class TestTaxBrackets:
    """累计应纳税所得额 → 累计税额计算正确性"""

    def test_bracket_3pct(self):
        # 累计 20,000 元 → 3% → 600 元
        tax, rate, quick = compute_cumulative_tax_fen(20_000 * 100)
        assert tax == 600 * 100
        assert rate == 0.03
        assert quick == 0

    def test_bracket_10pct(self):
        # 累计 50,000 元 → 50000*10% - 2520 = 2480 元
        tax, rate, quick = compute_cumulative_tax_fen(50_000 * 100)
        assert tax == 2480 * 100
        assert rate == 0.10
        assert quick == 2520 * 100

    def test_bracket_20pct(self):
        # 累计 200,000 元 → 200000*20% - 16920 = 23080 元
        tax, rate, _ = compute_cumulative_tax_fen(200_000 * 100)
        assert tax == 23_080 * 100
        assert rate == 0.20

    def test_bracket_25pct(self):
        # 累计 350,000 元 → 350000*25% - 31920 = 55580 元
        tax, rate, _ = compute_cumulative_tax_fen(350_000 * 100)
        assert tax == 55_580 * 100
        assert rate == 0.25

    def test_bracket_30pct(self):
        # 累计 500,000 元 → 500000*30% - 52920 = 97080 元
        tax, rate, _ = compute_cumulative_tax_fen(500_000 * 100)
        assert tax == 97_080 * 100
        assert rate == 0.30

    def test_bracket_45pct(self):
        # 累计 1,200,000 元 → 1200000*45% - 181920 = 358080 元
        tax, rate, _ = compute_cumulative_tax_fen(1_200_000 * 100)
        assert tax == 358_080 * 100
        assert rate == 0.45

    def test_zero_taxable(self):
        tax, rate, quick = compute_cumulative_tax_fen(0)
        assert tax == 0
        assert rate == 0.0
        assert quick == 0

    def test_negative_taxable(self):
        """负值应按 0 处理"""
        tax, _, _ = compute_cumulative_tax_fen(-1000)
        assert tax == 0


# ── 2) 月度个税场景（经典样例）─────────────────────────────────
class TestMonthlyScenarios:
    """
    累计预扣法：
      月收入 10000，社保个人 1500，无专项附加
      月度应纳税所得 = 10000 - 5000 - 1500 = 3500
      累计到第 n 月的应纳税所得 = 3500n
      前 10 个月都落在 3% 档(<=36000)，第11月跨档
    """

    def test_income_5000_no_tax(self):
        """月收入 5000 → 扣除后为 0 → 无税"""
        tax, _, _ = compute_cumulative_tax_fen(0)
        assert tax == 0

    def test_single_month_10k(self):
        # 累计 3500 元 → 3% → 105 元
        tax, rate, _ = compute_cumulative_tax_fen(3500 * 100)
        assert tax == 105 * 100
        assert rate == 0.03

    def test_single_month_50k_first_month(self):
        """月收入 50000, 社保 5000 → 应税 40000 → 累计 40000 元 → 10% - 2520 = 1480 元"""
        taxable_yuan = 50_000 - 5_000 - 5_000  # income - 起征点 - 社保
        tax, rate, _ = compute_cumulative_tax_fen(taxable_yuan * 100)
        assert tax == 1480 * 100
        assert rate == 0.10

    def test_single_month_100k_first_month(self):
        """月收入 100000, 社保 8000 → 应税 87000 → 10% - 2520 = 6180 元"""
        taxable_yuan = 100_000 - 5_000 - 8_000
        tax, rate, _ = compute_cumulative_tax_fen(taxable_yuan * 100)
        assert tax == 6180 * 100
        assert rate == 0.10


# ── 3) 累计预扣 — 用 PersonalTaxService 做端到端计算（mock DB）──
@pytest.mark.asyncio
class TestCumulativeWithholding:
    """mock 数据库 session 验证累计逻辑"""

    def _mock_db_empty(self):
        """模拟一个空数据库：无历史 PersonalTaxRecord、无 SpecialAdditionalDeduction"""
        db = AsyncMock()

        # 每次 execute() 返回空 scalars 列表
        async def _execute(_stmt):
            result = MagicMock()
            result.scalar.return_value = 0  # 专项附加 sum
            scalars = MagicMock()
            scalars.all.return_value = []
            result.scalars.return_value = scalars
            return result

        db.execute = _execute
        db.flush = AsyncMock()
        db.add = MagicMock()
        return db

    async def test_january_10k_income(self):
        """1月，月收入10000，社保1500 → 累计应税3500 → 3% → 105元"""
        service = PersonalTaxService(store_id="S001")
        db = self._mock_db_empty()
        detail = await service.calc_monthly_tax(
            db,
            employee_id="E001",
            pay_month="2025-01",
            gross_fen=10_000 * 100,
            si_personal_fen=1_500 * 100,
        )
        assert detail["current_month_tax_fen"] == 105 * 100
        assert detail["tax_month_num"] == 1
        assert detail["rate"] == 0.03

    async def test_mid_year_hire_starts_at_month_1(self):
        """中途入职：第一次申报 tax_month_num 应为 1，基本减除也只算 1 个 5000"""
        service = PersonalTaxService(store_id="S001")
        db = self._mock_db_empty()
        detail = await service.calc_monthly_tax(
            db,
            employee_id="E002",
            pay_month="2025-07",  # 7月入职
            gross_fen=20_000 * 100,
            si_personal_fen=2_000 * 100,
        )
        # 累计应税 = 20000 - 5000 - 2000 = 13000 → 3% → 390 元
        assert detail["tax_month_num"] == 1
        assert detail["current_month_tax_fen"] == 390 * 100


# ── 4) 专项附加扣除 — 使用纯函数验证 ──────────────────────────
class TestSpecialDeduction:
    """专项附加扣除会额外减少累计应税所得"""

    def test_with_2000_child_education(self):
        """月收入10000, 社保1500, 子女教育2000 → 应税 1500 → 3% → 45元"""
        taxable_yuan = 10_000 - 5_000 - 1_500 - 2_000
        tax, _, _ = compute_cumulative_tax_fen(taxable_yuan * 100)
        assert tax == 45 * 100

    def test_cumulative_2months_with_special(self):
        """2月累计 = (10000-5000-1500-2000)*2 = 3000 → 3% → 90元"""
        cumulative = (10_000 - 5_000 - 1_500 - 2_000) * 2
        tax, _, _ = compute_cumulative_tax_fen(cumulative * 100)
        assert tax == 90 * 100


# ── 5) 税率表边界 ─────────────────────────────────────────────
class TestBracketBoundaries:
    def test_exact_36000(self):
        """累计刚好 36000 → 3% → 1080 元（仍按3%档）"""
        tax, rate, _ = compute_cumulative_tax_fen(36_000 * 100)
        assert tax == 1080 * 100
        assert rate == 0.03

    def test_36001_crosses_to_10pct(self):
        """36001 → 10% - 2520 → 1080.1 元"""
        tax, rate, _ = compute_cumulative_tax_fen(36_001 * 100)
        assert rate == 0.10
        # 36001*0.1 - 2520 = 1080.10 元
        assert tax == int(round((36_001 * 0.10 - 2520) * 100))


