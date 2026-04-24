from .ai_marketing_orchestrator import AiMarketingOrchestratorAgent
from .ai_waiter import AIWaiterAgent

# Sprint D1 / PR 批次 5：合规运营（waived + margin + safety）
from .attendance_compliance_agent import AttendanceComplianceAgent
from .attendance_recovery import AttendanceRecoveryAgent

# Sprint D1 / PR 批次 6 + Overflow：内容洞察 + 遗漏 Skill（冲 100% 覆盖）
from .audit_trail import AuditTrailAgent
from .banquet_growth import BanquetGrowthAgent

# 专项运营Agent (Phase 6)
from .billing_anomaly import BillingAnomalyAgent
from .cashier_audit import CashierAuditAgent
from .closing_agent import ClosingAgent

# Intel Agents (情报Agent)
from .competitor_watch import CompetitorWatchAgent

# HR Agent (人力Agent)
from .compliance_alert import ComplianceAlertAgent
from .content_generation import ContentGenerationAgent
from .cost_diagnosis import CostDiagnosisAgent

# Sprint D4a：成本根因 Skill（Sonnet 4.7 + Prompt Cache）
from .cost_root_cause import CostRootCauseAgent
from .discount_guard import DiscountGuardAgent
from .dormant_recall import DormantRecallAgent

# Sprint D1 / PR 批次 4：库存原料（margin + safety，或豁免）
from .enterprise_activation import EnterpriseActivationAgent
from .finance_audit import FinanceAuditAgent

# Sprint D1 / PR G 批次 1：接入 ConstraintContext
from .growth_attribution import GrowthAttributionAgent
from .growth_coach import GrowthCoachAgent
from .high_value_member import HighValueMemberAgent
from .ingredient_radar import IngredientRadarAgent
from .intel_reporter import IntelReporterAgent
from .inventory_alert import InventoryAlertAgent
from .kitchen_overtime import KitchenOvertimeAgent
from .member_insight import MemberInsightAgent
from .menu_advisor import MenuAdvisorAgent

# Growth Agents (增长Agent)
from .new_customer_convert import NewCustomerConvertAgent
from .new_product_scout import NewProductScoutAgent
from .off_peak_traffic import OffPeakTrafficAgent

# 千人千面个性化Agent
from .personalization_agent import PersonalizationAgent
from .pilot_recommender import PilotRecommenderAgent

# Sprint D1 / PR 批次 3：定价营销（margin）
from .points_advisor import PointsAdvisorAgent
from .private_ops import PrivateOpsAgent
from .queue_seating import QueueSeatingAgent
from .referral_growth import ReferralGrowthAgent
from .review_insight import ReviewInsightAgent
from .review_summary import ReviewSummaryAgent
from .salary_advisor import SalaryAdvisorAgent
from .seasonal_campaign import SeasonalCampaignAgent
from .serve_dispatch import ServeDispatchAgent
from .smart_customer_service import SmartCustomerServiceAgent
from .smart_menu import SmartMenuAgent
from .smart_service import SmartServiceAgent
from .stockout_alert import StockoutAlertAgent
from .store_inspect import StoreInspectAgent

# Sprint D1 / PR H 批次 2：出餐体验（experience）
from .table_dispatch import TableDispatchAgent
from .trend_discovery import TrendDiscoveryAgent

# Sprint D1 / PR 批次 5：合规运营（HR 类豁免 + 排班 margin）
from .turnover_risk import TurnoverRiskAgent

# 语音点菜 + AI服务员
from .voice_order import VoiceOrderAgent
from .workforce_planner import WorkforcePlannerAgent

