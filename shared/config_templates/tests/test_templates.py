"""
shared/config_templates 单元测试

覆盖：
  1. 每种业态模板能正常实例化并生成默认配置包
  2. apply() 能正确覆写关键字段
  3. TenantConfigPackage.is_ready_for_go_live() 判断逻辑
  4. registry.get_template() / list_templates() 注册表查询
  5. 金额单位校验（全部为分，无浮点）
"""
from __future__ import annotations

import pytest

from shared.config_templates import (
    RestaurantType,
    TenantConfigPackage,
    get_template,
    list_templates,
)


# ── fixture ───────────────────────────────────────────────────────────


@pytest.fixture(params=list(RestaurantType))
def any_template(request):
    """参数化 fixture：对所有 5 种业态运行同一套测试"""
    return get_template(request.param)


# ── 基础实例化测试 ─────────────────────────────────────────────────────


def test_all_templates_instantiate(any_template):
    """每种模板都能生成默认配置包，不抛异常"""
    pkg = any_template.build_default()
    assert isinstance(pkg, TenantConfigPackage)
    assert pkg.restaurant_type == any_template.restaurant_type


def test_all_templates_have_printers(any_template):
    """每种模板至少配置一台收银打印机"""
    pkg = any_template.build_default()
    receipt_printers = [p for p in pkg.printers if p.printer_type == "receipt"]
    assert len(receipt_printers) >= 1, (
        f"{any_template.display_name} 模板缺少收银打印机"
    )


def test_all_templates_have_shifts(any_template):
    """每种模板至少配置一个营业班次"""
    pkg = any_template.build_default()
    assert len(pkg.shifts) >= 1, f"{any_template.display_name} 模板缺少班次配置"


def test_all_templates_have_member_tiers(any_template):
    """每种模板至少配置一个会员等级"""
    pkg = any_template.build_default()
    assert len(pkg.member_tiers) >= 1, f"{any_template.display_name} 模板缺少会员等级"


def test_all_templates_have_employee_roles(any_template):
    """每种模板至少配置一个员工角色"""
    pkg = any_template.build_default()
    assert len(pkg.employee_roles) >= 1


def test_all_templates_have_agent_policies(any_template):
    """每种模板都有 Agent 策略（折扣守护阈值非零）"""
    pkg = any_template.build_default()
    dg = pkg.agent_policies.discount_guard
    assert 0 < dg.employee_max_discount <= 1.0
    assert 0 < dg.manager_max_discount <= 1.0
    assert 0 < dg.min_gross_margin < 1.0


# ── 金额单位校验 ──────────────────────────────────────────────────────


def test_billing_rules_amounts_are_integers(any_template):
    """最低消费和打包费必须是整数（分），不能是浮点"""
    pkg = any_template.build_default()
    assert isinstance(pkg.billing_rules.min_spend_fen, int)
    assert isinstance(pkg.billing_rules.packing_fee_fen, int)
    assert isinstance(pkg.billing_rules.service_fee_fixed_fen, int)


def test_member_tiers_amounts_are_integers(any_template):
    """会员升级门槛必须是整数（分）"""
    pkg = any_template.build_default()
    for tier in pkg.member_tiers:
        assert isinstance(tier.min_spend_fen, int), (
            f"{any_template.display_name} 会员等级 {tier.tier_code} 金额非整数"
        )


# ── apply() 覆写测试 ──────────────────────────────────────────────────


def test_apply_overwrites_store_name():
    tpl = get_template(RestaurantType.CASUAL_DINING)
    pkg = tpl.apply({"store_name": "测试门店", "delivery_session_id": "test-001"})
    assert pkg.store_name == "测试门店"
    assert pkg.delivery_session_id == "test-001"


def test_apply_overwrites_table_count():
    tpl = get_template(RestaurantType.HOT_POT)
    pkg = tpl.apply({"table_count": 50})
    assert pkg.table_count == 50


def test_apply_overwrites_discount_threshold():
    tpl = get_template(RestaurantType.CASUAL_DINING)
    pkg = tpl.apply({
        "employee_max_discount": 0.92,
        "manager_max_discount": 0.85,
        "min_gross_margin": 0.25,
    })
    assert pkg.agent_policies.discount_guard.employee_max_discount == 0.92
    assert pkg.agent_policies.discount_guard.manager_max_discount == 0.85
    assert pkg.agent_policies.discount_guard.min_gross_margin == 0.25


def test_apply_min_spend_yuan_converts_to_fen():
    """min_spend_yuan（元）应转换为 min_spend_fen（分）"""
    tpl = get_template(RestaurantType.BANQUET)
    pkg = tpl.apply({"min_spend_yuan": 1500})
    assert pkg.billing_rules.min_spend_fen == 150000  # 1500元 = 150000分


