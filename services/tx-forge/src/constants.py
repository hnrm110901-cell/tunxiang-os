"""tx-forge 常量定义 — 应用市场 & AI Agent 注册表"""

# ── 应用分类 ──────────────────────────────────────────────
APP_CATEGORIES: dict[str, dict] = {
    "supply_chain":  {"name": "供应链",   "icon": "📦", "description": "采购、库存、配送管理"},
    "delivery":      {"name": "外卖配送", "icon": "🛵", "description": "外卖平台对接与骑手调度"},
    "finance":       {"name": "财务",     "icon": "💰", "description": "发票、对账、税务合规"},
    "ai_addon":      {"name": "AI增值",   "icon": "🤖", "description": "智能推荐、预测、自动化"},
    "iot":           {"name": "IoT设备",  "icon": "📡", "description": "智能厨房、传感器、物联网"},
    "analytics":     {"name": "数据分析", "icon": "📊", "description": "经营报表与决策洞察"},
    "marketing":     {"name": "营销",     "icon": "📣", "description": "优惠券、活动、私域运营"},
    "hr":            {"name": "人力资源", "icon": "👥", "description": "排班、考勤、薪资管理"},
    "payment":       {"name": "支付",     "icon": "💳", "description": "聚合支付与资金管理"},
    "compliance":    {"name": "合规",     "icon": "🛡️", "description": "食品安全、等保、审计"},
}

# ── 定价模型 ──────────────────────────────────────────────
PRICING_MODELS: dict[str, dict] = {
    "free":         {"name": "免费",       "platform_fee_rate": 0.00},
    "one_time":     {"name": "一次性买断", "platform_fee_rate": 0.20},
    "monthly":      {"name": "月订阅",     "platform_fee_rate": 0.15},
    "per_store":    {"name": "按门店计费", "platform_fee_rate": 0.15},
    "usage_based":  {"name": "按用量计费", "platform_fee_rate": 0.10},
    "freemium":     {"name": "免费增值",   "platform_fee_rate": 0.15},
}

# ── 枚举集合 ──────────────────────────────────────────────
DEV_TYPES: set[str] = {"individual", "company", "internal"}

APP_STATUSES: set[str] = {
    "draft", "submitted", "in_review", "approved",
    "published", "rejected", "suspended", "deprecated",
}

REVIEW_DECISIONS: set[str] = {"approved", "rejected", "needs_revision"}

PAYOUT_STATUSES: set[str] = {"pending", "processing", "completed", "failed"}

# ── AI Agent 注册表 ───────────────────────────────────────
AGENT_REGISTRY: list[dict] = [
    {"agent_id": "discount_guardian",   "name": "折扣守护", "priority": "P0", "inference_layer": "edge+cloud"},
    {"agent_id": "menu_recommender",    "name": "智能排菜", "priority": "P0", "inference_layer": "cloud"},
    {"agent_id": "kitchen_dispatcher",  "name": "出餐调度", "priority": "P1", "inference_layer": "edge"},
    {"agent_id": "member_insight",      "name": "会员洞察", "priority": "P1", "inference_layer": "cloud"},
    {"agent_id": "inventory_alerter",   "name": "库存预警", "priority": "P1", "inference_layer": "edge+cloud"},
    {"agent_id": "finance_auditor",     "name": "财务稽核", "priority": "P1", "inference_layer": "cloud"},
    {"agent_id": "patrol_inspector",    "name": "巡店质检", "priority": "P2", "inference_layer": "cloud"},
    {"agent_id": "smart_service",       "name": "智能客服", "priority": "P2", "inference_layer": "cloud"},
    {"agent_id": "private_domain",      "name": "私域运营", "priority": "P2", "inference_layer": "cloud"},
]

# ─── v1.5 Trust & Governance ──────────────────────────────────────────

TRUST_TIERS = {
    "T0": {"name": "实验室", "data_access": "none", "action_scope": "none", "financial": False, "sort": 0},
    "T1": {"name": "社区", "data_access": "read", "action_scope": "none", "financial": False, "sort": 1},
    "T2": {"name": "认证", "data_access": "read_write", "action_scope": "non_financial", "financial": False, "sort": 2},
    "T3": {"name": "信赖", "data_access": "read_write", "action_scope": "all", "financial": True, "sort": 3},
    "T4": {"name": "官方", "data_access": "full", "action_scope": "all", "financial": True, "sort": 4},
}

