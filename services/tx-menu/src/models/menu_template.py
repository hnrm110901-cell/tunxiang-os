"""菜单模板 ORM 模型

表：
  menu_templates         — 菜单模板主表
  store_menu_publishes   — 门店发布记录
  channel_prices         — 渠道差异价
  seasonal_menus         — 季节菜单
  room_menus             — 包间菜单
"""

import uuid

from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

# ─── 模板状态常量 ───
TEMPLATE_STATUS_DRAFT = "draft"
TEMPLATE_STATUS_PUBLISHED = "published"
VALID_TEMPLATE_STATUSES = {TEMPLATE_STATUS_DRAFT, TEMPLATE_STATUS_PUBLISHED}

# ─── 渠道常量 ───
VALID_CHANNELS = {"dine_in", "takeout", "delivery", "miniapp"}

# ─── 季节常量 ───
VALID_SEASONS = {"spring", "summer", "autumn", "winter"}

# ─── 包厢类型常量 ───
VALID_ROOM_TYPES = {"standard", "vip", "luxury", "banquet"}


class MenuTemplate(TenantBase):
    """菜单模板 — 可发布到多个门店的菜品组合"""

    __tablename__ = "menu_templates"

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="模板名称",
    )
    dishes: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment='菜品列表 [{"dish_id": str, "sort_order": int, ...}]',
    )
    rules: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="模板规则（如 min_dishes / type=banquet 等）",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=TEMPLATE_STATUS_DRAFT,
        comment="状态: draft / published",
    )
    published_stores: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="已发布的门店 ID 列表",
    )
    package_price_fen: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="宴席套餐总价（分），仅 banquet 类型使用",
    )
    guest_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="宴席适用人数，仅 banquet 类型使用",
    )
    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="模板/套餐描述",
    )


class StoreMenuPublish(TenantBase):
    """门店菜单发布记录 — 每个门店一条活跃记录"""

    __tablename__ = "store_menu_publishes"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="门店 ID",
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="来源模板 ID",
    )
    template_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="模板名称快照",
    )
    dishes: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="菜品列表快照",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        comment="发布状态: active / inactive",
    )


class ChannelPrice(TenantBase):
    """渠道差异价 — 某菜品在某渠道的特殊售价"""

    __tablename__ = "channel_prices"

    dish_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="菜品 ID",
    )
    channel: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="渠道: dine_in / takeout / delivery / miniapp",
    )
    price_fen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="渠道售价（分）",
    )


class SeasonalMenu(TenantBase):
    """季节菜单 — 门店 + 季节维度"""

    __tablename__ = "seasonal_menus"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="门店 ID",
    )
    season: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="季节: spring / summer / autumn / winter",
    )
    dishes: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="季节菜品列表",
    )
    dish_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="菜品数量",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        comment="状态",
    )


class RoomMenu(TenantBase):
    """包间菜单 — 门店 + 包间类型维度"""

    __tablename__ = "room_menus"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="门店 ID",
    )
    room_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="包间类型: standard / vip / luxury / banquet",
    )
    dishes: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="包间菜品列表",
    )
    dish_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="菜品数量",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        comment="状态",
    )
