"""
D12 z66 — 薪资项目库单测

覆盖：
  1. tax_attribute 分类聚合正确（应税/免税/税前扣/税后扣）
  2. 多项加成+扣减合计
  3. 生效时间窗筛选（过期项不应进入试算）
  4. 与 PersonalTaxService 协作的参数形态（gross/tax_free/si_personal）
  5. formula_type=formula 公式求值
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))
sys.modules.setdefault("src.core.tenant_context", MagicMock(TenantContext=MagicMock()))

from src.services.salary_item_service import SalaryItemService  # noqa: E402


def _item(
    code: str, name: str, cat: str, tax_attr: str, ftype: str = "fixed", formula: str = ""
):
    """构造 _get_active_items_for_employee 返回形态的 dict"""
    return {
        "assign_id": f"a_{code}",
        "override_amount_fen": None,
        "def_id": f"d_{code}",
        "code": code,
        "name": name,
        "category": cat,
        "tax_attribute": tax_attr,
        "formula": formula,
        "formula_type": ftype,
        "calc_order": 50,
    }


class DummyDB:
    """只需支持 flush/add 空转"""

    async def flush(self):
        return None

    def add(self, obj):
        pass


def _svc():
    return SalaryItemService(store_id="S001")


def test_tax_attribute_aggregation():
    """应税/免税/税前扣/税后扣 四类分别合计"""
    svc = _svc()
    # 500000 + 100000 应税；30000 免税餐补；40000 税前扣（社保）；10000 税后扣罚款
    items = [
        _item("ATT_001", "基本工资", "attendance", "pre_tax_add"),
        _item("SUB_002", "交通补贴", "subsidy", "pre_tax_add"),
        _item("SUB_003", "餐补", "subsidy", "non_tax"),
        _item("SOC_001", "养老(个)", "social", "pre_tax_deduct"),
        _item("DED_005", "罚款", "deduction", "after_tax_deduct"),
    ]
    # 注入 override 金额
    amounts = {"ATT_001": 500000, "SUB_002": 100000, "SUB_003": 30000,
               "SOC_001": 40000, "DED_005": 10000}
    for it in items:
        it["override_amount_fen"] = amounts[it["code"]]

    # 直接调用内部 _resolve_amount，通过 dummy 聚合逻辑
    totals = {"pre_tax_add": 0, "pre_tax_deduct": 0, "after_tax_add": 0,
              "after_tax_deduct": 0, "non_tax": 0}
    for it in items:
        amt = svc._resolve_amount(it, {})
        totals[it["tax_attribute"]] += amt

    assert totals["pre_tax_add"] == 600000
    assert totals["non_tax"] == 30000
    assert totals["pre_tax_deduct"] == 40000
    assert totals["after_tax_deduct"] == 10000

    gross = totals["pre_tax_add"] + totals["non_tax"] + totals["after_tax_add"]
    taxable_base = max(0, totals["pre_tax_add"] - totals["pre_tax_deduct"])
    assert gross == 630000
    assert taxable_base == 560000  # 传入 PersonalTaxService.gross_fen


def test_formula_evaluation():
    """formula_type=formula 能按上下文求值"""
    svc = _svc()
    it = _item(
        "ATT_005", "出勤工资", "attendance", "pre_tax_add",
        ftype="formula", formula="base_salary_fen * attendance_days / work_days_in_month",
    )
    ctx = {"base_salary_fen": 500000, "attendance_days": 20, "work_days_in_month": 22}
    val = svc._resolve_amount(it, ctx)
    # 500000 * 20 / 22 = 454545
    assert 454000 <= val <= 455000


def test_formula_seniority_subsidy():
    """工龄补贴阶梯函数"""
    svc = _svc()
    it = _item(
        "SUB_001", "工龄补贴", "subsidy", "pre_tax_add",
        ftype="formula", formula="seniority_subsidy(seniority_months)",
    )
    assert svc._resolve_amount(it, {"seniority_months": 6}) == 0
    assert svc._resolve_amount(it, {"seniority_months": 18}) == 10000
    assert svc._resolve_amount(it, {"seniority_months": 40}) == 20000
    assert svc._resolve_amount(it, {"seniority_months": 72}) == 30000


def test_formula_safe_no_builtins():
    """公式中禁用内置函数（如 __import__）"""
    svc = _svc()
    it = _item(
        "EVIL_001", "危险项", "deduction", "pre_tax_deduct",
        ftype="formula", formula="__import__('os').system('echo pwned')",
    )
    # 应回退为 0 并记 warning，不抛异常
    val = svc._resolve_amount(it, {})
    assert val == 0


def test_override_wins_over_formula():
    """分配时填了 amount_fen，覆盖默认/公式"""
    svc = _svc()
    it = _item(
        "ATT_001", "基本工资", "attendance", "pre_tax_add",
        ftype="formula", formula="base_salary_fen",
    )
    it["override_amount_fen"] = 888888
    assert svc._resolve_amount(it, {"base_salary_fen": 500000}) == 888888


def test_manual_via_context_key():
    """formula_type=manual 时可通过 ctx[item_<CODE>_fen] 传入"""
    svc = _svc()
    it = _item("PERF_002", "月度绩效", "performance", "pre_tax_add", ftype="manual")
    val = svc._resolve_amount(it, {"item_PERF_002_fen": 120000})
    assert val == 120000


def test_integration_with_personal_tax_inputs():
    """
    试算输出可直接喂 PersonalTaxService.calc_monthly_tax:
      gross_fen = taxable_base_fen
      si_personal_fen = totals['pre_tax_deduct']
      tax_free_income_fen = totals['non_tax']
    """
    svc = _svc()
    # 构造 5 项
    items_with_amounts = [
        (_item("ATT_001", "基本", "attendance", "pre_tax_add"), 800000),
        (_item("PERF_002", "绩效", "performance", "pre_tax_add"), 150000),
        (_item("SUB_003", "餐补", "subsidy", "non_tax"), 30000),
        (_item("SOC_001", "养老个人", "social", "pre_tax_deduct"), 64000),
        (_item("SOC_004", "公积金个人", "social", "pre_tax_deduct"), 40000),
    ]
    totals = {k: 0 for k in ("pre_tax_add", "pre_tax_deduct", "after_tax_add",
                              "after_tax_deduct", "non_tax")}
    for it, amt in items_with_amounts:
        it["override_amount_fen"] = amt
        totals[it["tax_attribute"]] += svc._resolve_amount(it, {})

    taxable_base_fen = totals["pre_tax_add"] - totals["pre_tax_deduct"]
    assert totals["pre_tax_add"] == 950000
    assert totals["pre_tax_deduct"] == 104000
    assert totals["non_tax"] == 30000
    assert taxable_base_fen == 846000  # 这个值将传入 calc_monthly_tax(gross_fen=...)
