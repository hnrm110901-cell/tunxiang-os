from .ai_waiter import AIWaiterAgent
from .banquet_growth import BanquetGrowthAgent

# Intel Agents (情报Agent)
from .competitor_watch import CompetitorWatchAgent

# HR Agent (人力Agent)
from .compliance_alert import ComplianceAlertAgent
from .content_generation import ContentGenerationAgent
from .discount_guard import DiscountGuardAgent
from .dormant_recall import DormantRecallAgent
from .finance_audit import FinanceAuditAgent
from .high_value_member import HighValueMemberAgent
from .ingredient_radar import IngredientRadarAgent
from .intel_reporter import IntelReporterAgent
from .inventory_alert import InventoryAlertAgent
from .member_insight import MemberInsightAgent
from .menu_advisor import MenuAdvisorAgent

# Growth Agents (增长Agent)
from .new_customer_convert import NewCustomerConvertAgent
from .new_product_scout import NewProductScoutAgent
from .off_peak_traffic import OffPeakTrafficAgent
from .pilot_recommender import PilotRecommenderAgent
from .private_ops import PrivateOpsAgent
from .referral_growth import ReferralGrowthAgent
from .review_insight import ReviewInsightAgent
from .salary_advisor import SalaryAdvisorAgent
from .seasonal_campaign import SeasonalCampaignAgent
from .serve_dispatch import ServeDispatchAgent
from .smart_menu import SmartMenuAgent
from .smart_service import SmartServiceAgent
from .store_inspect import StoreInspectAgent
from .trend_discovery import TrendDiscoveryAgent

# 语音点菜 + AI服务员
from .voice_order import VoiceOrderAgent

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
]
