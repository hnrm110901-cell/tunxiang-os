"""
屯象OS Ontology 类型定义 — 对标 Palantir Foundry Ontology

Palantir 映射:
  Object Type → Pydantic BaseModel (6大实体 DTO)
  Properties  → Model fields
  Links       → Foreign key references + relationship descriptors
  Constraints → 三条硬约束 (毛利底线/食安合规/客户体验)

与 shared/ontology/src/entities.py 的关系:
  src/entities.py  → SQLAlchemy ORM 模型 (数据库层)
  core/types.py    → Pydantic V2 DTO 模型  (Ontology 服务层/API 层)
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─────────────────────────────────────────────
# Enums (Ontology 层专用，与 src/enums.py 互补)
# ─────────────────────────────────────────────


class RFMTier(str, enum.Enum):
    """RFM 客户分层"""

    champion = "champion"
    loyal = "loyal"
    potential = "potential"
    new = "new"
    at_risk = "at_risk"
    dormant = "dormant"
    lost = "lost"


class LifecycleStage(str, enum.Enum):
    """客户生命周期阶段"""

    prospect = "prospect"
    first_visit = "first_visit"
    returning = "returning"
    regular = "regular"
    vip = "vip"
    churning = "churning"
    lost = "lost"


class DishQuadrant(str, enum.Enum):
    """菜品四象限分类 (BCG 矩阵)"""

    star = "star"  # 高销量 + 高毛利
    cash_cow = "cash_cow"  # 高销量 + 低毛利
    puzzle = "puzzle"  # 低销量 + 高毛利
    dog = "dog"  # 低销量 + 低毛利


class OrderChannel(str, enum.Enum):
    """订单渠道"""

    pos = "pos"
    wechat_mini = "wechat_mini"
    douyin_mini = "douyin_mini"
    meituan = "meituan"
    eleme = "eleme"
    dine_in = "dine_in"
    takeaway = "takeaway"


class FulfillmentStatus(str, enum.Enum):
    """出餐履约状态"""

    pending = "pending"
    accepted = "accepted"
    preparing = "preparing"
    ready = "ready"
    served = "served"
    cancelled = "cancelled"


class ConstraintType(str, enum.Enum):
    """三条硬约束类型"""

    margin_floor = "margin_floor"  # 毛利底线
    food_safety = "food_safety"  # 食安合规
    customer_experience = "customer_experience"  # 客户体验


# ─────────────────────────────────────────────
# Base Entity
# ─────────────────────────────────────────────


class TenantEntity(BaseModel):
    """所有 Ontology 对象的基类 — 强制 tenant_id + RLS 兼容

    对应 SQL 底层基类:
        tenant_id    UUID NOT NULL
        created_at   TIMESTAMPTZ DEFAULT NOW()
        updated_at   TIMESTAMPTZ DEFAULT NOW()
        is_deleted   BOOLEAN DEFAULT FALSE
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    tenant_id: uuid.UUID
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    is_deleted: bool = False


# ─────────────────────────────────────────────
# Hard Constraint Result
# ─────────────────────────────────────────────


class HardConstraintResult(BaseModel):
    """三条硬约束校验结果"""

    constraint_type: ConstraintType
    passed: bool
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.constraint_type.value}: {self.message}"


# ─────────────────────────────────────────────
# 1. Customer — 顾客 (Golden ID, 全渠道画像)
# ─────────────────────────────────────────────


class CustomerObject(TenantEntity):
    """CDP 统一消费者身份 — Golden ID

    Properties:
      - 基础身份: phone, name, gender, birth
      - 微信绑定: openid, unionid, nickname
      - RFM 分层: rfm_tier, r/f/m scores
      - 生命周期: lifecycle_stage
      - 渠道列表: channels
      - 风险评分: risk_score
    """

    primary_phone: str = Field(..., max_length=20)
    display_name: str | None = None
    gender: str | None = None
    birth_date: date | None = None

    # 微信身份
    wechat_openid: str | None = None
    wechat_unionid: str | None = None
    wechat_nickname: str | None = None

    # RFM 分层
    rfm_tier: RFMTier = RFMTier.new
    r_score: int = Field(default=0, ge=0, le=5)
    f_score: int = Field(default=0, ge=0, le=5)
    m_score: int = Field(default=0, ge=0, le=5)

    # 生命周期
    lifecycle_stage: LifecycleStage = LifecycleStage.prospect

    # 消费统计
    total_order_count: int = 0
    total_order_amount_fen: int = 0
    first_order_at: datetime | None = None
    last_order_at: datetime | None = None

    # 渠道 & 标签
    channels: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    dietary_restrictions: list[str] = Field(default_factory=list)

    # 风险评分
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("total_order_amount_fen")
    @classmethod
    def validate_amount_fen(cls, v: int) -> int:
        if v < 0:
            raise ValueError("total_order_amount_fen cannot be negative")
        return v


# ─────────────────────────────────────────────
# 2. Dish — 菜品 (BOM, 价格, 毛利, 四象限)
# ─────────────────────────────────────────────


