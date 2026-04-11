"""
火锅业态模板

典型门店特征：
- 桌均4-6人，翻台2-3次/天，高峰期排队
- 厨房较简单（备料+高汤），主要是配菜出品
- 点餐量大，小料区自助
- 通常有储值卡，团购活动多
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


class HotPotTemplate(BaseTemplate):
    @property
    def restaurant_type(self) -> RestaurantType:
        return RestaurantType.HOT_POT

    @property
    def display_name(self) -> str:
        return "火锅"

    @property
    def description(self) -> str:
        return "火锅/串串/烤肉，自选为主，翻台率高，高峰排队"

    def build_default(self) -> TenantConfigPackage:
        return TenantConfigPackage(
            restaurant_type=RestaurantType.HOT_POT,

            table_count=30,
            vip_room_count=0,

            printers=[
                PrinterConfig(
                    name="收银台打印机",
                    printer_type="receipt",
                    is_default=True,
                ),
                PrinterConfig(
                    name="配菜厨房",
                    printer_type="kitchen",
                ),
            ],

            # 火锅厨房分区较简单
            kds_zones=[
                KDSZoneConfig(
                    zone_code="prep", zone_name="配菜档",
                    display_order=0, alert_minutes=6,
                    color_warning="#FFC107", color_overdue="#F44336",
                ),
                KDSZoneConfig(
                    zone_code="soup", zone_name="底料区",
                    display_order=1, alert_minutes=4,
                    color_warning="#FFC107", color_overdue="#F44336",
                ),
            ],

            # 全天候单班（或午晚两班）
            shifts=[
                ShiftConfig(
                    shift_name="午市",
                    start_time="11:00",
                    end_time="14:30",
                    settlement_cutoff="15:00",
                ),
                ShiftConfig(
                    shift_name="晚市",
                    start_time="17:00",
                    end_time="22:00",
                    is_overnight=False,
                    settlement_cutoff="02:00",
                ),
            ],

            # 火锅通常无最低消费
            billing_rules=BillingRuleSet(
                min_spend_fen=0,
                service_fee_rate=0.0,
            ),

            member_tiers=[
                MemberTierConfig(
                    tier_code="standard", tier_name="普通会员",
                    min_spend_fen=0, point_multiplier=1.0, discount_rate=1.0,
                ),
                MemberTierConfig(
                    tier_code="vip", tier_name="VIP会员",
                    min_spend_fen=300000, point_multiplier=1.5, discount_rate=0.95,
                    birthday_benefit="生日当月赠底料一份",
                ),
            ],
            point_rate=1.0,
            point_redeem_rate=100.0,

            channels_enabled=["meituan", "eleme", "douyin"],

            payment_methods=["wechat", "alipay", "cash", "unionpay"],

            employee_roles=["cashier", "waiter", "manager", "chef"],

            agent_policies=AgentPolicySet(
                discount_guard=DiscountPolicy(
                    employee_max_discount=0.90,
                    manager_max_discount=0.85,
                    min_gross_margin=0.35,  # 火锅毛利高，守护线可设高
                    require_reason_below=0.88,
                ),
                kds_target_minutes=8,   # 火锅出品快
                kds_warn_minutes=12,
                inventory_alert_days=2,  # 鲜货多，预警更早
                inventory_waste_alert_rate=0.03,
            ),
        )
