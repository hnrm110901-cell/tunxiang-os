"""商品菜单域事件类型定义

菜单域所有跨服务事件均通过 MenuEvent 传递，事件类型由 MenuEventType 枚举定义。
Redis Stream key: menu_events
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class MenuEventType(str, Enum):
    """商品菜单域事件类型

    命名规范：menu.{entity}.{action}
    全部小写，单词间用点分隔。
    """

    # ── 菜品类 ─────────────────────────────────────────────────────
    DISH_PUBLISHED = "menu.dish.published"  # 菜品发布
    DISH_SOLDOUT = "menu.dish.soldout"  # 菜品售罄
    DISH_PRICE_CHANGED = "menu.dish.price_changed"  # 菜品改价
    DISH_DEACTIVATED = "menu.dish.deactivated"  # 菜品下架

    # ── 品类类 ─────────────────────────────────────────────────────
    CATEGORY_REORDERED = "menu.category.reordered"  # 品类排序调整

    # ── 发布计划类 ─────────────────────────────────────────────────
    PUBLISH_PLAN_APPROVED = "menu.publish_plan.approved"  # 发布计划审批通过


@dataclass
class MenuEvent:
    """商品菜单域事件数据类

    Attributes:
        event_type:     事件类型（MenuEventType 枚举值）
        tenant_id:      租户 UUID（RLS 隔离）
        store_id:       门店 UUID（None 表示品牌级变更）
        dish_id:        菜品 UUID（部分事件可为 None）
        event_data:     事件具体数据（业务字段，按事件类型不同）
        event_id:       唯一事件 ID（默认自动生成 uuid4）
        occurred_at:    事件发生时刻（UTC，默认当前时间）
        source_service: 来源服务名
    """

    event_type: MenuEventType
    tenant_id: UUID
    store_id: Optional[UUID]
    dish_id: Optional[UUID]
    event_data: dict
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_service: str = "tx-menu"
