"""事件类型注册表 -- 屯象OS 全域事件类型统一定义

每个事件类型是 str 枚举，值为点分格式 "{domain}.{action}"。
新增事件类型在此处注册，确保全局唯一、可查。

10大业务域（对应方案第2.2节）：
  订单(order) / 折扣(discount) / 支付(payment) / 会员(member) /
  库存(inventory) / 渠道(channel) / 预订宴会(reservation) /
  财务(settlement) / 食安(safety) / 能耗(energy)

扩展域（屯象OS特有）：
  KDS厨房(kds) / Agent决策(agent) / 舆情评价(review) / 成本卡(recipe)
"""
from __future__ import annotations

from enum import Enum


# ──────────────────────────────────────────────────────────────────────
# 核心业务域（七条因果链直接关联）
# ──────────────────────────────────────────────────────────────────────

class OrderEventType(str, Enum):
    """订单事件 — 因果链①②③④⑤⑥⑦"""

    CREATED = "order.created"              # 订单创建
    ITEM_ADDED = "order.item_added"        # 加菜
    ITEM_removed = "order.item_removed"    # 退菜
    SUBMITTED = "order.submitted"          # 提交出餐
    PAID = "order.paid"                    # 支付完成
    CANCELLED = "order.cancelled"          # 取消
    REFUNDED = "order.refunded"            # 整单退款
    PARTIAL_REFUNDED = "order.partial_refunded"  # 部分退款
    CLOSED = "order.closed"               # 结账关闭


class DiscountEventType(str, Enum):
    """折扣授权事件 — 因果链①折扣健康"""

    APPLIED = "discount.applied"           # 折扣被应用
    AUTHORIZED = "discount.authorized"     # 主管授权
    REVOKED = "discount.revoked"           # 折扣撤销
    THRESHOLD_EXCEEDED = "discount.threshold_exceeded"  # 超授权阈值
    LEAK_DETECTED = "discount.leak_detected"            # Agent检测到泄漏


class PaymentEventType(str, Enum):
    """支付事件 — 因果链⑦日清日结"""

    INITIATED = "payment.initiated"        # 发起支付
    CONFIRMED = "payment.confirmed"        # 支付确认
    FAILED = "payment.failed"             # 支付失败
    REFUNDED = "payment.refunded"         # 退款
    CASH_DECLARED = "payment.cash_declared"  # 现金申报
    CHANNEL_SETTLED = "payment.channel_settled"  # 渠道结算到账


class MemberEventType(str, Enum):
    """会员事件 — 因果链⑤会员真ROI"""

    REGISTERED = "member.registered"          # 注册
    RECHARGED = "member.recharged"            # 储值充值（负债事件）
    CONSUMED = "member.consumed"              # 储值消费（收入确认事件）
    VOUCHER_ISSUED = "member.voucher_issued"   # 发券
    VOUCHER_USED = "member.voucher_used"      # 核销券
    VOUCHER_EXPIRED = "member.voucher_expired"  # 券过期
    UPGRADED = "member.upgraded"              # 等级升级
    POINTS_CHANGED = "member.points_changed"  # 积分变动
    CHURN_PREDICTED = "member.churn_predicted"  # Agent预测流失


class InventoryEventType(str, Enum):
    """库存/损耗事件 — 因果链③BOM推算"""

    RECEIVED = "inventory.received"           # 入库
    CONSUMED = "inventory.consumed"           # 出库（BOM推算）
    WASTED = "inventory.wasted"               # 损耗登记
    ADJUSTED = "inventory.adjusted"           # 盘点调整
    EXPIRED = "inventory.expired"             # 过期报废
    LOW_STOCK = "inventory.low_stock"         # 库存预警
    TRANSFER_IN = "inventory.transfer_in"     # 调拨入库
    TRANSFER_OUT = "inventory.transfer_out"   # 调拨出库


class ChannelEventType(str, Enum):
    """渠道事件 — 因果链②外卖真毛利"""

    ORDER_SYNCED = "channel.order_synced"         # 渠道订单同步
    COMMISSION_CALC = "channel.commission_calc"   # 佣金计算
    SETTLEMENT = "channel.settlement"             # 渠道结算
    PROMOTION_APPLIED = "channel.promotion_applied"  # 平台活动补贴
    CHARGEBACK = "channel.chargeback"             # 渠道拒付


class ReservationEventType(str, Enum):
    """预订/宴会事件 — 因果链⑥宴会收入链"""

    CREATED = "reservation.created"               # 预订创建
    CONFIRMED = "reservation.confirmed"           # 确认预订
    CANCELLED = "reservation.cancelled"           # 取消预订
    BANQUET_DEPOSIT_PAID = "reservation.banquet_deposit_paid"   # 宴会定金
    BANQUET_MENU_CONFIRMED = "reservation.banquet_menu_confirmed"  # 菜单确认
    BANQUET_SETTLED = "reservation.banquet_settled"  # 宴会结账