ALL_SKILL_AGENTS = [
    # 原有9个核心Agent
    DiscountGuardAgent,
    SmartMenuAgent,
    ServeDispatchAgent,
    MemberInsightAgent,
    InventoryAlertAgent,
    FinanceAuditAgent,
    StoreInspectAgent,
    SmartServiceAgent,
    PrivateOpsAgent,
    # 增长Agent (8个)
    NewCustomerConvertAgent,
    DormantRecallAgent,
    BanquetGrowthAgent,
    SeasonalCampaignAgent,
    ReferralGrowthAgent,
    HighValueMemberAgent,
    OffPeakTrafficAgent,
    ContentGenerationAgent,
    # 情报Agent (8个)
    CompetitorWatchAgent,
    ReviewInsightAgent,
    TrendDiscoveryAgent,
    NewProductScoutAgent,
    IngredientRadarAgent,
    MenuAdvisorAgent,
    PilotRecommenderAgent,
    IntelReporterAgent,
    # 语音点菜 + AI服务员
    VoiceOrderAgent,
    AIWaiterAgent,
    # HR Agent (人力Agent)
    ComplianceAlertAgent,
    SalaryAdvisorAgent,
    # 千人千面Agent
    PersonalizationAgent,
    # 专项运营Agent (Phase 6)
    QueueSeatingAgent,
    KitchenOvertimeAgent,
    BillingAnomalyAgent,
    ClosingAgent,
    # AI营销编排 Agent (v207)
    AiMarketingOrchestratorAgent,
    # 成本核算Agent (P1)
    CostDiagnosisAgent,
    # Sprint D1 / PR G 批次 1
    GrowthAttributionAgent,
    StockoutAlertAgent,
    # Sprint D1 / PR H 批次 2（serve_dispatch / ai_waiter / voice_order /
    # smart_service / queue_seating / kitchen_overtime 已在上方注册；
    # 本行新增 table_dispatch）
    TableDispatchAgent,
    # Sprint D1 / PR 批次 3：定价营销（smart_menu / menu_advisor /
    # seasonal_campaign / personalization / new_customer_convert /
    # referral_growth 已在上方注册；本行新增 points_advisor）
    PointsAdvisorAgent,
    # Sprint D1 / PR 批次 4：库存原料（inventory_alert / new_product_scout /
    # trend_discovery / pilot_recommender / banquet_growth / private_ops
    # 已在上方注册；本行新增 enterprise_activation）
    EnterpriseActivationAgent,
    # Sprint D1 / PR 批次 5：合规运营（compliance_alert / store_inspect /
    # off_peak_traffic 已在上方注册；本行新增 4 个 HR/运营 Agent）
    AttendanceComplianceAgent,
    AttendanceRecoveryAgent,
    TurnoverRiskAgent,
    WorkforcePlannerAgent,
    # Sprint D1 / PR 批次 6 + Overflow：冲 100% 覆盖
    # （review_insight / intel_reporter / salary_advisor 已在上方注册；
    #  本行新增 5 个：review_summary / audit_trail / growth_coach /
    #  smart_customer_service / cashier_audit）
    ReviewSummaryAgent,
    AuditTrailAgent,
    GrowthCoachAgent,
    SmartCustomerServiceAgent,
    CashierAuditAgent,
    # Sprint D4a：成本根因（Sonnet 4.7 + Prompt Cache）
    CostRootCauseAgent,
]


# ──────────────────────────────────────────────────────────────────────
# Sprint D1 / PR G：SKILL_REGISTRY（agent_id → Skill class）
#
# 供 CI 门禁 test_constraint_coverage.py 遍历 Skills，逐一验证 constraint_scope
# 声明完备性。批次推进时在 ALL_SKILL_AGENTS 追加条目即可自动进入注册表。
# ──────────────────────────────────────────────────────────────────────

SKILL_REGISTRY: dict[str, type] = {}
for _cls in ALL_SKILL_AGENTS:
    _agent_id = getattr(_cls, "agent_id", None)
    if not _agent_id or _agent_id == "base":
        # base 或未设 agent_id 的骨架 Skill 不入注册表
        continue
    if _agent_id in SKILL_REGISTRY:
        raise RuntimeError(
            f"SKILL_REGISTRY agent_id 冲突: {_agent_id} 同时被 "
            f"{SKILL_REGISTRY[_agent_id].__name__} 和 {_cls.__name__} 声明"
        )
    SKILL_REGISTRY[_agent_id] = _cls
