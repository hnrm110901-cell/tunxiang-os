"""
宴席业态模板（高端正餐/宴会/婚宴/商宴，如徐记海鲜类）

典型门店特征：
- 宴席+散客双模式，包厢为主
- 海鲜/活鲜展示柜，称重计费
- 宴席预订+定金+排菜流程
- 人均消费高，最低消费常见
- 企业挂账/协议单位比例高
- 存酒、押金场景高频
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


class BanquetTemplate(BaseTemplate):
    @property
    def restaurant_type(self) -> RestaurantType:
        return RestaurantType.BANQUET

    @property
    def display_name(self) -> str:
        return "宴席/高端正餐"

    @property
    def description(self) -> str:
        return "高端正餐/宴会/婚宴，含包厢+散台，预订+排菜，海鲜称重，企业挂账"

    def build_default(self) -> TenantConfigPackage:
        return TenantConfigPackage(
            restaurant_type=RestaurantType.BANQUET,
            table_count=30,
            vip_room_count=10,  # 宴席包厢多
            printers=[
                PrinterConfig(
                    name="前台收银打印机",
                    printer_type="receipt",
                    is_default=True,
                ),
                PrinterConfig(
                    name="冷菜档打印机",
                    printer_type="kitchen",
                ),
                PrinterConfig(
                    name="热菜档打印机",
                    printer_type="kitchen",
                ),
                PrinterConfig(
                    name="海鲜档打印机",
                    printer_type="kitchen",
                ),
                PrinterConfig(
                    name="甜品/主食打印机",
                    printer_type="kitchen",
                ),
                PrinterConfig(
                    name="标签打印机（称重）",
                    printer_type="label",
                ),
            ],
            # 宴席厨房分区精细
            kds_zones=[
                KDSZoneConfig(
                    zone_code="cold",
                    zone_name="冷菜档",
                    display_order=0,
                    alert_minutes=5,
                    color_warning="#FFC107",
                    color_overdue="#F44336",
                ),
                KDSZoneConfig(
                    zone_code="hot",
                    zone_name="热菜炒锅",
                    display_order=1,
                    alert_minutes=10,
                    color_warning="#FFC107",
                    color_overdue="#F44336",
                ),
                KDSZoneConfig(
                    zone_code="seafood",
                    zone_name="海鲜档",
                    display_order=2,
                    alert_minutes=15,
                    color_warning="#FF9800",
                    color_overdue="#F44336",
                ),
                KDSZoneConfig(
                    zone_code="dessert",
                    zone_name="甜品/主食",
                    display_order=3,
                    alert_minutes=8,
                    color_warning="#FFC107",
                    color_overdue="#F44336",
                ),
            ],
            shifts=[
                ShiftConfig(
                    shift_name="午宴",
                    start_time="11:00",
                    end_time="14:30",
                    settlement_cutoff="15:00",
                ),
                ShiftConfig(
                    shift_name="晚宴",
                    start_time="17:30",
                    end_time="22:00",
                    settlement_cutoff="02:00",
                ),
            ],
            # 宴席通常有最低消费（每桌1000-2000元区间，默认1000元）
            billing_rules=BillingRuleSet(
                min_spend_fen=100000,  # 默认最低消费1000元（DeliveryAgent会覆写）
                service_fee_rate=0.10,  # 10%服务费
                min_spend_applies_to="table",
            ),
            # 宴席高端会员体系
            member_tiers=[
                MemberTierConfig(
                    tier_code="standard",
                    tier_name="普通会员",
                    min_spend_fen=0,
                    point_multiplier=1.0,
                    discount_rate=1.0,
                ),
                MemberTierConfig(
                    tier_code="silver",
                    tier_name="银卡会员",
                    min_spend_fen=500000,
                    point_multiplier=1.5,
                    discount_rate=0.95,
                    birthday_benefit="生日当月九五折+赠甜品",
                ),
                MemberTierConfig(
                    tier_code="gold",
                    tier_name="金卡会员",
                    min_spend_fen=2000000,
                    point_multiplier=2.0,
                    discount_rate=0.88,
                    birthday_benefit="生日当月专属包厢+赠菜",
                ),
                MemberTierConfig(
                    tier_code="diamond",
                    tier_name="钻石会员",
                    min_spend_fen=5000000,
                    point_multiplier=3.0,
                    discount_rate=0.85,
                    birthday_benefit="生日当月专属管家+全场八五折",
                ),
            ],
            point_rate=1.0,
            point_redeem_rate=200.0,  # 高端会员积分价值高
            # 宴席外卖比例低
            channels_enabled=["meituan"],
            payment_methods=["wechat", "alipay", "cash", "unionpay", "stored_value", "agreement"],
            employee_roles=[
                "cashier",
                "waiter",
                "captain",  # 宴席有领班
                "manager",
                "chef",
                "seafood_chef",
                "runner",
            ],
            agent_policies=AgentPolicySet(
                discount_guard=DiscountPolicy(
                    employee_max_discount=0.95,  # 宴席员工几乎不能打折
                    manager_max_discount=0.88,
                    min_gross_margin=0.35,
                    require_reason_below=0.90,
                    alert_on_gift=True,
                    block_below_cost=True,
                ),
                kds_target_minutes=20,  # 宴席出品允许更长
                kds_warn_minutes=30,
                inventory_alert_days=2,
                banquet_pre_sort_hours=2,  # 宴席提前2小时自动排菜
                finance_audit_enabled=True,
            ),
        )