TRUST_AUDIT_TYPES = {"upgrade", "downgrade", "initial", "suspend"}

VIOLATION_TYPES = {
    "permission_denied", "token_exceeded", "rate_limited",
    "constraint_violated", "kill_switched", "data_boundary", "action_blocked"
}

VIOLATION_SEVERITIES = {"P0", "P1", "P2", "P3"}

MCP_TRANSPORTS = {"stdio", "sse", "streamable-http"}

CORE_ENTITIES = {"Store", "Order", "Customer", "Dish", "Ingredient", "Employee"}

ACCESS_MODES = {"read", "write", "read_write"}

# OWASP Agentic Top 10 checklist
OWASP_AGENTIC_TOP10 = [
    {"id": "OA01", "threat": "目标劫持", "check": "prompt_injection_test", "automated": True},
    {"id": "OA02", "threat": "工具滥用", "check": "action_whitelist_audit", "automated": True},
    {"id": "OA03", "threat": "权限过度", "check": "least_privilege_check", "automated": True},
    {"id": "OA04", "threat": "失控Agent", "check": "token_budget_enforcement", "automated": True},
    {"id": "OA05", "threat": "记忆投毒", "check": "memory_content_audit", "automated": False},
    {"id": "OA06", "threat": "级联失败", "check": "dependency_circuit_breaker", "automated": True},
    {"id": "OA07", "threat": "数据泄露", "check": "pii_detection_audit", "automated": True},
    {"id": "OA08", "threat": "输出篡改", "check": "hard_constraint_enforcement", "automated": True},
    {"id": "OA09", "threat": "模型窃取", "check": "rate_limit_anomaly_detection", "automated": True},
    {"id": "OA10", "threat": "供应链攻击", "check": "dependency_cve_scan", "automated": True},
]

# ─── v2.0 Agent Exchange ──────────────────────────────────────────────

OUTCOME_TYPES = {
    "conversion", "retention", "revenue_lift", "cost_saved",
    "complaint_resolved", "recommendation_accepted",
    "churn_prevented", "upsell_success"
}

MEASUREMENT_METHODS = {"event_count", "delta_compare", "attribution"}

VERIFICATION_METHODS = {"auto", "manual", "hybrid"}

EVIDENCE_CARD_TYPES = {
    "security_scan", "performance_benchmark", "compliance_cert",
    "guardrail_test", "customer_case", "data_privacy", "uptime_sla"
}

TARGET_ROLES = {"品牌总监", "门店店长", "运营经理", "财务总监"}

TOKEN_PERIOD_TYPES = {"daily", "monthly"}

# ─── v2.5 Developer Enablement ────────────────────────────────────────

BUILDER_TEMPLATE_TYPES = {
    "data_analysis": "数据分析型 — 读取Ontology→Claude分析→生成报告",
    "automation": "自动化执行型 — 事件触发→条件判断→执行Action",
    "conversational": "对话交互型 — 用户提问→检索知识库→回答",
    "monitoring": "监控预警型 — 定时巡检→异常检测→告警",
    "optimization": "优化决策型 — 收集数据→建模→推荐→人类审批",
}

BUILDER_PROJECT_STATUSES = {"draft", "building", "preview", "submitted", "archived"}

# ─── v3.0 Ecosystem Flywheel ─────────────────────────────────────────

ALLIANCE_SHARING_MODES = {"public", "invited", "private"}
ALLIANCE_TRANSACTION_TYPES = {"subscription", "outcome", "token_usage"}

WORKFLOW_STATUSES = {"draft", "active", "paused", "archived"}
WORKFLOW_TRIGGER_TYPES = {"event", "schedule", "manual"}
WORKFLOW_RUN_STATUSES = {"running", "completed", "failed", "cancelled"}

ECOSYSTEM_METRIC_WEIGHTS = {
    "isv_active_rate": 0.15,
    "product_quality_score": 0.15,
    "install_density": 0.15,
    "outcome_conversion_rate": 0.15,
    "token_efficiency": 0.10,
    "developer_nps": 0.10,
    "tthw_minutes": 0.10,
    "ecosystem_gmv_fen": 0.10,
}
