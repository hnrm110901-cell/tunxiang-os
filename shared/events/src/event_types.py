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

    CREATED = "order.created"  # 订单创建
    ITEM_ADDED = "order.item_added"  # 加菜
    ITEM_removed = "order.item_removed"  # 退菜
    SUBMITTED = "order.submitted"  # 提交出餐
    PAID = "order.paid"  # 支付完成
    CANCELLED = "order.cancelled"  # 取消
    REFUNDED = "order.refunded"  # 整单退款
    PARTIAL_REFUNDED = "order.partial_refunded"  # 部分退款
    CLOSED = "order.closed"  # 结账关闭
    BILLING_RULE_APPLIED = "order.billing_rule_applied"  # 账单规则（最低消费/服务费）应用


class DiscountEventType(str, Enum):
    """折扣授权事件 — 因果链①折扣健康"""

    APPLIED = "discount.applied"  # 折扣被应用
    AUTHORIZED = "discount.authorized"  # 主管授权
    REVOKED = "discount.revoked"  # 折扣撤销
    THRESHOLD_EXCEEDED = "discount.threshold_exceeded"  # 超授权阈值
    LEAK_DETECTED = "discount.leak_detected"  # Agent检测到泄漏


class PaymentEventType(str, Enum):
    """支付事件 — 因果链⑦日清日结"""

    INITIATED = "payment.initiated"  # 发起支付
    CONFIRMED = "payment.confirmed"  # 支付确认
    FAILED = "payment.failed"  # 支付失败
    REFUNDED = "payment.refunded"  # 退款
    CASH_DECLARED = "payment.cash_declared"  # 现金申报
    CHANNEL_SETTLED = "payment.channel_settled"  # 渠道结算到账


class MemberEventType(str, Enum):
    """会员事件 — 因果链⑤会员真ROI"""

    REGISTERED = "member.registered"  # 注册
    RECHARGED = "member.recharged"  # 储值充值（负债事件）
    CONSUMED = "member.consumed"  # 储值消费（收入确认事件）
    VOUCHER_ISSUED = "member.voucher_issued"  # 发券
    VOUCHER_USED = "member.voucher_used"  # 核销券
    VOUCHER_EXPIRED = "member.voucher_expired"  # 券过期
    UPGRADED = "member.upgraded"  # 等级升级
    POINTS_CHANGED = "member.points_changed"  # 积分变动
    CHURN_PREDICTED = "member.churn_predicted"  # Agent预测流失


class InventoryEventType(str, Enum):
    """库存/损耗事件 — 因果链③BOM推算"""

    RECEIVED = "inventory.received"  # 入库
    CONSUMED = "inventory.consumed"  # 出库（BOM推算）
    WASTED = "inventory.wasted"  # 损耗登记
    ADJUSTED = "inventory.adjusted"  # 盘点调整
    EXPIRED = "inventory.expired"  # 过期报废
    LOW_STOCK = "inventory.low_stock"  # 库存预警
    TRANSFER_IN = "inventory.transfer_in"  # 调拨入库
    TRANSFER_OUT = "inventory.transfer_out"  # 调拨出库


class ChannelEventType(str, Enum):
    """渠道事件 — 因果链②外卖真毛利"""

    ORDER_SYNCED = "channel.order_synced"  # 渠道订单同步
    COMMISSION_CALC = "channel.commission_calc"  # 佣金计算
    SETTLEMENT = "channel.settlement"  # 渠道结算
    PROMOTION_APPLIED = "channel.promotion_applied"  # 平台活动补贴
    CHARGEBACK = "channel.chargeback"  # 渠道拒付


class ReservationEventType(str, Enum):
    """预订/宴会事件 — 因果链⑥宴会收入链"""

    CREATED = "reservation.created"  # 预订创建
    CONFIRMED = "reservation.confirmed"  # 确认预订
    CANCELLED = "reservation.cancelled"  # 取消预订
    BANQUET_DEPOSIT_PAID = "reservation.banquet_deposit_paid"  # 宴会定金
    BANQUET_MENU_CONFIRMED = "reservation.banquet_menu_confirmed"  # 菜单确认
    BANQUET_SETTLED = "reservation.banquet_settled"  # 宴会结账


