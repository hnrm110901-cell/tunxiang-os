"""
茶饮/咖啡业态模板（奶茶/咖啡/茶饮连锁）

典型门店特征：
- 收银台点餐+制作，无传统桌台
- 外带比例高（60-80%）
- 小程序点餐/扫码点餐为主
- 品类少但规格多（大中小+温度+糖度）
- 外卖平台占比大
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


class CafeTeaTemplate(BaseTemplate):
    @property
    def restaurant_type(self) -> RestaurantType:
        return RestaurantType.CAFE_TEA

    @property
    def display_name(self) -> str:
        return "茶饮/咖啡"

    @property
    def description(self) -> str:
        return "奶茶/咖啡/茶饮连锁，扫码点餐，外带为主，规格多"

    def build_default(self) -> TenantConfigPackage:
        return TenantConfigPackage(
            restaurant_type=RestaurantType.CAFE_TEA,

            table_count=6,     # 茶饮座位少
            vip_room_count=0,

            printers=[
                PrinterConfig(
                    name="收银打印机",
                    printer_type="receipt",
                    is_default=True,
                ),
                PrinterConfig(
                    name="制作标签打印机",
                    printer_type="label",   # 杯贴/标签
                    copies=1,
                ),
            ],

            # 茶饮KDS简单
            kds_zones=[
                KDSZoneConfig(
                    zone_code="bar", zone_name="吧台",
                    display_order=0, alert_minutes=4,
                    color_warning="#FFC107", color_overdue="#F44336",
                ),
            ],

            shifts=[
                ShiftConfig(
                    shift_name="全天",
                    start_time="09:00",
                    end_time="22:00",
                    settlement_cutoff="23:00",
                ),
            ],

            billing_rules=BillingRuleSet(
                min_spend_fen=0,
                service_fee_rate=0.0,
                packing_fee_fen=100,  # 外带杯1元
            ),

            member_tiers=[
                MemberTierConfig(
                    tier_code="standard", tier_name="普通会员",
                    min_spend_fen=0, point_multiplier=1.0, discount_rate=1.0,
                ),
                MemberTierConfig(
                    tier_code="frequent", tier_name="常客",
                    min_spend_fen=50000, point_multiplier=1.5, discount_rate=0.95,
                    birthday_benefit="生日当月赠饮一杯",
                ),
            ],
            point_rate=2.0,        # 茶饮积分积累快（消费1元=2积分）
            point_redeem_rate=50.0,

            # 茶饮外卖占比高，全平台开通
            channels_enabled=["meituan", "eleme", "douyin"],
            delivery_packing_fee_fen=100,

            payment_methods=["wechat", "alipay", "cash"],

            employee_roles=["cashier", "barista", "manager"],

            agent_policies=AgentPolicySet(
                discount_guard=DiscountPolicy(
                    employee_max_discount=0.95,
                    manager_max_discount=0.90,
                    min_gross_margin=0.55,   # 茶饮毛利极高
                    require_reason_below=0.90,
                ),
                kds_target_minutes=4,
                kds_warn_minutes=6,
                inventory_alert_days=2,
                inventory_waste_alert_rate=0.02,  # 茶饮食材精贵，损耗严控
            ),
        )
