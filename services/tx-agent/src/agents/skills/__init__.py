from .discount_guard import DiscountGuardAgent
from .smart_menu import SmartMenuAgent
from .serve_dispatch import ServeDispatchAgent
from .member_insight import MemberInsightAgent
from .inventory_alert import InventoryAlertAgent
from .finance_audit import FinanceAuditAgent
from .store_inspect import StoreInspectAgent
from .smart_service import SmartServiceAgent
from .private_ops import PrivateOpsAgent

# Growth Agents (增长Agent)
from .new_customer_convert import NewCustomerConvertAgent
from .dormant_recall import DormantRecallAgent
from .banquet_growth import BanquetGrowthAgent
from .seasonal_campaign import SeasonalCampaignAgent
from .referral_growth import ReferralGrowthAgent
from .high_value_member import HighValueMemberAgent
from .off_peak_traffic import OffPeakTrafficAgent
from .content_generation import ContentGenerationAgent

# Intel Agents (情报Agent)
from .competitor_watch import CompetitorWatchAgent
from .review_insight import ReviewInsightAgent
from .trend_discovery import TrendDiscoveryAgent
from .new_product_scout import NewProductScoutAgent
from .ingredient_radar import IngredientRadarAgent
from .menu_advisor import MenuAdvisorAgent
from .pilot_recommender import PilotRecommenderAgent
from .intel_reporter import IntelReporterAgent

# 语音点菜 + AI服务员
from .voice_order import VoiceOrderAgent
from .ai_waiter import AIWaiterAgent

# HR Agent (人力Agent)
from .compliance_alert import ComplianceAlertAgent
from .salary_advisor import SalaryAdvisorAgent

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
