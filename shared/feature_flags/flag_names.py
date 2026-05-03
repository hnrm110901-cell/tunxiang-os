"""
屯象OS Feature Flag 名称常量

用于避免硬编码字符串，防止拼写错误。
所有 Flag 名称按业务域分组为独立 class，便于 IDE 自动补全。

使用示例：
    from shared.feature_flags.flag_names import GrowthFlags, AgentFlags

    if is_enabled(GrowthFlags.JOURNEY_V2):
        run_v2_logic()
"""


class GrowthFlags:
    """增长中枢域 Flag 名称。"""

    # 增长中枢V2旅程模板（首单转二访/沉默召回/服务修复）
    JOURNEY_V2 = "growth.hub.journey_v2.enable"

    # 沉默召回V2（loss_aversion + relationship_warmup自动选择）
    RECALL_V2 = "growth.member.recall_v2.enable"

    # Agent建议自动发布（无需人工审核）—— 高风险，仅允许L3门店
    AGENT_AUTO_PUBLISH = "growth.agent.suggestion.auto_publish"

    # 触达频控引擎（防止过度营销）
    TOUCH_FREQUENCY_CONTROL = "growth.touch.frequency_control.enable"

    # 客户360页面
    CUSTOMER_360 = "growth.member.customer_360.enable"

    # 服务修复7态管理
    SERVICE_REPAIR = "growth.service.repair_7state.enable"

    # A/B测试自动选胜组
    AB_TEST_AUTO_WINNER = "growth.ab_test.auto_winner.enable"

    # 智能优惠券发放
    COUPON_INTELLIGENT_ISSUE = "growth.coupon.intelligent_issue.enable"


class AgentFlags:
    """Agent体系域 Flag 名称。"""

    # 智能排班建议（管理者可手动调整）
    HR_SHIFT_SUGGEST = "agent.hr.shift_suggest.enable"

    # 排班自动执行（L2自治级别）—— 高风险
    HR_SHIFT_AUTO_EXECUTE = "agent.hr.shift_suggest.auto_execute"

    # 沉默召回Agent
    GROWTH_DORMANT_RECALL = "agent.growth.dormant_recall.enable"

    # 会员洞察Agent
    GROWTH_MEMBER_INSIGHT = "agent.growth.member_insight.enable"

    # 日清E1-E8全流程追踪
    OPS_DAILY_REVIEW = "agent.ops.daily_review.enable"

    # 折扣健康预警（P0级）
    TRADE_DISCOUNT_ALERT = "agent.trade.discount_alert.enable"

    # P&L AI摘要
    FINANCE_PNL_SUMMARY = "agent.finance.pnl_summary.enable"

    # 7维离职风险预警
    ORG_ATTRITION_RISK = "agent.org.attrition_risk.enable"

    # 企微通知全局开关
    WECOM_NOTIFY = "agent.wecom_notify.enable"

    # L3全自治级别 —— 最高风险，需三级审批
    L3_AUTONOMY = "agent.l3_autonomy.enable"

    # Sprint D2: Agent 决策写入 ROI 四字段
    # （触发规划文档决策点 #1，需创始人签字后再开启）
    ROI_WRITEBACK = "agent.roi.writeback"

    # Sprint D4a: 成本根因 Skill Agent 启用开关
    COST_ROOT_CAUSE_ENABLE = "agent.cost_root_cause.enable"

    # Sprint D3a: RFM 触达 Skill Agent 启用开关（目标复购率 +5pp）
    RFM_OUTREACH_ENABLE = "agent.rfm_outreach.enable"

    # Sprint D4b: 薪资异常 Skill Agent 启用开关（加班/薪资环比稽核）
    SALARY_ANOMALY_ENABLE = "agent.salary_anomaly.enable"

    # Sprint D4c: 预算预测 Skill Agent 启用开关（月度预测 + 偏差识别）
    BUDGET_FORECAST_ENABLE = "agent.budget_forecast.enable"


