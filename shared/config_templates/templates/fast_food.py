"""
快餐业态模板（档口/快餐/小吃/外带为主）

典型门店特征：
- 无桌台或少桌台，翻台极快
- 收银为主，出品简单快
- 叫号取餐，外带比例高
- 点餐主要靠小程序/自助机
"""

from ..base import (
    AgentPolicySet,
    BaseTemplate,
    BillingRuleSet,
    DiscountPolicy,
    KDSZoneConfig,
    MemberTierConfig,
    PrinterConfig,
    RestaurantType,
    ShiftConfig,
    TenantConfigPackage,
)


class FastFoodTemplate(BaseTemplate):
    @property
    def restaurant_type(self) -> RestaurantType:
        return RestaurantType.FAST_FOOD

    @property
    def display_name(self) -> str:
        return "快餐/档口"

    @property
    def description(self) -> str:
        return "快餐/档口/小吃，无桌台或少桌台，叫号取餐，出品快"

    def build_default(self) -> TenantConfigPackage:
        return TenantConfigPackage(
            restaurant_type=RestaurantType.FAST_FOOD,
            table_count=8,  # 快餐少桌或无桌
            vip_room_count=0,
            printers=[
                PrinterConfig(
                    name="收银打印机",
                    printer_type="receipt",
                    is_default=True,
                ),
                PrinterConfig(
                    name="出品口打印机",
                    printer_type="kitchen",
                ),
                PrinterConfig(
                    name="叫号票打印机",
                    printer_type="label",  # 取餐号
                ),
            ],
            # 快餐KDS只需一个出品区
            kds_zones=[
                KDSZoneConfig(
                    zone_code="counter",
                    zone_name="出品台",
                    display_order=0,
                    alert_minutes=5,
                    color_warning="#FFC107",
                    color_overdue="#F44336",
                ),
            ],
            # 快餐全天单班（或早午晚三班）
            shifts=[
                ShiftConfig(
                    shift_name="全天",
                    start_time="08:00",
                    end_time="21:00",
                    settlement_cutoff="22:00",
                ),
            ],
            billing_rules=BillingRuleSet(
                min_spend_fen=0,
                service_fee_rate=0.0,
                packing_fee_fen=200,  # 打包费2元（默认）
            ),
            # 快餐会员体系简单
            member_tiers=[
                MemberTierConfig(
                    tier_code="standard",
                    tier_name="普通会员",
                    min_spend_fen=0,
                    point_multiplier=1.0,
                    discount_rate=1.0,
                ),
                MemberTierConfig(
                    tier_code="regular",
                    tier_name="常客",
                    min_spend_fen=50000,
                    point_multiplier=1.2,
                    discount_rate=0.95,
                ),
            ],
            point_rate=1.0,
            point_redeem_rate=50.0,  # 快餐积分兑换更实惠
            channels_enabled=["meituan", "eleme", "douyin"],
            delivery_packing_fee_fen=200,
            payment_methods=["wechat", "alipay", "cash"],
            employee_roles=["cashier", "chef", "manager"],
            agent_policies=AgentPolicySet(
                discount_guard=DiscountPolicy(
                    employee_max_discount=0.95,  # 快餐折扣空间小
                    manager_max_discount=0.90,
                    min_gross_margin=0.40,  # 快餐毛利应更高
                    require_reason_below=0.90,
                ),
                kds_target_minutes=5,  # 快餐必须快
                kds_warn_minutes=8,
                inventory_alert_days=1,  # 快餐食材快进快出
            ),
        )