def test_apply_payment_methods():
    tpl = get_template(RestaurantType.FAST_FOOD)
    pkg = tpl.apply({"payment_methods": ["wechat", "alipay"]})
    assert pkg.payment_methods == ["wechat", "alipay"]


def test_apply_channels_enabled():
    tpl = get_template(RestaurantType.CAFE_TEA)
    pkg = tpl.apply({"channels_enabled": ["meituan", "douyin"]})
    assert "meituan" in pkg.channels_enabled
    assert "douyin" in pkg.channels_enabled


def test_apply_kds_zones_override():
    tpl = get_template(RestaurantType.BANQUET)
    custom_zones = [
        {"zone_code": "seafood", "zone_name": "海鲜档", "alert_minutes": 15},
        {"zone_code": "hot", "zone_name": "热菜档", "alert_minutes": 10},
    ]
    pkg = tpl.apply({"kds_zones": custom_zones})
    assert len(pkg.kds_zones) == 2
    assert pkg.kds_zones[0].zone_code == "seafood"
    assert pkg.kds_zones[1].alert_minutes == 10


def test_apply_preserves_defaults_for_unanswered():
    """未回答的问题应保留模板默认值"""
    tpl = get_template(RestaurantType.CASUAL_DINING)
    pkg = tpl.apply({"store_name": "只回答了店名"})
    default_pkg = tpl.build_default()
    # 未覆写的 shifts 应与默认相同
    assert len(pkg.shifts) == len(default_pkg.shifts)
    assert pkg.shifts[0].shift_name == default_pkg.shifts[0].shift_name


# ── 业态特有配置验证 ──────────────────────────────────────────────────


def test_banquet_has_service_fee():
    """宴席模板默认有服务费"""
    tpl = get_template(RestaurantType.BANQUET)
    pkg = tpl.build_default()
    assert pkg.billing_rules.service_fee_rate > 0


def test_banquet_has_min_spend():
    """宴席模板默认有最低消费"""
    tpl = get_template(RestaurantType.BANQUET)
    pkg = tpl.build_default()
    assert pkg.billing_rules.min_spend_fen > 0


def test_cafe_tea_has_label_printer():
    """茶饮模板默认有标签打印机（杯贴）"""
    tpl = get_template(RestaurantType.CAFE_TEA)
    pkg = tpl.build_default()
    label_printers = [p for p in pkg.printers if p.printer_type == "label"]
    assert len(label_printers) >= 1


def test_fast_food_has_short_kds_target():
    """快餐出餐目标时间应 ≤ 5 分钟"""
    tpl = get_template(RestaurantType.FAST_FOOD)
    pkg = tpl.build_default()
    assert pkg.agent_policies.kds_target_minutes <= 5


def test_banquet_pre_sort_enabled():
    """宴席模板启用提前排菜"""
    tpl = get_template(RestaurantType.BANQUET)
    pkg = tpl.build_default()
    assert pkg.agent_policies.banquet_pre_sort_hours > 0


def test_cafe_tea_high_gross_margin_guard():
    """茶饮毛利守护线应 ≥ 50%（茶饮毛利高）"""
    tpl = get_template(RestaurantType.CAFE_TEA)
    pkg = tpl.build_default()
    assert pkg.agent_policies.discount_guard.min_gross_margin >= 0.50


# ── registry 测试 ─────────────────────────────────────────────────────


def test_get_template_all_types():
    for rt in RestaurantType:
        tpl = get_template(rt)
        assert tpl.restaurant_type == rt


def test_get_template_unknown_raises():
    with pytest.raises(ValueError, match="未知业态类型"):
        get_template("unknown_type")  # type: ignore


def test_list_templates_returns_all():
    templates = list_templates()
    assert len(templates) == len(RestaurantType)
    keys = {t["type"] for t in templates}
    expected = {rt.value for rt in RestaurantType}
    assert keys == expected


def test_list_templates_has_display_name():
    for t in list_templates():
        assert t["display_name"], f"模板 {t['type']} 缺少 display_name"
        assert t["description"], f"模板 {t['type']} 缺少 description"


# ── TenantConfigPackage.is_ready_for_go_live() ───────────────────────


def test_go_live_ready_requires_score_90():
    pkg = TenantConfigPackage(
        restaurant_type=RestaurantType.CASUAL_DINING,
        config_score=89.9,
        missing_required=[],
    )
    assert pkg.is_ready_for_go_live() is False


def test_go_live_ready_requires_no_missing():
    pkg = TenantConfigPackage(
        restaurant_type=RestaurantType.CASUAL_DINING,
        config_score=95.0,
        missing_required=["printer_receipt"],
    )
    assert pkg.is_ready_for_go_live() is False


def test_go_live_ready_passes():
    pkg = TenantConfigPackage(
        restaurant_type=RestaurantType.CASUAL_DINING,
        config_score=92.0,
        missing_required=[],
    )
    assert pkg.is_ready_for_go_live() is True