class TradeFlags:
    """交易履约域 Flag 名称。"""

    # 外卖自动接单
    DELIVERY_AUTO_ACCEPT = "trade.delivery.auto_accept.enable"

    # 外卖聚合接单面板
    DELIVERY_AGGREGATOR = "trade.delivery.aggregator_panel.enable"

    # 折扣健康引擎
    DISCOUNT_HEALTH = "trade.discount.health_engine.enable"

    # 语音下单（依赖CoreML）
    VOICE_ORDER = "trade.voice_order.enable"

    # 分账引擎
    SPLIT_PAYMENT = "trade.split_payment.enable"

    # Sprint A4（Tier1）：RBAC 严格模式开关。on=敏感路由要求显式授权，off=legacy 行为。
    # 联动 tx-trade/src/security/rbac.py require_role/require_mfa 装饰器链路。
    RBAC_STRICT = "trade.rbac.strict"


class OrgFlags:
    """人力组织域 Flag 名称。"""

    # 营收驱动智能排班
    HR_REVENUE_SCHEDULE = "org.hr.revenue_schedule.enable"

    # 员工贡献度评分
    HR_CONTRIBUTION_SCORE = "org.hr.contribution_score.enable"

    # 7维离职预警模型
    HR_ATTRITION_MODEL = "org.hr.attrition_model.enable"

    # 实时人力毛利仪表盘
    HR_LABOR_MARGIN = "org.hr.labor_margin.enable"

    # 菜品技能匹配
    HR_SKILL_MATCH = "org.hr.skill_match.enable"

    # 企微/钉钉IM实接同步
    HR_IM_SYNC = "org.hr.im_sync.enable"

    # 电子签约模块
    HR_E_SIGNATURE = "org.hr.e_signature.enable"

    # 员工积分赛马机制
    HR_POINTS_RACE = "org.hr.points_race.enable"

    # 绩效在线打分评审
    HR_REVIEW_CYCLE = "org.hr.review_cycle.enable"

    # 薪税申报对接
    HR_TAX_FILING = "org.hr.tax_filing.enable"

    # 考勤深度合规检测
    HR_ATTENDANCE_COMPLIANCE = "org.hr.attendance_compliance.enable"


class MemberFlags:
    """会员CDP域 Flag 名称。"""

    # 客户360页面
    INSIGHT_360 = "member.insight.360_page.enable"

    # CLV计算引擎
    CLV_ENGINE = "member.clv.engine.enable"

    # GDPR匿名化（等保三级合规）
    GDPR_ANONYMIZE = "member.gdpr.anonymize.enable"

    # 生命周期自动分群
    LIFECYCLE_AUTO_SEGMENT = "member.lifecycle.auto_segment.enable"


class EdgeFlags:
    """边缘计算域 Flag 名称（Mac mini M4）。"""

    # 增量同步策略
    DELTA_SYNC = "edge.sync.delta_sync.enable"

    # CoreML本地推理（Neural Engine）
    COREML_INFERENCE = "edge.coreml.inference.enable"

    # 完全离线模式 —— 高风险
    OFFLINE_FULL_MODE = "edge.offline.full_mode.enable"

    # Edge节点自动更新
    AUTO_UPDATE = "edge.mac_station.auto_update.enable"

    # Sprint A2（Tier1）：Saga 本地 SQLite 缓冲 4h。
    # off=legacy 直写云端（无缓冲），on=断网时 enqueue 到 /var/tunxiang/saga_buffer.db
    # 5%→50%→100% 灰度，dead_letter 需人工确认不自动删除。
    PAYMENT_SAGA_BUFFER = "edge.payment.saga_buffer"

    # Sprint A3（Tier1）：离线订单号 UUID v7 前端生成。
    # off=legacy 服务端生成 order_id（TX+时间+uuid4.hex[:4]）
    # on=前端生成 `{device_id}:{ms_epoch}:{counter}` + UUID v7 payload
    # 5%→50%→100% 灰度，与 A2 saga_buffer idempotency_key 契约共享（settle:{order_id}）
    OFFLINE_ORDER_ID_BRIDGE = "edge.offline.order_id_bridge"

    # Sprint C3（Tier1）：KDS delta 同步接口启用开关。
    # off=保留全量轮询（legacy /api/v1/kds/tasks + WebSocket）
    # on=web-kds 走 /api/v1/kds/orders/delta 增量轮询 + device heartbeat
    #    共享 A3 device_id 格式；sync-engine Phase 1 依赖 edge_device_registry
    # 5%→50%→100% 灰度，4h E2E 零卡顿 / 60s 断网恢复全同步为门禁
    KDS_DELTA_SYNC = "edge.kds.delta_sync"

    # Sprint C3 §19（Tier1）：mark_offline_if_stale 60s 周期调度。
    # off=不启动调度任务（DEMO 演示拔 KDS 网线 11min 后 health_status 永远停留 healthy）
    # on=tx-trade lifespan 启动 60s 周期 task → 跨租户调用
    #    DeviceRegistryService.mark_offline_if_stale_global，超 600s 心跳标 offline
    # 默认 off：先在 DEMO 环境验证后再灰度，避免误标 offline 干扰真实运维
    MARK_OFFLINE_SCHEDULER = "edge.kds.mark_offline_scheduler"