class SettlementEventType(str, Enum):
    """财务结算事件 — 因果链⑦日清日结"""

    DAILY_CLOSED = "settlement.daily_closed"  # 日结完成
    RECONCILED = "settlement.reconciled"  # 对账完成
    DISCREPANCY_FOUND = "settlement.discrepancy_found"  # 差异发现
    REVENUE_RECOGNIZED = "settlement.revenue_recognized"  # 收入确认
    STORED_VALUE_DEFERRED = "settlement.stored_value_deferred"  # 储值负债入账
    ADVANCE_CONSUMED = "settlement.advance_consumed"  # 预收款转收入


# ──────────────────────────────────────────────────────────────────────
# 新增模块（事件总线上的自然延伸，方案第5节）
# ──────────────────────────────────────────────────────────────────────


class SafetyEventType(str, Enum):
    """食品安全合规事件 — 法律义务（市场监管总局要求）"""

    SAMPLE_LOGGED = "safety.sample_logged"  # 留样登记
    TEMPERATURE_RECORDED = "safety.temperature_recorded"  # 温度记录
    INSPECTION_DONE = "safety.inspection_done"  # 检查完成
    VIOLATION_FOUND = "safety.violation_found"  # 违规发现
    EXPIRY_ALERT = "safety.expiry_alert"  # 临期预警
    CERTIFICATE_UPDATED = "safety.certificate_updated"  # 证件更新
    TRAINING_COMPLETED = "safety.training_completed"  # 食安培训完成
    # HACCP 检查计划专属事件（v163 新增）
    HACCP_CHECK_COMPLETED = "safety.haccp_check_completed"  # HACCP检查执行完成
    HACCP_CRITICAL_FAILURE = "safety.haccp_critical_failure"  # HACCP关键控制点失控


class EnergyEventType(str, Enum):
    """能耗管理事件 — IoT智能电表/燃气表"""

    READING_CAPTURED = "energy.reading_captured"  # 抄表数据
    ANOMALY_DETECTED = "energy.anomaly_detected"  # 异常能耗
    ALERT_SENT = "energy.alert_sent"  # 告警推送
    BENCHMARK_SET = "energy.benchmark_set"  # 基准线设置
    BUDGET_SET = "energy.budget_set"  # 月度预算配置（v164 新增）
    ALERT_RULE_CREATED = "energy.alert_rule_created"  # 告警规则创建（v164 新增）


class DeliveryTempEventType(str, Enum):
    """配送在途温控事件 — 海鲜冷链命门（v368 新增 / TASK-3）

    覆盖配送车温控全生命周期：
      - RECORDED:       温度上报（每条可发，可降采样到每分钟一条）
      - BREACH_STARTED: 连续超限达阈值时长，告警触发
      - BREACH_ENDED:   超限恢复或人工处理结束
    """

    RECORDED = "delivery.temperature_recorded"  # 温度记录上报
    BREACH_STARTED = "delivery.temperature_breach"  # 超限告警触发
    BREACH_ENDED = "delivery.temperature_breach_ended"  # 超限恢复/告警关闭


class ReviewEventType(str, Enum):
    """舆情/评价事件"""

    CAPTURED = "review.captured"  # 评价采集
    SENTIMENT_ANALYZED = "review.sentiment_analyzed"  # 情感分析完成
    ATTRIBUTED = "review.attributed"  # 归因到菜品/员工
    RESPONDED = "review.responded"  # 商家回复


class OpinionEventType(str, Enum):
    """公众舆情监控事件（PublicOpinionProjector 消费）"""

    MENTION_CAPTURED = "opinion.mention_captured"  # 新舆情采集
    RESOLVED = "opinion.resolved"  # 舆情已处理
    SENTIMENT_ANALYZED = "opinion.sentiment_analyzed"  # 情感分析完成
    ESCALATED = "opinion.escalated"  # 舆情升级（需人工介入）


class RecipeEventType(str, Enum):
    """成本卡事件 — 动态毛利"""

    COST_UPDATED = "recipe.cost_updated"  # 成本卡更新
    PROCUREMENT_PRICE_CHANGED = "recipe.procurement_price_changed"  # 采购价变动
    MENU_PRICE_ADJUSTED = "recipe.menu_price_adjusted"  # 菜单价格调整
    MARGIN_ALERT = "recipe.margin_alert"  # 毛利预警


