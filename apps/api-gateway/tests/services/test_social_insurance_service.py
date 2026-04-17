"""
D12 社保公积金计算引擎 — 单元测试
覆盖：
  1) 基数超上限裁剪 (base_ceiling_fen)
  2) 基数低于下限裁剪 (base_floor_fen)
  3) 单险种禁用 (has_xxx=False)
  4) 公积金个性化覆盖
"""

import sys
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest

from src.models.social_insurance import (
    EmployeeSocialInsurance,
    InsuranceType,
    SocialInsuranceConfig,
)
from src.services.social_insurance_service import (
    SocialInsuranceService,
    _clip_base_fen,
    _pct_to_fen,
)


# ── 纯函数：基数裁剪 ──────────────────────────────────────────
class TestClipBase:
    def test_within_range(self):
        assert _clip_base_fen(10000 * 100, 4000 * 100, 20000 * 100) == 10000 * 100

    def test_above_ceiling(self):
        assert _clip_base_fen(50000 * 100, 4000 * 100, 20000 * 100) == 20000 * 100

    def test_below_floor(self):
        assert _clip_base_fen(2000 * 100, 4000 * 100, 20000 * 100) == 4000 * 100

    def test_zero_bounds_passthrough(self):
        """未配置上下限时应原样返回"""
        assert _clip_base_fen(10000 * 100, 0, 0) == 10000 * 100


class TestPctToFen:
    def test_basic(self):
        # 10000 元 × 8% = 800 元 = 80000 分
        assert _pct_to_fen(10000 * 100, Decimal("8.00")) == 80000

    def test_none_pct_returns_zero(self):
        assert _pct_to_fen(10000 * 100, None) == 0

    def test_float_pct(self):
        assert _pct_to_fen(10000 * 100, 2.5) == 25000


# ── 构造 fake config / emp_si ────────────────────────────────
def _make_config(
    floor_fen=4_000 * 100,
    ceiling_fen=30_000 * 100,
    pension_er=Decimal("16.00"),
    pension_ee=Decimal("8.00"),
    medical_er=Decimal("8.00"),
    medical_ee=Decimal("2.00"),
    unemp_er=Decimal("0.70"),
    unemp_ee=Decimal("0.30"),
    injury_er=Decimal("0.20"),
    maternity_er=Decimal("0.70"),
    hf_er=Decimal("12.00"),
    hf_ee=Decimal("12.00"),
):
    cfg = SocialInsuranceConfig()
    cfg.region_code = "430100"
    cfg.region_name = "长沙市"
    cfg.effective_year = 2025
    cfg.base_floor_fen = floor_fen
    cfg.base_ceiling_fen = ceiling_fen
    cfg.pension_employer_pct = pension_er
    cfg.pension_employee_pct = pension_ee
    cfg.medical_employer_pct = medical_er
    cfg.medical_employee_pct = medical_ee
    cfg.unemployment_employer_pct = unemp_er
    cfg.unemployment_employee_pct = unemp_ee
    cfg.injury_employer_pct = injury_er
    cfg.maternity_employer_pct = maternity_er
    cfg.housing_fund_employer_pct = hf_er
    cfg.housing_fund_employee_pct = hf_ee
    return cfg


def _make_emp_si(
    personal_base_fen=10_000 * 100,
    has_pension=True,
    has_medical=True,
    has_unemployment=True,
    has_injury=True,
    has_maternity=True,
    has_housing_fund=True,
    hf_override=None,
):
    esi = EmployeeSocialInsurance()
    esi.id = "si1"
    esi.store_id = "S001"
    esi.employee_id = "E001"
    esi.config_id = "cfg1"
    esi.effective_year = 2025
    esi.personal_base_fen = personal_base_fen
    esi.has_pension = has_pension
    esi.has_medical = has_medical
    esi.has_unemployment = has_unemployment
    esi.has_injury = has_injury
    esi.has_maternity = has_maternity
    esi.has_housing_fund = has_housing_fund
    esi.housing_fund_pct_override = hf_override
    esi.is_active = True
    return esi


def _mock_db_with(emp_si, config):
    """模拟 db.execute() —— 第一次返回 emp_si，第二次返回 config"""
    db = AsyncMock()

    call_order = {"n": 0}

    async def _execute(_stmt):
        call_order["n"] += 1
        result = MagicMock()
        if call_order["n"] == 1:
            result.scalar_one_or_none.return_value = emp_si
        else:
            result.scalar_one_or_none.return_value = config
        return result

    db.execute = _execute
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