class SettlementEventType(str, Enum):
    """财务结算事件 — 因果链⑦日清日结"""

    DAILY_CLOSED = "settlement.daily_closed"         # 日结完成
    RECONCILED = "settlement.reconciled"             # 对账完成
    DISCREPANCY_FOUND = "settlement.discrepancy_found"  # 差异发现
    REVENUE_RECOGNIZED = "settlement.revenue_recognized"  # 收入确认
    STORED_VALUE_DEFERRED = "settlement.stored_value_deferred"  # 储值负债入账
    ADVANCE_CONSUMED = "settlement.advance_consumed"    # 预收款转收入


# ──────────────────────────────────────────────────────────────────────
# 新增模块（事件总线上的自然延伸，方案第5节）
# ──────────────────────────────────────────────────────────────────────

class SafetyEventType(str, Enum):
    """食品安全合规事件 — 法律义务（市场监管总局要求）"""

    SAMPLE_LOGGED = "safety.sample_logged"              # 留样登记
    TEMPERATURE_RECORDED = "safety.temperature_recorded"  # 温度记录
    INSPECTION_DONE = "safety.inspection_done"          # 检查完成
    VIOLATION_FOUND = "safety.violation_found"          # 违规发现
    EXPIRY_ALERT = "safety.expiry_alert"                # 临期预警
    CERTIFICATE_UPDATED = "safety.certificate_updated"  # 证件更新
    TRAINING_COMPLETED = "safety.training_completed"    # 食安培训完成


class EnergyEventType(str, Enum):
    """能耗管理事件 — IoT智能电表/燃气表"""

    READING_CAPTURED = "energy.reading_captured"        # 抄表数据
    ANOMALY_DETECTED = "energy.anomaly_detected"        # 异常能耗
    ALERT_SENT = "energy.alert_sent"                    # 告警推送
    BENCHMARK_SET = "energy.benchmark_set"              # 基准线设置


class ReviewEventType(str, Enum):
    """舆情/评价事件"""

    CAPTURED = "review.captured"                        # 评价采集
    SENTIMENT_ANALYZED = "review.sentiment_analyzed"    # 情感分析完成
    ATTRIBUTED = "review.attributed"                    # 归因到菜品/员工
    RESPONDED = "review.responded"                      # 商家回复


class OpinionEventType(str, Enum):
    """公众舆情监控事件（PublicOpinionProjector 消费）"""

    MENTION_CAPTURED = "opinion.mention_captured"       # 新舆情采集
    RESOLVED = "opinion.resolved"                       # 舆情已处理
    SENTIMENT_ANALYZED = "opinion.sentiment_analyzed"   # 情感分析完成
    ESCALATED = "opinion.escalated"                     # 舆情升级（需人工介入）


class RecipeEventType(str, Enum):
    """成本卡事件 — 动态毛利"""

    COST_UPDATED = "recipe.cost_updated"                # 成本卡更新
    PROCUREMENT_PRICE_CHANGED = "recipe.procurement_price_changed"  # 采购价变动
    MENU_PRICE_ADJUSTED = "recipe.menu_price_adjusted"  # 菜单价格调整
    MARGIN_ALERT = "recipe.margin_alert"                # 毛利预警


# ──────────────────────────────────────────────────────────────────────
# 屯象OS系统级域
# ──────────────────────────────────────────────────────────────────────

class KdsEventType(str, Enum):
    """厨房 KDS 事件"""

    ORDER_READY = "kds.order_ready"
    TIMEOUT_WARNING = "kds.timeout_warning"
    SHORTAGE = "kds.shortage"


class AgentEventType(str, Enum):
    """Agent 智能决策事件"""

    DECISION = "agent.decision"
    CONSTRAINT_VIOLATION = "agent.constraint_violation"
    ALERT = "agent.alert"
    ALERT_ACKNOWLEDGED = "agent.alert_acknowledged"     # 老板在WeCom确认告警


# ──────────────────────────────────────────────────────────────────────
# 全局注册表
# ──────────────────────────────────────────────────────────────────────

# 域名 -> Redis Stream key 映射（投影器消费用）
DOMAIN_STREAM_MAP: dict[str, str] = {
    # 核心业务域
    "order":        "tx_order_events",
    "discount":     "tx_discount_events",
    "payment":      "tx_payment_events",
    "member":       "tx_member_events",
    "inventory":    "tx_inventory_events",
    "channel":      "tx_channel_events",
    "reservation":  "tx_reservation_events",
    "settlement":   "tx_settlement_events",
    # 新增模块
    "safety":       "tx_safety_events",
    "energy":       "tx_energy_events",
    "opinion":      "tx_opinion_events",
    "review":       "tx_review_events",
    "recipe":       "tx_recipe_events",
    # 系统域
    "kds":          "tx_kds_events",
    "agent":        "tx_agent_events",
    # 财务应收管理域（v156 新增）
    "deposit":      "tx_deposit_events",
    "wine_storage": "tx_wine_storage_events",
    "credit":       "tx_credit_events",
    # 营销活动域（v157 新增）
    "campaign":     "tx_campaign_events",
    # 兼容旧域
    "trade":        "trade_events",
    "supply":       "supply_events",
    "finance":      "finance_events",
    "org":          "org_events",
    "menu":         "menu_events",
    "ops":          "ops_events",
}