class PriceEventType(str, Enum):
    """供应链价格台账事件 — 价格快照写入与异常预警（v366 新增）

    由 services/tx-supply/src/services/price_ledger_service.py 触发：
      - RECORDED：每次收货确认/采购单/手工录入完成后立即发射
      - ALERT_TRIGGERED：价格快照写入后命中预警规则时发射
    """

    RECORDED = "price.recorded"  # 价格快照写入
    ALERT_TRIGGERED = "price.alert_triggered"  # 命中预警阈值


# ──────────────────────────────────────────────────────────────────────
# 屯象OS系统级域
# ──────────────────────────────────────────────────────────────────────


class TableEventType(str, Enum):
    """桌台会话事件 — 桌台中心化架构核心事件流（v149新增）

    桌台会话是门店业务聚合根，以下事件覆盖一次完整就餐旅程：
      开台 → 点菜 → 用餐 → (加菜) → 买单 → 结账 → 清台

    Agent 订阅此流可感知每张桌台的实时状态，支持：
      - 折扣守护：感知同会话折扣叠加，防绕过单笔上限
      - 出餐调度：按会话综合优先级（VIP/等待时长/催菜次数）排序
      - 会员洞察：VIP_IDENTIFIED 触发时实时推送个性化服务建议
      - 翻台率 Agent：OVERSTAY_ALERT 触发后主动干预
    """

    OPENED = "table.opened"  # 开台（创建 TableSession）
    ORDER_PLACED = "table.order_placed"  # 首次点菜完成（主单提交）
    ADD_ORDERED = "table.add_ordered"  # 加菜（追加点单，order_sequence >= 2）
    DISH_SERVED = "table.dish_served"  # 菜品上桌确认（KDS 出餐扫描/手动确认）
    SERVICE_CALLED = "table.service_called"  # 服务呼叫（催菜/呼叫服务员/需要物品）
    BILL_REQUESTED = "table.bill_requested"  # 请求买单（买单按钮/扫码自助买单）
    PAID = "table.paid"  # 结账完成（支付成功）
    CLEARED = "table.cleared"  # 清台完成（桌台归还为空闲状态）
    TRANSFERRED = "table.transferred"  # 转台（会话迁移到新桌台）
    MERGED = "table.merged"  # 并台（多会话合并为主会话）
    SPLIT = "table.split"  # 拆台（主会话拆分为独立会话）
    VIP_IDENTIFIED = "table.vip_identified"  # VIP 识别（开台/中途扫码/人脸识别）
    OVERSTAY_ALERT = "table.overstay_alert"  # 超时预警（Agent 触发，超过门店设定翻台上限）
    WAITER_CHANGED = "table.waiter_changed"  # 换服务员（责任服务员变更）
    GUEST_COUNT_UPDATED = "table.guest_count_updated"  # 就餐人数修改


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
    ALERT_ACKNOWLEDGED = "agent.alert_acknowledged"  # 老板在WeCom确认告警


# ──────────────────────────────────────────────────────────────────────
# 全局注册表
# ──────────────────────────────────────────────────────────────────────

