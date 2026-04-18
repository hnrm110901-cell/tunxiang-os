"""
多国合规 service 单元测试
覆盖：
  1) 香港 MPF：最高月薪 30,000 HKD 封顶
  2) 香港低薪员工部分免缴（<7,100）
  3) 新加坡 CPF：<55 岁员工 20% 雇主 17%
  4) 新加坡年龄分段：65+ 降至 7.5%/7.5%
  5) 内地返回占位（提示走本地引擎）
"""

import sys
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest  # noqa: E402

from src.services.country_compliance_service import (  # noqa: E402
    HK_MPF,
    SG_CPF,
    CountryComplianceService,
)


def _mk_db():
    db = MagicMock()
    db.get = AsyncMock()
    db.execute = AsyncMock()
    return db


def test_hk_mpf_cap_at_30k():
    svc = CountryComplianceService(_mk_db())
    # 月薪 50,000 HKD = 5,000,000 分 → MPF 基数应封顶至 3,000,000
    r = svc.calc_hk(gross_fen=50000_00)
    assert r.employee_contribution_fen == int(30000_00 * HK_MPF["employee_rate"])
    assert r.employer_contribution_fen == int(30000_00 * HK_MPF["employer_rate"])
    assert r.currency == "HKD"
    assert r.country_code == "HK"


def test_hk_mpf_low_wage_employee_exempt():
    svc = CountryComplianceService(_mk_db())
    # 月薪 5000 HKD < 7100 → 员工部分免缴，雇主仍需缴
    r = svc.calc_hk(gross_fen=5000_00)
    assert r.employee_contribution_fen == 0
    # 雇主按实际基数（非封顶）
    assert r.employer_contribution_fen == int(5000_00 * HK_MPF["employer_rate"])


def test_sg_cpf_under_55():
    svc = CountryComplianceService(_mk_db())
    r = svc.calc_sg(gross_fen=5000_00, age=30)
    # 基数 5000 < 上限 6800 → 按 5000 算
    assert r.employee_contribution_fen == int(5000_00 * SG_CPF["under_55"]["employee_rate"])
    assert r.employer_contribution_fen == int(5000_00 * SG_CPF["under_55"]["employer_rate"])
    assert r.currency == "SGD"


def test_sg_cpf_cap_at_6800():
    svc = CountryComplianceService(_mk_db())
    # 月薪 10,000 SGD → 基数封顶 6800
    r = svc.calc_sg(gross_fen=10000_00, age=30)
    assert r.employee_contribution_fen == int(6800_00 * SG_CPF["under_55"]["employee_rate"])


def test_sg_cpf_over_65_lower_rate():
    svc = CountryComplianceService(_mk_db())
    r = svc.calc_sg(gross_fen=5000_00, age=70)
    assert r.employee_contribution_fen == int(5000_00 * SG_CPF["over_65"]["employee_rate"])
    assert r.employer_contribution_fen == int(5000_00 * SG_CPF["over_65"]["employer_rate"])


@pytest.mark.asyncio
async def test_calc_by_country_cn_returns_placeholder():
    emp = MagicMock()
    emp.locale_code = "zh-CN"
    emp.daily_wage_standard_fen = 30000  # 300/日 × 22 = 6600 元
    emp.birth_date = None
    db = _mk_db()
    db.get = AsyncMock(return_value=emp)
    svc = CountryComplianceService(db)
    r = await svc.calc_by_country("EMP001", "2026-04")
    assert r.country_code == "CN"
    assert "payroll_service" in r.details.get("note", "")


def test_to_dict_has_yuan_fields():
    svc = CountryComplianceService(_mk_db())
    r = svc.calc_hk(gross_fen=20000_00)
    d = r.to_dict()
    # 符合 Rule 6：_yuan 伴生
    assert "gross_yuan" in d
    assert "net_yuan" in d
    assert "tax_yuan" in d
    assert d["gross_yuan"] == 20000.0