# 域名 -> stream_type 映射（PG events 表 stream_type 字段）
DOMAIN_STREAM_TYPE_MAP: dict[str, str] = {
    "order":        "order",
    "discount":     "order",        # 折扣是订单聚合根的一部分
    "payment":      "payment",
    "member":       "member",
    "inventory":    "inventory",
    "channel":      "channel",
    "reservation":  "reservation",
    "settlement":   "settlement",
    "safety":       "safety",
    "energy":       "energy",
    "campaign":     "campaign",
    "opinion":      "opinion",
    "review":       "review",
    "recipe":       "dish",
    "kds":          "order",
    "agent":        "agent",
    # 财务应收管理域（v156 新增）
    "deposit":      "deposit",
    "wine_storage": "wine_storage",
    "credit":       "credit",
}

# 所有事件类型枚举（用于校验）
ALL_EVENT_ENUMS = (
    OrderEventType,
    DiscountEventType,
    PaymentEventType,
    MemberEventType,
    InventoryEventType,
    ChannelEventType,
    ReservationEventType,
    SettlementEventType,
    SafetyEventType,
    EnergyEventType,
    ReviewEventType,
    OpinionEventType,
    RecipeEventType,
    KdsEventType,
    AgentEventType,
    # 财务应收管理域（v156 新增）
    DepositEventType,
    WineStorageEventType,
    CreditEventType,
    # 食安巡检域（v157 新增）
    SafetyInspectionEventType,
    # 营销活动域（v157 新增）
    CampaignEventType,
)


# ──────────────────────────────────────────────────────────────────────
# 财务应收管理域（押金 / 存酒 / 企业挂账，v156 新增）
# ──────────────────────────────────────────────────────────────────────

class DepositEventType(str, Enum):
    """押金事件"""

    COLLECTED = "deposit.collected"                        # 押金收取
    APPLIED = "deposit.applied"                            # 押金抵扣
    REFUNDED = "deposit.refunded"                          # 押金退还
    CONVERTED_TO_REVENUE = "deposit.converted_to_revenue"  # 转收入
    EXPIRED = "deposit.expired"                            # 押金过期


class WineStorageEventType(str, Enum):
    """存酒事件"""

    STORED = "wine_storage.stored"                         # 存酒
    RETRIEVED = "wine_storage.retrieved"                   # 取酒
    EXPIRING_SOON = "wine_storage.expiring_soon"           # 即将到期
    EXPIRED = "wine_storage.expired"                       # 已过期
    TRANSFERRED = "wine_storage.transferred"               # 转赠


class CreditEventType(str, Enum):
    """企业挂账事件"""

    CHARGED = "credit.charged"                             # 挂账消费
    BILL_GENERATED = "credit.bill_generated"               # 账单生成
    PAYMENT_RECEIVED = "credit.payment_received"           # 还款到账
    LIMIT_WARNING = "credit.limit_warning"                 # 额度预警（使用率 >80%）
    OVERDUE = "credit.overdue"                             # 账单逾期


class SafetyInspectionEventType(str, Enum):
    """食安巡检事件（对标 mv_safety_compliance 物化视图）"""

    INSPECTION_STARTED = "safety.inspection.started"
    INSPECTION_COMPLETED = "safety.inspection.completed"
    INSPECTION_FAILED = "safety.inspection.failed"           # 不合格
    CRITICAL_ITEM_FAILED = "safety.critical_item.failed"    # 关键项不合格（高优先级告警）
    INGREDIENT_EXPIRED = "safety.ingredient.expired"
    CORRECTION_OVERDUE = "safety.correction.overdue"        # 整改超期未完成


class CampaignEventType(str, Enum):
    """营销活动事件"""

    CREATED = "campaign.created"
    ACTIVATED = "campaign.activated"
    DEACTIVATED = "campaign.deactivated"
    COUPON_APPLIED = "campaign.coupon_applied"
    COUPON_EXPIRED = "campaign.coupon_expired"
    BUDGET_EXHAUSTED = "campaign.budget_exhausted"          # 活动预算耗尽


def resolve_stream_key(event_type: str) -> str:
    """根据事件类型字符串解析目标 Redis Stream key。

    取 event_type 的第一段（点分隔）作为域名，查表获取 stream key。
    未知域名时返回 "tx_unknown_events"。
    """
    domain = event_type.split(".")[0]
    return DOMAIN_STREAM_MAP.get(domain, "tx_unknown_events")


def resolve_stream_type(event_type: str) -> str:
    """根据事件类型字符串解析 PG events 表的 stream_type。"""
    domain = event_type.split(".")[0]
    return DOMAIN_STREAM_TYPE_MAP.get(domain, domain)