# 域名 -> Redis Stream key 映射（投影器消费用）
DOMAIN_STREAM_MAP: dict[str, str] = {
    # 桌台会话域（v149新增，桌台中心化核心）
    "table": "tx_dining_session_events",  # 桌台堂食会话域（v149，dining_sessions表）
    # 核心业务域
    "order": "tx_order_events",
    "discount": "tx_discount_events",
    "payment": "tx_payment_events",
    "member": "tx_member_events",
    "inventory": "tx_inventory_events",
    "channel": "tx_channel_events",
    "reservation": "tx_reservation_events",
    "settlement": "tx_settlement_events",
    # 新增模块
    "safety": "tx_safety_events",
    "energy": "tx_energy_events",
    # 配送在途温控（v368 / TASK-3，海鲜冷链命门）
    "delivery": "tx_delivery_events",
    "opinion": "tx_opinion_events",
    "review": "tx_review_events",
    "recipe": "tx_recipe_events",
    # 系统域
    "kds": "tx_kds_events",
    "agent": "tx_agent_events",
    # 财务应收管理域（v156 新增）
    "deposit": "tx_deposit_events",
    "wine_storage": "tx_wine_storage_events",
    "credit": "tx_credit_events",
    # 营销活动域（v157 新增）
    "campaign": "tx_campaign_events",
    # 增长中枢域（v184 新增）
    "growth": "tx_growth_events",
    # 知识库域
    "knowledge": "tx_knowledge_events",
    # 库位域（v367 TASK-2，仓储细化）
    "location": "tx_location_events",
    # 配送签收凭证域（v369 新增，TASK-4）
    "delivery": "tx_delivery_events",
    # 盘亏处理审批闭环（v370 新增，TASK-5）
    "stocktake": "tx_stocktake_events",
    # 旧系统适配器域（Sprint F1 / PR F，14 个 POS / 外卖 / 物流 / 财税适配器统一入口）
    "adapter": "tx_adapter_events",
    # 供应链价格台账域（v366 新增）
    "price": "tx_price_events",
    # 兼容旧域
    "trade": "trade_events",
    "supply": "supply_events",
    "finance": "finance_events",
    "org": "org_events",
    "menu": "menu_events",
    "ops": "ops_events",
}

# 域名 -> stream_type 映射（PG events 表 stream_type 字段）
DOMAIN_STREAM_TYPE_MAP: dict[str, str] = {
    "table": "dining_session",  # 桌台堂食会话域（v149，dining_sessions表）
    "order": "order",
    "discount": "order",  # 折扣是订单聚合根的一部分
    "payment": "payment",
    "member": "member",
    "inventory": "inventory",
    "channel": "channel",
    "reservation": "reservation",
    "settlement": "settlement",
    "safety": "safety",
    "energy": "energy",
    "delivery": "delivery",
    "campaign": "campaign",
    "opinion": "opinion",
    "review": "review",
    "recipe": "dish",
    "kds": "order",
    "agent": "agent",
    # 财务应收管理域（v156 新增）
    "deposit": "deposit",
    "wine_storage": "wine_storage",
    "credit": "credit",
    # 增长中枢域（v184 新增）
    "growth": "growth",
    # 知识库域
    "knowledge": "knowledge",
    # 库位域（v367 TASK-2）
    "location": "location",
    # 盘亏处理审批闭环（v370 新增，TASK-5）
    "stocktake": "stocktake_loss_case",
    # 旧系统适配器域（Sprint F1 / PR F）
    "adapter": "adapter",
    # 供应链价格台账域（v366 新增）
    "price": "price",
}

# ──────────────────────────────────────────────────────────────────────
# 财务应收管理域（押金 / 存酒 / 企业挂账，v156 新增）
# ──────────────────────────────────────────────────────────────────────


class DepositEventType(str, Enum):
    """押金事件"""

    COLLECTED = "deposit.collected"  # 押金收取
    REGISTERED = "deposit.registered"  # 宴会定金登记（收取的别名，模块4.1）
    APPLIED = "deposit.applied"  # 押金抵扣
    CONVERTED = "deposit.converted"  # 定金转预收（宴会结账抵扣，模块4.1）
    REFUNDED = "deposit.refunded"  # 押金退还
    CONVERTED_TO_REVENUE = "deposit.converted_to_revenue"  # 转收入
    EXPIRED = "deposit.expired"  # 押金过期


class WineStorageEventType(str, Enum):
    """存酒事件"""

    STORED = "wine_storage.stored"  # 存酒
    RETRIEVED = "wine_storage.retrieved"  # 取酒
    EXPIRING_SOON = "wine_storage.expiring_soon"  # 即将到期
    EXPIRED = "wine_storage.expired"  # 已过期
    TRANSFERRED = "wine_storage.transferred"  # 转赠


class CreditEventType(str, Enum):
    """企业挂账事件"""

    CHARGED = "credit.charged"  # 挂账消费
    BILL_GENERATED = "credit.bill_generated"  # 账单生成
    PAYMENT_RECEIVED = "credit.payment_received"  # 还款到账
    LIMIT_WARNING = "credit.limit_warning"  # 额度预警（使用率 >80%）
    OVERDUE = "credit.overdue"  # 账单逾期


