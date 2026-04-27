"""销售渠道配置表 — 新增渠道不改代码，加记录即可

channel_type 分类:
  dine_in   — 堂食/外带
  delivery  — 外卖平台
  retail    — 零售/团购
  banquet   — 宴会
  catering  — 外烩/大厨到家
  b2b       — 中央厨房B2B
"""

from dataclasses import dataclass, field


@dataclass
class SalesChannel:
    """销售渠道配置 — 数据驱动，非枚举硬编码"""

    channel_id: str
    channel_name: str  # "堂食"/"美团外卖"/"预制菜零售"
    channel_type: str  # dine_in/delivery/retail/banquet/catering/b2b
    commission_rate: float  # 平台抽成率 (0.0 ~ 1.0)
    settlement_days: int  # T+N结算周期
    payment_fee_rate: float  # 支付手续费率
    margin_rules: dict = field(default_factory=dict)  # 毛利核算规则
    is_active: bool = True
    created_at: str = ""


# Pre-seeded channels — 覆盖主流餐饮渠道
DEFAULT_CHANNELS = [
    SalesChannel(
        channel_id="ch_dine_in",
        channel_name="堂食",
        channel_type="dine_in",
        commission_rate=0.0,
        settlement_days=0,
        payment_fee_rate=0.0038,
        margin_rules={"type": "standard"},
    ),
    SalesChannel(
        channel_id="ch_takeaway",
        channel_name="外带",
        channel_type="dine_in",
        commission_rate=0.0,
        settlement_days=0,
        payment_fee_rate=0.0038,
        margin_rules={"type": "standard"},
    ),
    SalesChannel(
        channel_id="ch_meituan",
        channel_name="美团外卖",
        channel_type="delivery",
        commission_rate=0.18,
        settlement_days=7,
        payment_fee_rate=0.0,
        margin_rules={"type": "platform", "deduct_commission": True},
    ),
    SalesChannel(
        channel_id="ch_eleme",
        channel_name="饿了么",
        channel_type="delivery",
        commission_rate=0.20,
        settlement_days=7,
        payment_fee_rate=0.0,
        margin_rules={"type": "platform", "deduct_commission": True},
    ),
    SalesChannel(
        channel_id="ch_douyin",
        channel_name="抖音外卖",
        channel_type="delivery",
        commission_rate=0.10,
        settlement_days=7,
        payment_fee_rate=0.0,
        margin_rules={"type": "platform", "deduct_commission": True},
    ),
    SalesChannel(
        channel_id="ch_group_buy",
        channel_name="团购",
        channel_type="retail",
        commission_rate=0.12,
        settlement_days=3,
        payment_fee_rate=0.0,
        margin_rules={"type": "platform", "deduct_commission": True},
    ),
    SalesChannel(
        channel_id="ch_banquet",
        channel_name="宴会",
        channel_type="banquet",
        commission_rate=0.0,
        settlement_days=0,
        payment_fee_rate=0.0038,
        margin_rules={"type": "banquet", "min_spend_pct": 0.80},
    ),
    SalesChannel(
        channel_id="ch_catering",
        channel_name="外烩",
        channel_type="catering",
        commission_rate=0.0,
        settlement_days=0,
        payment_fee_rate=0.0038,
        margin_rules={"type": "catering"},
    ),
    SalesChannel(
        channel_id="ch_retail",
        channel_name="预制菜零售",
        channel_type="retail",
        commission_rate=0.0,
        settlement_days=0,
        payment_fee_rate=0.006,
        margin_rules={"type": "retail"},
    ),
    SalesChannel(
        channel_id="ch_chef_home",
        channel_name="大厨到家",
        channel_type="catering",
        commission_rate=0.0,
        settlement_days=0,
        payment_fee_rate=0.0038,
        margin_rules={"type": "catering", "include_labor": True},
    ),
    SalesChannel(
        channel_id="ch_central_kitchen",
        channel_name="中央厨房B2B",
        channel_type="b2b",
        commission_rate=0.0,
        settlement_days=30,
        payment_fee_rate=0.0,
        margin_rules={"type": "b2b", "net_terms": True},
    ),
]


def get_channel_by_id(channel_id: str) -> SalesChannel | None:
    """按ID查找渠道配置"""
    for ch in DEFAULT_CHANNELS:
        if ch.channel_id == channel_id:
            return ch
    return None


def get_channels_by_type(channel_type: str) -> list[SalesChannel]:
    """按类型过滤渠道"""
    return [ch for ch in DEFAULT_CHANNELS if ch.channel_type == channel_type]