class BOMEntry(BaseModel):
    """BOM 配方条目"""

    ingredient_id: uuid.UUID
    ingredient_name: str
    quantity: float = Field(..., gt=0)
    unit: str
    cost_per_serving_fen: int = 0
    is_required: bool = True
    is_substitutable: bool = False
    substitute_ids: list[uuid.UUID] = Field(default_factory=list)


class DishObject(TenantEntity):
    """菜品主档 — BOM 配方, 各渠道价格, 毛利模型, 四象限分类

    Properties:
      - 基本: name, code, category, description
      - 价格: price_fen, cost_fen, margin
      - BOM: bom_entries
      - 分类: quadrant, tags
      - 状态: is_available, is_sold_out
    """

    store_id: uuid.UUID | None = None
    dish_name: str = Field(..., max_length=100)
    dish_code: str = Field(..., max_length=50)
    category_id: uuid.UUID | None = None
    description: str | None = None
    image_url: str | None = None

    # 价格 (分)
    price_fen: int = Field(..., ge=0)
    original_price_fen: int | None = None
    cost_fen: int | None = None
    profit_margin: float | None = Field(default=None, ge=0, le=100)

    # 属性
    unit: str = "份"
    preparation_time_min: int | None = Field(default=None, ge=0)
    kitchen_station: str | None = None
    spicy_level: int = Field(default=0, ge=0, le=5)

    # BOM
    bom_entries: list[BOMEntry] = Field(default_factory=list)

    # 四象限
    quadrant: DishQuadrant | None = None

    # 渠道价格 (channel_id → price_fen)
    channel_prices: dict[str, int] = Field(default_factory=dict)

    # 标签
    tags: list[str] = Field(default_factory=list)
    allergens: list[str] = Field(default_factory=list)

    # 状态
    is_available: bool = True
    is_sold_out: bool = False
    is_recommended: bool = False

    # 统计
    total_sales: int = 0
    total_revenue_fen: int = 0

    @field_validator("price_fen")
    @classmethod
    def validate_price(cls, v: int) -> int:
        if v < 0:
            raise ValueError("price_fen cannot be negative")
        return v


# ─────────────────────────────────────────────
# 3. Store — 门店 (桌台拓扑, 档口配置, 人效模型)
# ─────────────────────────────────────────────


class StoreObject(TenantEntity):
    """门店 — 桌台拓扑, 档口配置, 人效模型, 经营指标

    Properties:
      - 基本: name, code, address, brand_id
      - 类型: store_type, business_type
      - 物理: area, seats, floors
      - 经营目标: revenue_target, customer_target
      - 约束: serve_time_limit_min (客户体验硬约束)
    """

    store_name: str = Field(..., max_length=100)
    store_code: str = Field(..., max_length=20)
    brand_id: str | None = None
    region: str | None = None

    # 类型
    store_type: str = Field(
        default="physical",
        description="physical/virtual/central_kitchen/warehouse",
    )
    business_type: str | None = Field(
        default=None,
        description="fine_dining/fast_food/retail/catering/pro/standard/lite",
    )

    # 地址
    address: str | None = None
    city: str | None = None
    district: str | None = None
    phone: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    # 物理属性
    area_sqm: float | None = None
    seats: int | None = Field(default=None, ge=0)
    floors: int = 1

    # 经营目标
    monthly_revenue_target_fen: int | None = None
    daily_customer_target: int | None = None
    cost_ratio_target: float | None = None
    labor_cost_ratio_target: float | None = None

    # 硬约束 — 客户体验
    serve_time_limit_min: int = Field(
        default=30,
        ge=1,
        description="出餐时限(分钟) — 三条硬约束之客户体验",
    )

    # 毛利底线阈值
    margin_floor_pct: float = Field(
        default=30.0,
        ge=0,
        le=100,
        description="毛利底线(%) — 三条硬约束之毛利底线",
    )

    # 桌台拓扑
    table_topology: dict[str, Any] = Field(default_factory=dict)

    # 档口配置
    kitchen_stations: list[str] = Field(default_factory=list)

    # 餐段
    meal_periods: list[dict[str, str]] = Field(default_factory=list)

    is_active: bool = True


# ─────────────────────────────────────────────
# 4. Order — 订单 (全渠道统一)
# ─────────────────────────────────────────────