class SafetyInspectionEventType(str, Enum):
    """食安巡检事件（对标 mv_safety_compliance 物化视图）"""

    INSPECTION_STARTED = "safety.inspection.started"
    INSPECTION_COMPLETED = "safety.inspection.completed"
    INSPECTION_FAILED = "safety.inspection.failed"  # 不合格
    CRITICAL_ITEM_FAILED = "safety.critical_item.failed"  # 关键项不合格（高优先级告警）
    INGREDIENT_EXPIRED = "safety.ingredient.expired"
    CORRECTION_OVERDUE = "safety.correction.overdue"  # 整改超期未完成


class CampaignEventType(str, Enum):
    """营销活动事件"""

    CREATED = "campaign.created"
    ACTIVATED = "campaign.activated"
    DEACTIVATED = "campaign.deactivated"
    COUPON_APPLIED = "campaign.coupon_applied"
    COUPON_EXPIRED = "campaign.coupon_expired"
    BUDGET_EXHAUSTED = "campaign.budget_exhausted"  # 活动预算耗尽


class StocktakeLossEventType(str, Enum):
    """盘亏处理审批闭环事件 — 案件登记 → 审批 → 财务核销

    供 tx-finance 通过事件订阅自动生成凭证（不需要直接 API 调用）。
    """

    CASE_CREATED = "stocktake.loss_case_created"  # 案件登记（DRAFT 状态）
    SUBMITTED = "stocktake.loss_submitted"  # 提交审批（→ PENDING_APPROVAL）
    APPROVED = "stocktake.loss_approved"  # 最终节点通过（→ APPROVED，触发 tx-finance 准备凭证）
    REJECTED = "stocktake.loss_rejected"  # 任一节点驳回（→ REJECTED）
    WRITTEN_OFF = "stocktake.loss_written_off"  # 财务核销完成（→ WRITTEN_OFF）


# ──────────────────────────────────────────────────────────────────────
# 增长中枢域（私域复购链路，v184 新增）
# ──────────────────────────────────────────────────────────────────────


class KnowledgeEventType(str, Enum):
    """知识库域事件"""

    DOCUMENT_UPLOADED = "knowledge.document.uploaded"
    DOCUMENT_PROCESSED = "knowledge.document.processed"
    DOCUMENT_PUBLISHED = "knowledge.document.published"
    DOCUMENT_ARCHIVED = "knowledge.document.archived"
    CHUNK_INDEXED = "knowledge.chunk.indexed"
    GRAPH_ENTITY_EXTRACTED = "knowledge.graph.entity_extracted"
    QUERY_ANSWERED = "knowledge.query.answered"
    STALE_ALERT = "knowledge.stale.alert"


class MenuEventType(str, Enum):
    """菜谱方案事件 — 模块3.4 批量下发与门店差异化"""

    PLAN_CREATED = "menu.plan_created"  # 方案创建
    PLAN_PUBLISHED = "menu.plan_published"  # 方案发布（draft→published）
    PLAN_DISTRIBUTED = "menu.plan_distributed"  # 方案批量下发到门店
    PLAN_ROLLED_BACK = "menu.plan_rolled_back"  # 回滚到历史版本
    STORE_OVERRIDE_SET = "menu.store_override_set"  # 门店微调（价格/状态覆盖）
    STORE_OVERRIDE_RESET = "menu.store_override_reset"  # 门店覆盖全部重置为集团方案