class SupplyFlags:
    """供应链域 Flag 名称。"""

    # 收货验收功能（入库加权均价计算）
    RECEIVING_INSPECTION = "supply.receiving.inspection.enable"

    # 门店调拨运输损耗检测
    TRANSFER_LOSS_DETECTION = "supply.transfer.loss_detection.enable"

    # AI智能补货计划（需要tx-brain支持）
    SMART_REORDER = "supply.intel.smart_reorder.enable"


class VietnamFlags:
    """Vietnam market (Phase 3, Sprint 3.5) Flag 名称。"""

    # 越南市场全局开关
    VIETNAM_ENABLED = "market.vietnam.enabled"

    # VAT 8%/10% 计算引擎
    VAT_CALCULATION = "market.vietnam.vat.enabled"

    # 越南 e-Invoice（配合 VAT）
    EINVOICE_INVOICE = "market.vietnam.einvoice"

    # MoMo 电子钱包支付
    PAYMENT_MOMO = "market.vietnam.payment.momo"

    # ZaloPay 支付
    PAYMENT_ZALOPAY = "market.vietnam.payment.zalopay"

    # GrabFood 越南外卖
    DELIVERY_GRABFOOD = "market.vietnam.delivery.grabfood"

    # ShopeeFood 越南外卖
    DELIVERY_SHOPEEFOOD = "market.vietnam.delivery.shopeefood"


class IndonesiaFlags:
    """Indonesia market (Phase 3, Sprint 3.4) Flag 名称。"""

    # 印度尼西亚市场全局开关
    INDONESIA_ENABLED = "market.indonesia.enabled"

    # PPN 11% 计算引擎（替代中国 VAT）
    PPN_CALCULATION = "market.indonesia.ppn.enabled"

    # e-Faktur 电子发票（配合 DJP）
    EINVOICE_EFAKTUR = "market.indonesia.einvoice.efaktur"

    # GoPay 电子钱包支付
    PAYMENT_GOPAY = "market.indonesia.payment.gopay"

    # DANA 电子钱包支付
    PAYMENT_DANA = "market.indonesia.payment.dana"

    # GoFood 外卖平台
    DELIVERY_GOFOOD = "market.indonesia.delivery.gofood"

    # ShopeeFood 印尼外卖
    DELIVERY_SHOPEEFOOD = "market.indonesia.delivery.shopeefood"


class KnowledgeFlags:
    """知识库域 Flag 名称。"""

    # Phase 1: pgvector 混合检索（替代 Qdrant）
    HYBRID_SEARCH_V2 = "knowledge.search.hybrid_v2.enable"

    # Phase 1: 文档处理管线
    DOCUMENT_PIPELINE = "knowledge.document.pipeline.enable"

    # Phase 2: Agentic RAG（智能检索路由）
    AGENTIC_RAG = "knowledge.rag.agentic.enable"

    # Phase 2: 纠错式 RAG（检索质量自动修正）
    CORRECTIVE_RAG = "knowledge.rag.corrective.enable"

    # Phase 3: LightRAG 知识图谱增强
    LIGHTRAG_GRAPH = "knowledge.graph.lightrag.enable"

    # Phase 4: 边缘知识同步（Mac mini 本地副本）
    EDGE_KNOWLEDGE_SYNC = "knowledge.edge.sync.enable"
