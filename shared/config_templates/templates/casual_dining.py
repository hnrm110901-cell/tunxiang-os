"""
正餐业态模板（湘菜/粤菜/川菜/家常菜等）

典型门店特征：
- 桌均4-6人，翻台1.5-2次/天
- 2-4个厨房分区（炒锅、凉菜、蒸菜、主食）
- 服务员点餐为主，支持扫码点餐
- 通常有会员储值，季节性营销活动
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


class CasualDiningTemplate(BaseTemplate):
    @property
    def restaurant_type(self) -> RestaurantType:
        return RestaurantType.CASUAL_DINING

    @property
    def display_name(self) -> str:
        return "正餐"

    @property
    def description(self) -> str:
        return "湘菜/粤菜/川菜/家常菜等传统中餐，含堂食+外卖，桌均4-6人"

    def build_default(self) -> TenantConfigPackage:
        return TenantConfigPackage(
            restaurant_type=RestaurantType.CASUAL_DINING,

            # 典型正餐门店规模
            table_count=20,
            vip_room_count=2,

            # 标准打印机配置：收银台 + 厨房 + 传菜口
            printers=[
                PrinterConfig(
                    name="收银台打印机",
                    printer_type="receipt",
                    is_default=True,
                    copies=1,
                ),
                PrinterConfig(
                    name="厨房打印机",
                    printer_type="kitchen",
                    copies=1,
                ),
                PrinterConfig(
                    name="传菜口打印机",
                    printer_type="kitchen",
                    copies=1,
                ),
            ],

            # 标准正餐厨房分区（4区）
            kds_zones=[
                KDSZoneConfig(
                    zone_code="cold", zone_name="凉菜档",
                    display_order=0, alert_minutes=5,
                    color_warning="#FFC107", color_overdue="#F44336",
                ),
                KDSZoneConfig(
                    zone_code="wok", zone_name="炒锅档",
                    display_order=1, alert_minutes=8,
                    color_warning="#FFC107", color_overdue="#F44336",
                ),
                KDSZoneConfig(
                    zone_code="steam", zone_name="蒸菜档",
                    display_order=2, alert_minutes=12,
                    color_warning="#FFC107", color_overdue="#F44336",
                ),
                KDSZoneConfig(
                    zone_code="staple", zone_name="主食档",
                    display_order=3, alert_minutes=5,
                    color_warning="#FFC107", color_overdue="#F44336",
                ),
            ],

            # 午市 + 晚市两班
            shifts=[
                ShiftConfig(
                    shift_name="午市",
                    start_time="10:30",
                    end_time="14:30",
                    settlement_cutoff="15:00",
                ),
                ShiftConfig(
                    shift_name="晚市",
                    start_time="17:00",
                    end_time="21:30",
                    settlement_cutoff="02:00",
                    is_overnight=False,
                ),
            ],

            # 正餐通常无最低消费，服务费按需配置（默认关闭）
            billing_rules=BillingRuleSet(
                min_spend_fen=0,
                service_fee_rate=0.0,
            ),

            # 3级会员体系：普通/银卡/金卡
            member_tiers=[
                MemberTierConfig(
                    tier_code="standard", tier_name="普通会员",
                    min_spend_fen=0, point_multiplier=1.0, discount_rate=1.0,
                ),
                MemberTierConfig(
                    tier_code="silver", tier_name="银卡会员",
                    min_spend_fen=200000, point_multiplier=1.2, discount_rate=0.95,
                    birthday_benefit="生日当月九五折",
                ),
                MemberTierConfig(
                    tier_code="gold", tier_name="金卡会员",
                    min_spend_fen=500000, point_multiplier=1.5, discount_rate=0.90,
                    birthday_benefit="生日当月九折+赠菜一道",
                ),
            ],
            point_rate=1.0,        # 消费1元=1积分
            point_redeem_rate=100.0,  # 100积分=1元

            # 渠道：默认开启主流外卖平台
            channels_enabled=["meituan", "eleme"],

            # 支付方式
            payment_methods=["wechat", "alipay", "cash", "unionpay"],

            # 员工角色模板
            employee_roles=["cashier", "waiter", "manager", "chef", "runner"],

            # Agent 策略
            agent_policies=AgentPolicySet(
                discount_guard=DiscountPolicy(
                    employee_max_discount=0.88,
                    manager_max_discount=0.80,
                    min_gross_margin=0.30,
                    require_reason_below=0.85,
                ),
                kds_target_minutes=15,
                kds_warn_minutes=22,
                inventory_alert_days=3,
            ),
        )