class OrderItemObject(BaseModel):
    """订单明细"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    dish_id: uuid.UUID | None = None
    item_name: str
    quantity: int = Field(..., ge=1)
    unit_price_fen: int = Field(..., ge=0)
    subtotal_fen: int = Field(..., ge=0)
    food_cost_fen: int | None = None
    gross_margin: float | None = None
    notes: str | None = None
    customizations: dict[str, Any] = Field(default_factory=dict)

    # 称重
    pricing_mode: str | None = Field(
        default=None,
        description="fixed/weight/market_price",
    )
    weight_value: float | None = None

    # 状态
    gift_flag: bool = False
    return_flag: bool = False
    return_reason: str | None = None
    fulfillment_status: FulfillmentStatus = FulfillmentStatus.pending
    kds_station: str | None = None


class OrderObject(TenantEntity):
    """订单 — 全渠道统一, 折扣明细, 核销记录, 出餐状态

    Properties:
      - 基本: order_no, store_id, customer_id
      - 类型: order_type, channel
      - 金额: total, discount, final (all in fen)
      - 状态: status, fulfillment_status
      - 时间: order_time, confirmed_at, completed_at, served_at
      - 约束跟踪: margin_alert_flag, gross_margin_before/after
    """

    order_no: str
    store_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    table_number: str | None = None
    waiter_id: str | None = None

    # 类型 & 渠道
    order_type: str = Field(
        default="dine_in",
        description="dine_in/takeaway/delivery/retail/catering/banquet",
    )
    channel: OrderChannel = OrderChannel.pos

    # 金额 (分)
    total_amount_fen: int = Field(..., ge=0)
    discount_amount_fen: int = 0
    final_amount_fen: int | None = None

    # 状态
    status: str = "pending"

    # 时间
    order_time: datetime = Field(default_factory=datetime.utcnow)
    confirmed_at: datetime | None = None
    completed_at: datetime | None = None
    served_at: datetime | None = None

    # 出餐
    serve_duration_min: int | None = None
    guest_count: int | None = Field(default=None, ge=1)

    # 明细
    items: list[OrderItemObject] = Field(default_factory=list)

    # 约束跟踪
    discount_type: str | None = None
    margin_alert_flag: bool = False
    gross_margin_before: float | None = None
    gross_margin_after: float | None = None
    abnormal_flag: bool = False
    abnormal_type: str | None = None

    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("total_amount_fen", "discount_amount_fen")
    @classmethod
    def validate_fen_fields(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Amount in fen cannot be negative")
        return v


# ─────────────────────────────────────────────
# 5. Ingredient — 食材 (库存, 效期, 批次)
# ─────────────────────────────────────────────


class IngredientObject(TenantEntity):
    """食材 — 库存量, 效期, 采购价, 批次, 供应商

    Properties:
      - 基本: name, category, unit
      - 库存: current_quantity, min/max_quantity
      - 价格: unit_price_fen
      - 效期: expiry_date, shelf_life_days (食安合规硬约束)
      - 供应商: supplier_name, supplier_contact
      - 存储: storage_type, storage_temp
      - 批次: batch_no
    """

    store_id: uuid.UUID
    ingredient_name: str = Field(..., max_length=100)
    category: str | None = None
    unit: str = Field(..., max_length=20)

    # 库存
    current_quantity: float = 0.0
    min_quantity: float = 0.0
    max_quantity: float | None = None

    # 价格
    unit_price_fen: int | None = None

    # 效期 — 食安合规硬约束
    expiry_date: date | None = None
    shelf_life_days: int | None = Field(default=None, ge=0)
    production_date: date | None = None

    # 存储
    storage_type: str = "ambient"  # frozen/chilled/ambient/live
    storage_temp_min: float | None = None
    storage_temp_max: float | None = None

    # 批次 & 供应商
    batch_no: str | None = None
    supplier_name: str | None = None
    supplier_contact: str | None = None

    # 溯源
    is_traceable: bool = False
    allergen_tags: list[str] = Field(default_factory=list)

    # 状态
    status: str = "normal"  # normal/low/critical/out_of_stock

    def is_expired(self, reference_date: date | None = None) -> bool:
        """检查是否过期 — 食安合规硬约束核心判定"""
        if self.expiry_date is None:
            return False
        check_date = reference_date or date.today()
        return self.expiry_date < check_date

    def days_until_expiry(self, reference_date: date | None = None) -> int | None:
        """距过期天数，负数表示已过期"""
        if self.expiry_date is None:
            return None
        check_date = reference_date or date.today()
        return (self.expiry_date - check_date).days


# ─────────────────────────────────────────────
# 6. Employee — 员工 (角色, 技能, 排班, 效率)
# ─────────────────────────────────────────────


class EmployeeObject(TenantEntity):
    """员工 — 角色, 技能, 排班, 业绩提成, 效率指标

    Properties:
      - 基本: name, phone, email, role
      - 技能: skills
      - 雇佣: hire_date, employment_status, employment_type
      - 证照: health_cert_expiry (食安合规关联)
      - 排班: store_id, org_id
      - 效率: performance_score
    """

    store_id: uuid.UUID
    emp_name: str = Field(..., max_length=100)
    phone: str | None = None
    email: str | None = None
    role: str = Field(
        ...,
        description="waiter/chef/cashier/manager",
    )
    skills: list[str] = Field(default_factory=list)

    # 雇佣
    hire_date: date | None = None
    employment_status: str = "regular"
    employment_type: str = "regular"
    is_active: bool = True

    # IM
    wechat_userid: str | None = None
    dingtalk_userid: str | None = None

    # 证照 — 食安合规关联
    health_cert_expiry: date | None = None

    # 组织
    org_id: uuid.UUID | None = None

    # 效率
    performance_score: str | None = None
    training_completed: list[str] = Field(default_factory=list)

    def is_health_cert_valid(self, reference_date: date | None = None) -> bool:
        """健康证是否有效 — 食安合规关联检查"""
        if self.health_cert_expiry is None:
            return False
        check_date = reference_date or date.today()
        return self.health_cert_expiry >= check_date
