from .discount_guard import DiscountGuardAgent
from .smart_menu import SmartMenuAgent
from .serve_dispatch import ServeDispatchAgent
from .member_insight import MemberInsightAgent
from .inventory_alert import InventoryAlertAgent
from .finance_audit import FinanceAuditAgent
from .store_inspect import StoreInspectAgent
from .smart_service import SmartServiceAgent
from .private_ops import PrivateOpsAgent

ALL_SKILL_AGENTS = [
    DiscountGuardAgent,
    SmartMenuAgent,
    ServeDispatchAgent,
    MemberInsightAgent,
    InventoryAlertAgent,
    FinanceAuditAgent,
    StoreInspectAgent,
    SmartServiceAgent,
    PrivateOpsAgent,
]