# ── 1) 标准用例 ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_standard_calc():
    """基数 10000 元、长沙默认费率：
    养老企业 1600 / 个人 800；公积金 1200/1200 …
    """
    service = SocialInsuranceService(store_id="S001")
    emp_si = _make_emp_si(personal_base_fen=10_000 * 100)
    cfg = _make_config()
    db = _mock_db_with(emp_si, cfg)

    detail = await service.calc_monthly_si(db, "E001", "2025-03")

    assert detail["base_fen"] == 10_000 * 100
    assert detail["pension"]["employer"] == 1600 * 100
    assert detail["pension"]["employee"] == 800 * 100
    assert detail["medical"]["employer"] == 800 * 100
    assert detail["medical"]["employee"] == 200 * 100
    assert detail["housing_fund"]["employee"] == 1200 * 100
    # 总和验算
    # 企业: 1600+800+70+20+70+1200 = 3760
    assert detail["total_employer_fen"] == 3760 * 100


# ── 2) 基数超上限 ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_base_above_ceiling_clipped():
    """个人基数 50000，超过上限 30000，应按 30000 计算养老个人 = 2400 元"""
    service = SocialInsuranceService(store_id="S001")
    emp_si = _make_emp_si(personal_base_fen=50_000 * 100)
    cfg = _make_config(ceiling_fen=30_000 * 100)
    db = _mock_db_with(emp_si, cfg)

    detail = await service.calc_monthly_si(db, "E001", "2025-03")
    assert detail["base_fen"] == 30_000 * 100
    # 养老个人 = 30000 * 8% = 2400 元
    assert detail["pension"]["employee"] == 2400 * 100


# ── 3) 基数低于下限 ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_base_below_floor_clipped():
    service = SocialInsuranceService(store_id="S001")
    emp_si = _make_emp_si(personal_base_fen=2_000 * 100)
    cfg = _make_config(floor_fen=4_000 * 100)
    db = _mock_db_with(emp_si, cfg)

    detail = await service.calc_monthly_si(db, "E001", "2025-03")
    assert detail["base_fen"] == 4_000 * 100
    # 养老个人 = 4000 * 8% = 320 元
    assert detail["pension"]["employee"] == 320 * 100


# ── 4) 单险种禁用 ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_housing_fund_disabled():
    """禁用公积金：housing_fund 企业/个人 均为 0"""
    service = SocialInsuranceService(store_id="S001")
    emp_si = _make_emp_si(personal_base_fen=10_000 * 100, has_housing_fund=False)
    cfg = _make_config()
    db = _mock_db_with(emp_si, cfg)

    detail = await service.calc_monthly_si(db, "E001", "2025-03")
    assert detail["housing_fund"]["employer"] == 0
    assert detail["housing_fund"]["employee"] == 0
    # 企业合计 = 1600+800+70+20+70 = 2560
    assert detail["total_employer_fen"] == 2560 * 100


@pytest.mark.asyncio
async def test_pension_disabled():
    service = SocialInsuranceService(store_id="S001")
    emp_si = _make_emp_si(personal_base_fen=10_000 * 100, has_pension=False)
    cfg = _make_config()
    db = _mock_db_with(emp_si, cfg)

    detail = await service.calc_monthly_si(db, "E001", "2025-03")
    assert detail["pension"]["employer"] == 0
    assert detail["pension"]["employee"] == 0


# ── 5) 公积金个性化覆盖 ───────────────────────────────────────
@pytest.mark.asyncio
async def test_housing_fund_override():
    """override=5% 时，即便配置默认12%，也应按 5% 计"""
    service = SocialInsuranceService(store_id="S001")
    emp_si = _make_emp_si(
        personal_base_fen=10_000 * 100,
        hf_override=Decimal("5.00"),
    )
    cfg = _make_config(hf_er=Decimal("12.00"), hf_ee=Decimal("12.00"))
    db = _mock_db_with(emp_si, cfg)

    detail = await service.calc_monthly_si(db, "E001", "2025-03")
    # 10000 * 5% = 500
    assert detail["housing_fund"]["employee"] == 500 * 100
    assert detail["housing_fund"]["employer"] == 500 * 100


# ── 6) 未参保兜底 ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_no_enrollment_returns_zero():
    service = SocialInsuranceService(store_id="S001")
    db = AsyncMock()

    async def _execute(_stmt):
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    db.execute = _execute

    detail = await service.calc_monthly_si(db, "E999", "2025-03")
    assert detail["base_fen"] == 0
    assert detail["total_employer_fen"] == 0
    assert detail["total_employee_fen"] == 0
