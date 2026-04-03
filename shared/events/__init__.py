"""shared.events — 屯象OS 全域业务事件总线（Redis Streams）

导出所有域的事件类型、数据类和发布器。
"""
# 会员域（保持向后兼容）
from .member_events import MemberEvent, MemberEventType
from .event_publisher import MemberEventPublisher
from .event_consumer import MemberEventConsumer

# 交易域
from .trade_events import TradeEvent, TradeEventType

# 供应链域
from .supply_events import SupplyEvent, SupplyEventType

# 财务域
from .finance_events import FinanceEvent, FinanceEventType

# 组织人事域
from .org_events import OrgEvent, OrgEventType

# 商品菜单域
from .menu_events import MenuEvent, MenuEventType

# 运营日清域
from .ops_events import OpsEvent, OpsEventType

# 通用发布器（推荐所有新代码使用）
from .universal_publisher import UniversalPublisher

__all__ = [
    # 会员
    "MemberEvent", "MemberEventType", "MemberEventPublisher", "MemberEventConsumer",
    # 交易
    "TradeEvent", "TradeEventType",
    # 供应链
    "SupplyEvent", "SupplyEventType",
    # 财务
    "FinanceEvent", "FinanceEventType",
    # 组织
    "OrgEvent", "OrgEventType",
    # 菜单
    "MenuEvent", "MenuEventType",
    # 运营
    "OpsEvent", "OpsEventType",
    # 通用发布器
    "UniversalPublisher",
]