class AdapterEventType(str, Enum):
    """旧系统适配器事件 — 14 个 POS / 外卖 / 物流 / 财税适配器统一留痕（Sprint F1 / PR F）

    因果链：14 适配器（品智/奥琦玮/天财/美团/饿了么/抖音/微信/物流/科脉/微生活/
    宜鼎/诺诺/小红书/ERP）与屯象事件总线的唯一接入面。所有抓取/推送/回写/
    webhook 回调都通过本类型枚举进入 tx_adapter_events 流，下游 Agent 和
    SRE 驾驶舱按 adapter_name 维度看健康度。

    设计原则：
      - SYNC_STARTED/FINISHED 成对（便于算耗时与成功率）
      - ORDER_INGESTED / MENU_SYNCED / MEMBER_SYNCED / INVENTORY_SYNCED 按实体分流
      - SYNC_FAILED 携带 error_code 便于 Grafana 按 code 聚类
      - RECONNECTED 监测长期故障后首次恢复（P0 告警触发条件）
      - WEBHOOK_RECEIVED 作为三方回调链路的入口事件（外卖退单、异议、票据回执）
    """

    SYNC_STARTED = "adapter.sync_started"  # 同步开始（按 scope=orders/menu/members/inventory 区分）
    SYNC_FINISHED = "adapter.sync_finished"  # 同步成功结束
    SYNC_FAILED = "adapter.sync_failed"  # 同步失败（需 payload.error_code）
    ORDER_INGESTED = "adapter.order_ingested"  # 单条外卖/POS 订单入库
    MENU_SYNCED = "adapter.menu_synced"  # 菜品同步批次
    MEMBER_SYNCED = "adapter.member_synced"  # 会员同步批次
    INVENTORY_SYNCED = "adapter.inventory_synced"  # 库存同步批次
    STATUS_PUSHED = "adapter.status_pushed"  # 状态回写三方（并行运行期关键事件）
    WEBHOOK_RECEIVED = "adapter.webhook_received"  # 三方 webhook 回调入口
    RECONNECTED = "adapter.reconnected"  # 长时故障后首次恢复（触发 Agent 重算）
    CREDENTIAL_EXPIRED = "adapter.credential_expired"  # Token/AccessKey 到期


class LocationEventType(str, Enum):
    """库位事件 — 仓储库存细化（v367 TASK-2）

    用于追踪库位级别的库存变更与食材绑定操作：
      INVENTORY_MOVED    — 库位间转移（更新 inventory_by_location）
      LOCATION_BOUND     — 食材绑定到主库位
    """

    INVENTORY_MOVED = "location.inventory_moved"
    LOCATION_BOUND = "location.location_bound"


class DeliveryProofEventType(str, Enum):
    """配送签收凭证事件（TASK-4，v369 新增）

    覆盖配送末端三个关键节点：
      1. 电子签收完成（SIGNED）          — 触发结算/对账
      2. 损坏拍照取证上报（DAMAGE_REPORTED） — 触发供应商索赔流程
      3. 损坏处理决议（DAMAGE_RESOLVED）  — RETURNED 时财务侧自动开红字凭证
    """

    SIGNED = "delivery.signed"
    DAMAGE_REPORTED = "delivery.damage_reported"
    DAMAGE_RESOLVED = "delivery.damage_resolved"


class GrowthEventType(str, Enum):
    """增长中枢事件 — 私域复购链路"""

    FIRST_ORDER_COMPLETED = "growth.first_order_completed"
    SILENT_DETECTED = "growth.silent_detected"
    COMPLAINT_CLOSED = "growth.complaint_closed"
    TOUCH_DELIVERED = "growth.touch_delivered"
    ORDER_ATTRIBUTED = "growth.order_attributed"
    SUGGESTION_PUBLISHED = "growth.agent_suggestion_published"
    REPAIR_STATE_CHANGED = "growth.repair_state_changed"
    ENROLLMENT_STATE_CHANGED = "growth.enrollment_state_changed"
    # V3.0 外部信号触发
    CALENDAR_TRIGGER_FIRED = "growth.calendar_trigger_fired"
    WEATHER_SIGNAL_RECEIVED = "growth.weather_signal_received"
    STORE_READINESS_EVALUATED = "growth.store_readiness_evaluated"


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


# 所有事件类型枚举（用于校验）— 放在所有类定义之后，避免 forward reference
ALL_EVENT_ENUMS = (
    TableEventType,  # 桌台会话域（v149）
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
    DeliveryTempEventType,
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
    # 盘亏处理审批闭环（v370 新增）
    StocktakeLossEventType,
    # 知识库域
    KnowledgeEventType,
    # 增长中枢域（v184 新增）
    GrowthEventType,
    # 配送签收凭证域（v369 新增，TASK-4）
    DeliveryProofEventType,
    # 菜谱方案域（v245 新增，模块3.4）
    MenuEventType,
    # 库位域（v367 TASK-2，仓储细化）
    LocationEventType,
    # 旧系统适配器域（Sprint F1 / PR F）
    AdapterEventType,
    # 供应链价格台账域（v366 新增）
    PriceEventType,
)
