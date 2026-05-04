"""屯象OS 事件投影器集合

每个投影器消费特定事件域，维护对应的物化视图（mv_*）。

投影器列表（对应七条因果链 + 新模块）：
  DiscountHealthProjector    → mv_discount_health（因果链①）
  ChannelMarginProjector     → mv_channel_margin（因果链②）
  InventoryBomProjector      → mv_inventory_bom（因果链③）
  StorePnlProjector          → mv_store_pnl（因果链④）
  MemberClvProjector         → mv_member_clv（因果链⑤）
  DailySettlementProjector   → mv_daily_settlement（因果链⑦）
  SafetyComplianceProjector  → mv_safety_compliance（食安合规）
  EnergyEfficiencyProjector  → mv_energy_efficiency（能耗管理）
  PublicOpinionProjector     → mv_public_opinion（舆情监控）
  TableTurnoverProjector     → mv_table_turnover（v385 翻台率）
  DishProfitabilityProjector → mv_dish_profitability（v385 菜品盈利）
  EmployeeEfficiencyProjector → mv_employee_efficiency（v385 人效）
  CustomerLtvProjector       → mv_customer_ltv（v385 客户LTV）
"""

from .channel_margin import ChannelMarginProjector
from .customer_ltv import CustomerLtvProjector
from .daily_settlement import DailySettlementProjector
from .dish_profitability import DishProfitabilityProjector
from .discount_health import DiscountHealthProjector
from .employee_efficiency import EmployeeEfficiencyProjector
from .energy_efficiency import EnergyEfficiencyProjector
from .inventory_bom import InventoryBomProjector
from .member_clv import MemberClvProjector
from .public_opinion import PublicOpinionProjector
from .safety_compliance import SafetyComplianceProjector
from .store_pnl import StorePnlProjector
from .table_turnover import TableTurnoverProjector

ALL_PROJECTORS = [
    DiscountHealthProjector,
    ChannelMarginProjector,
    InventoryBomProjector,
    MemberClvProjector,
    StorePnlProjector,
    DailySettlementProjector,
    SafetyComplianceProjector,
    EnergyEfficiencyProjector,
    PublicOpinionProjector,
    TableTurnoverProjector,
    DishProfitabilityProjector,
    EmployeeEfficiencyProjector,
    CustomerLtvProjector,
]

__all__ = [
    "ChannelMarginProjector",
    "CustomerLtvProjector",
    "DailySettlementProjector",
    "DishProfitabilityProjector",
    "DiscountHealthProjector",
    "EmployeeEfficiencyProjector",
    "EnergyEfficiencyProjector",
    "InventoryBomProjector",
    "MemberClvProjector",
    "PublicOpinionProjector",
    "SafetyComplianceProjector",
    "StorePnlProjector",
    "TableTurnoverProjector",
    "ALL_PROJECTORS",
]
