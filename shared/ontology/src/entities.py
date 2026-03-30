"""六大核心实体 — Ontology L1 层完整定义

从 tunxiang V2.x 模型提取，统一添加 tenant_id + RLS 支持。
金额统一存分（fen），展示时 /100 转元。
"""
import uuid

from sqlalchemy import (
    Boolean, Date, DateTime, Float, Integer, Numeric, String, Text,
    ForeignKey, Index, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import TenantBase
from .enums import (
    OrderStatus, StoreStatus, InventoryStatus, TransactionType,
    EmploymentStatus, EmploymentType, StorageType, RFMLevel,
)


# ─────────────────────────────────────────────
# 1. Customer — 顾客（Golden ID 全渠道画像）
# ─────────────────────────────────────────────

class Customer(TenantBase):
    """CDP 统一消费者身份 — Golden ID"""
    __tablename__ = "customers"

    primary_phone: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(100))
    gender: Mapped[str | None] = mapped_column(String(10))
    birth_date: Mapped[str | None] = mapped_column(Date)
    anniversary: Mapped[str | None] = mapped_column(Date)

    # 微信身份
    wechat_openid: Mapped[str | None] = mapped_column(String(128), index=True)
    wechat_unionid: Mapped[str | None] = mapped_column(String(128), index=True)
    wechat_nickname: Mapped[str | None] = mapped_column(String(100))
    wechat_avatar_url: Mapped[str | None] = mapped_column(String(500))

    # 消费统计
    total_order_count: Mapped[int] = mapped_column(Integer, default=0)
    total_order_amount_fen: Mapped[int] = mapped_column(Integer, default=0, comment="累计消费(分)")
    total_reservation_count: Mapped[int] = mapped_column(Integer, default=0)
    first_order_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    last_order_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), index=True)
    first_store_id: Mapped[str | None] = mapped_column(String(50))

    # RFM
    rfm_recency_days: Mapped[int | None] = mapped_column(Integer)
    rfm_frequency: Mapped[int | None] = mapped_column(Integer)
    rfm_monetary_fen: Mapped[int | None] = mapped_column(Integer, comment="M值(分)")
    rfm_level: Mapped[str | None] = mapped_column(String(5), default="S3")

    # 标签与偏好
    tags: Mapped[list | None] = mapped_column(JSON, default=list)
    dietary_restrictions: Mapped[list | None] = mapped_column(JSON, default=list)

    # 合并追踪
    is_merged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    merged_into: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)

    # RFM 1-5 标准化评分（老项目 private_domain_members 迁入）
    r_score: Mapped[int | None] = mapped_column(Integer, comment="R评分1-5")
    f_score: Mapped[int | None] = mapped_column(Integer, comment="F评分1-5")
    m_score: Mapped[int | None] = mapped_column(Integer, comment="M评分1-5")
    rfm_updated_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), comment="RFM最近更新时间")

    # 门店象限与流失风险（老项目 private_domain_members 迁入）
    store_quadrant: Mapped[str | None] = mapped_column(String(20), comment="benchmark/defensive/potential/breakthrough")
    risk_score: Mapped[float | None] = mapped_column(Float, default=0.0, comment="流失风险分0-1")

    # 来源
    source: Mapped[str | None] = mapped_column(String(50), comment="pos/wechat/manual/meituan")
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0)
    extra: Mapped[dict | None] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("idx_customer_phone_active", "primary_phone", "is_merged"),
        {"comment": "CDP统一消费者身份"},
    )


# ─────────────────────────────────────────────
# 2. Store — 门店
# ─────────────────────────────────────────────

class Store(TenantBase):
    """门店 — 桌台拓扑, 档口配置, 人效模型, 经营指标

    修正#7: 支持虚拟门店(中央厨房/电商仓库)
    - store_type: physical/virtual/central_kitchen/warehouse
    - has_physical_seats: False for virtual stores
    - address/seats: optional for virtual stores
    """
    __tablename__ = "stores"

    store_name: Mapped[str] = mapped_column(String(100), nullable=False)
    store_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(100), comment="门店邮箱")
    manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), comment="店长ID")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否营业中")

    # 修正#7: 门店类型 — 支持虚拟门店
    store_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="physical",
        comment="physical/virtual/central_kitchen/warehouse",
    )
    has_physical_seats: Mapped[bool] = mapped_column(
        Boolean, default=True,
        comment="True for restaurants, False for warehouses/virtual",
    )

    # 地址现在可选 — 虚拟门店/中央厨房可能无地址
    address: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(50))
    district: Mapped[str | None] = mapped_column(String(50))
    phone: Mapped[str | None] = mapped_column(String(20))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    brand_id: Mapped[str | None] = mapped_column(String(50), index=True)
    region: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=StoreStatus.active.value)

    # 门店物理属性 — seats 可选(虚拟门店无座位)
    area: Mapped[float | None] = mapped_column(Float, comment="面积(平方米)")
    seats: Mapped[int | None] = mapped_column(Integer, comment="座位数, None for virtual stores")
    floors: Mapped[int] = mapped_column(Integer, default=1)
    opening_date: Mapped[str | None] = mapped_column(String(20))
    business_hours: Mapped[dict | None] = mapped_column(JSON)
    config: Mapped[dict | None] = mapped_column(JSON, default=dict)

    # 经营目标
    monthly_revenue_target_fen: Mapped[int | None] = mapped_column(Integer, comment="月营收目标(分)")
    daily_customer_target: Mapped[int | None] = mapped_column(Integer)
    cost_ratio_target: Mapped[float | None] = mapped_column(Float)
    labor_cost_ratio_target: Mapped[float | None] = mapped_column(Float)

    # 蓝图扩展字段
    turnover_rate_target: Mapped[float | None] = mapped_column(Float, comment="翻台率目标")
    serve_time_limit_min: Mapped[int | None] = mapped_column(Integer, default=30, comment="出餐时限(分钟)")
    waste_rate_target: Mapped[float | None] = mapped_column(Float, comment="损耗率目标(%)")
    rectification_close_rate: Mapped[float | None] = mapped_column(Float, comment="整改关闭率")
    meal_periods: Mapped[dict | None] = mapped_column(JSON, comment="餐段配置[{name,start,end}]")
    business_type: Mapped[str | None] = mapped_column(String(30), comment="fine_dining/fast_food/retail/catering/pro/standard/lite")

    # 品智借鉴：门店标签多维度分类
    store_category: Mapped[str | None] = mapped_column(String(50), comment="门店类别：商场店/街边店/社区店")
    store_tags: Mapped[dict | None] = mapped_column(JSON, default=list, comment="门店标签[{category,tags}]，最多3维度")
    operation_mode: Mapped[str | None] = mapped_column(String(20), comment="经营模式：直营/加盟/联营")
    store_level: Mapped[str | None] = mapped_column(String(20), comment="门店等级：A/B/C/D")
    last_online_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), comment="最近在线日期")
    license_expiry: Mapped[str | None] = mapped_column(Date, comment="授权到期日期")

    # 品智借鉴：日结/班别配置
    settlement_mode: Mapped[str | None] = mapped_column(String(20), default="auto+manual", comment="日结方式：auto/manual/auto+manual")
    shift_type: Mapped[str | None] = mapped_column(String(20), default="no_shift", comment="班别：no_shift/two_shift/three_shift")

    # 灵活扩展
    store_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, default=dict, comment="灵活扩展字段")


# ─────────────────────────────────────────────
# 3. Dish — 菜品
# ─────────────────────────────────────────────

class DishCategory(TenantBase):
    """菜品分类（支持多级）"""
    __tablename__ = "dish_categories"

    store_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), index=True, comment="所属门店，NULL=集团通用分类")
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str | None] = mapped_column(String(50))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("dish_categories.id"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text, comment="分类描述")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    children = relationship("DishCategory", backref="parent", remote_side="DishCategory.id")


class Dish(TenantBase):
    """菜品主档 — BOM 配方, 各渠道价格, 毛利模型, 四象限分类"""
    __tablename__ = "dishes"

    store_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), index=True, comment="所属门店，NULL=集团通用菜品")
    dish_name: Mapped[str] = mapped_column(String(100), nullable=False)
    dish_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("dish_categories.id"))
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(500))

    # 价格（统一存分）
    price_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="售价(分)")
    original_price_fen: Mapped[int | None] = mapped_column(Integer, comment="原价(分)")
    cost_fen: Mapped[int | None] = mapped_column(Integer, comment="成本(分)")
    profit_margin: Mapped[float | None] = mapped_column(Numeric(5, 2), comment="毛利率(%)")

    # 属性
    unit: Mapped[str] = mapped_column(String(20), default="份")
    serving_size: Mapped[str | None] = mapped_column(String(50))
    spicy_level: Mapped[int] = mapped_column(Integer, default=0)
    preparation_time: Mapped[int | None] = mapped_column(Integer, comment="制作时间(分钟)")
    cooking_method: Mapped[str | None] = mapped_column(String(50))
    kitchen_station: Mapped[str | None] = mapped_column(String(50), comment="档口")
    production_dept_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), comment="出品部门ID")
    sell_start_date: Mapped[str | None] = mapped_column(Date, comment="售卖开始日期")
    sell_end_date: Mapped[str | None] = mapped_column(Date, comment="售卖结束日期")
    sell_time_ranges: Mapped[dict | None] = mapped_column(JSON, comment="售卖时段[{start,end}]")

    # 标签
    tags: Mapped[list | None] = mapped_column(ARRAY(String), comment="招牌/新品/特价/素食")
    allergens: Mapped[list | None] = mapped_column(ARRAY(String))
    dietary_info: Mapped[list | None] = mapped_column(ARRAY(String))

    # 营养
    calories: Mapped[int | None] = mapped_column(Integer)
    protein: Mapped[float | None] = mapped_column(Numeric(5, 2))
    fat: Mapped[float | None] = mapped_column(Numeric(5, 2))
    carbohydrate: Mapped[float | None] = mapped_column(Numeric(5, 2))

    # 状态
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    is_recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    is_seasonal: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # 季节性
    season: Mapped[str | None] = mapped_column(String(20), comment="季节：春/夏/秋/冬")

    # 库存关联（老项目 requires_inventory/low_stock_threshold 迁入）
    requires_inventory: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否需要库存管理")
    low_stock_threshold: Mapped[int | None] = mapped_column(Integer, comment="低库存预警阈值(份)")

    # 集团主档关联（老项目 dish_master_id 迁入）
    dish_master_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True, comment="集团菜品主档ID")

    # 统计
    total_sales: Mapped[int] = mapped_column(Integer, default=0)
    total_revenue_fen: Mapped[int] = mapped_column(Integer, default=0, comment="总营收(分)")
    rating: Mapped[float | None] = mapped_column(Numeric(3, 2))
    review_count: Mapped[int] = mapped_column(Integer, default=0)

    # 备注与扩展
    notes: Mapped[str | None] = mapped_column(Text, comment="菜品备注")
    dish_metadata: Mapped[dict | None] = mapped_column(JSON, default=dict, comment="扩展字段")

    # 关联
    category = relationship("DishCategory", lazy="joined")
    ingredients = relationship("DishIngredient", back_populates="dish", cascade="all, delete-orphan")


class DishIngredient(TenantBase):
    """菜品-食材关联（BOM 配方）"""
    __tablename__ = "dish_ingredients"

    dish_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("dishes.id"), nullable=False)
    ingredient_id: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    cost_per_serving_fen: Mapped[int | None] = mapped_column(Integer, comment="每份成本(分)")
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)
    is_substitutable: Mapped[bool] = mapped_column(Boolean, default=False)
    substitute_ids: Mapped[list | None] = mapped_column(ARRAY(UUID(as_uuid=True)), comment="可替代食材ID列表")
    notes: Mapped[str | None] = mapped_column(Text, comment="配方备注")

    dish = relationship("Dish", back_populates="ingredients")


# ─────────────────────────────────────────────
# 4. Order — 订单
# ─────────────────────────────────────────────

class Order(TenantBase):
    """订单 — 全渠道统一, 折扣明细, 核销记录, 出餐状态

    修正#7:
    - table_number 移入 metadata (预制菜零售无桌台)
    - sales_channel → sales_channel_id 引用配置表，非硬编码枚举
    - order_type 明确订单类型
    """
    __tablename__ = "orders"

    order_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"), index=True)
    # 散客信息（未关联CDP时使用，老项目 customer_name/phone 迁入）
    customer_name: Mapped[str | None] = mapped_column(String(100), comment="散客姓名(未关联CDP)")
    customer_phone: Mapped[str | None] = mapped_column(String(20), comment="散客手机(未关联CDP)")
    table_number: Mapped[str | None] = mapped_column(String(20), comment="桌号(堂食场景快捷字段)")
    waiter_id: Mapped[str | None] = mapped_column(String(50), index=True)

    # 修正#7: 订单类型 + 渠道引用配置表
    order_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="dine_in",
        comment="dine_in/takeaway/delivery/retail/catering/banquet",
    )
    sales_channel_id: Mapped[str | None] = mapped_column(
        String(50), index=True,
        comment="引用SalesChannel配置表, e.g. ch_meituan",
    )

    # 金额（统一存分）
    total_amount_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="总金额(分)")
    discount_amount_fen: Mapped[int] = mapped_column(Integer, default=0, comment="折扣(分)")
    final_amount_fen: Mapped[int | None] = mapped_column(Integer, comment="实付(分)")

    # 状态与时间
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=OrderStatus.pending.value, index=True)
    order_time: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))

    notes: Mapped[str | None] = mapped_column(String(500))

    # 修正#7: metadata 存放 table_no/guest_count 等可选上下文
    # table_number 不再是顶层字段 — 预制菜/外卖/B2B 无桌台
    order_metadata: Mapped[dict | None] = mapped_column(
        JSON, default=dict,
        comment='{"table_no": "A03", "guest_count": 4, "delivery_address": "..."}',
    )

    # 蓝图扩展字段（wireframe-fields-v1）
    guest_count: Mapped[int | None] = mapped_column(Integer, comment="就餐人数")
    dining_duration_min: Mapped[int | None] = mapped_column(Integer, comment="就餐时长(分钟)")
    abnormal_flag: Mapped[bool] = mapped_column(Boolean, default=False, comment="异常标记")
    abnormal_type: Mapped[str | None] = mapped_column(String(50), comment="complaint/return/discount/timeout")
    discount_type: Mapped[str | None] = mapped_column(String(50), comment="折扣类型:coupon/vip/manager/promotion")
    margin_alert_flag: Mapped[bool] = mapped_column(Boolean, default=False, comment="毛利告警")
    gross_margin_before: Mapped[float | None] = mapped_column(Numeric(6, 4), comment="折扣前毛利率")
    gross_margin_after: Mapped[float | None] = mapped_column(Numeric(6, 4), comment="折扣后毛利率")
    served_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), comment="出餐完成时间")
    serve_duration_min: Mapped[int | None] = mapped_column(Integer, comment="出餐耗时(分钟)")

    # 收银员 & 来源 & 转台（v011 补全）
    cashier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), comment="收银员ID")
    service_charge_fen: Mapped[int | None] = mapped_column(Integer, comment="服务费总额(分)")
    order_source: Mapped[str | None] = mapped_column(String(50), comment="原始订单来源编码")
    table_transfer_from: Mapped[str | None] = mapped_column(String(20), comment="转台前桌号")

    # 关联
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_order_store_status", "store_id", "status"),
        Index("idx_order_store_time", "store_id", "order_time"),
    )


class OrderItem(TenantBase):
    """订单明细"""
    __tablename__ = "order_items"

    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True)
    dish_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("dishes.id"))
    item_name: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="单价(分)")
    subtotal_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="小计(分)")
    food_cost_fen: Mapped[int | None] = mapped_column(Integer, comment="BOM理论成本(分)")
    gross_margin: Mapped[float | None] = mapped_column(Numeric(6, 4), comment="毛利率")
    notes: Mapped[str | None] = mapped_column(String(255))
    customizations: Mapped[dict | None] = mapped_column(JSON, default=dict)

    # 蓝图扩展字段
    pricing_mode: Mapped[str | None] = mapped_column(String(20), comment="fixed/weight/market_price")
    weight_value: Mapped[float | None] = mapped_column(Numeric(8, 3), comment="称重值(kg)")
    gift_flag: Mapped[bool] = mapped_column(Boolean, default=False, comment="赠送标记")
    sent_to_kds_flag: Mapped[bool] = mapped_column(Boolean, default=False, comment="已发送KDS")
    kds_station: Mapped[str | None] = mapped_column(String(50), comment="目标档口")
    return_flag: Mapped[bool] = mapped_column(Boolean, default=False, comment="退菜标记")
    return_reason: Mapped[str | None] = mapped_column(String(200), comment="退菜原因")

    # 价格 & 折扣 & 做法 & 赠菜 & 套餐（v011 补全）
    original_price_fen: Mapped[int | None] = mapped_column(Integer, comment="原价/折前价(分)")
    single_discount_fen: Mapped[int | None] = mapped_column(Integer, comment="单品折扣金额(分)")
    practice_names: Mapped[str | None] = mapped_column(String(500), comment="做法名称(冗余,逗号分隔)")
    is_gift: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否赠菜")
    gift_reason: Mapped[str | None] = mapped_column(String(200), comment="赠菜原因")
    combo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), comment="所属套餐ID(NULL=非套餐)")

    order = relationship("Order", back_populates="items")


# ─────────────────────────────────────────────
# 5. Ingredient — 食材
# ─────────────────────────────────────────────

class IngredientMaster(TenantBase):
    """食材主档（集团级字典表）"""
    __tablename__ = "ingredient_masters"

    canonical_name: Mapped[str] = mapped_column(String(100), nullable=False)
    aliases: Mapped[list | None] = mapped_column(ARRAY(String(100)))
    category: Mapped[str] = mapped_column(String(30), nullable=False, comment="seafood/meat/vegetable/...")
    sub_category: Mapped[str | None] = mapped_column(String(30))
    base_unit: Mapped[str] = mapped_column(String(10), nullable=False, comment="kg/L/个")
    spec_desc: Mapped[str | None] = mapped_column(String(100))

    # 存储
    shelf_life_days: Mapped[int | None] = mapped_column(Integer)
    storage_type: Mapped[str] = mapped_column(String(20), nullable=False, default=StorageType.ambient.value)
    storage_temp_min: Mapped[float | None] = mapped_column(Numeric(5, 1))
    storage_temp_max: Mapped[float | None] = mapped_column(Numeric(5, 1))

    # 属性
    is_traceable: Mapped[bool] = mapped_column(Boolean, default=False)
    allergen_tags: Mapped[list | None] = mapped_column(ARRAY(String(30)))
    seasonality: Mapped[list | None] = mapped_column(ARRAY(String(2)), comment="月份如{3,4,5}")
    typical_waste_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    typical_yield_rate: Mapped[float | None] = mapped_column(Numeric(5, 4))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Ingredient(TenantBase):
    """门店库存台账"""
    __tablename__ = "ingredients"

    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    ingredient_name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50))
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    current_quantity: Mapped[float] = mapped_column(Float, default=0)
    min_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    max_quantity: Mapped[float | None] = mapped_column(Float)
    unit_price_fen: Mapped[int | None] = mapped_column(Integer, comment="单价(分)")
    status: Mapped[str] = mapped_column(String(20), default=InventoryStatus.normal.value, index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(100))
    supplier_contact: Mapped[str | None] = mapped_column(String(100), comment="供应商联系方式")

    transactions = relationship("IngredientTransaction", back_populates="ingredient", cascade="all, delete-orphan")


class IngredientTransaction(TenantBase):
    """库存流水"""
    __tablename__ = "ingredient_transactions"

    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ingredients.id"), nullable=False, index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True, comment="门店ID(便于按店查询)")
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="purchase/usage/waste/adjustment")
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit_cost_fen: Mapped[int | None] = mapped_column(Integer, comment="单位成本(分)")
    total_cost_fen: Mapped[int | None] = mapped_column(Integer, comment="总成本(分)=quantity*unit_cost_fen")

    # 库存快照（老项目 quantity_before/after 迁入，用于对账）
    quantity_before: Mapped[float | None] = mapped_column(Float, comment="操作前库存量")
    quantity_after: Mapped[float | None] = mapped_column(Float, comment="操作后库存量")

    # 操作人与时间
    performed_by: Mapped[str | None] = mapped_column(String(100), comment="操作人")
    transaction_time: Mapped[str | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="操作时间")

    reference_id: Mapped[str | None] = mapped_column(String(100), comment="关联单据号")
    notes: Mapped[str | None] = mapped_column(String(500))

    ingredient = relationship("Ingredient", back_populates="transactions")


# ─────────────────────────────────────────────
# 6. Employee — 员工
# ─────────────────────────────────────────────

class Employee(TenantBase):
    """员工 — 角色, 技能, 排班, 业绩提成, 效率指标"""
    __tablename__ = "employees"

    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    emp_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(50), nullable=False, comment="waiter/chef/cashier/manager")
    skills: Mapped[list | None] = mapped_column(ARRAY(String), default=list)

    # 雇佣信息
    hire_date: Mapped[str | None] = mapped_column(Date)
    employment_status: Mapped[str] = mapped_column(String(20), default=EmploymentStatus.regular.value)
    employment_type: Mapped[str] = mapped_column(String(30), default=EmploymentType.regular.value)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    probation_end_date: Mapped[str | None] = mapped_column(Date)
    grade_level: Mapped[str | None] = mapped_column(String(50))

    # IM 绑定
    wechat_userid: Mapped[str | None] = mapped_column(String(100), index=True)
    dingtalk_userid: Mapped[str | None] = mapped_column(String(100), index=True)

    # 个人信息
    gender: Mapped[str | None] = mapped_column(String(10))
    birth_date: Mapped[str | None] = mapped_column(Date)
    education: Mapped[str | None] = mapped_column(String(20))

    # 证照
    health_cert_expiry: Mapped[str | None] = mapped_column(Date)
    health_cert_attachment: Mapped[str | None] = mapped_column(String(500), comment="健康证附件路径")
    id_card_no: Mapped[str | None] = mapped_column(String(200), comment="AES-256-GCM加密")
    id_card_expiry: Mapped[str | None] = mapped_column(Date, comment="身份证到期日")
    background_check: Mapped[str | None] = mapped_column(String(50), comment="背调状态:pending/passed/failed")

    # 薪酬
    daily_wage_standard_fen: Mapped[int | None] = mapped_column(Integer, comment="日薪标准(分)")
    work_hour_type: Mapped[str | None] = mapped_column(String(30), comment="标准工时/综合工时")
    first_work_date: Mapped[str | None] = mapped_column(Date, comment="首次工作日期")
    regular_date: Mapped[str | None] = mapped_column(Date, comment="转正日期")
    seniority_months: Mapped[int | None] = mapped_column(Integer, comment="司龄(月)")
    bank_name: Mapped[str | None] = mapped_column(String(100))
    bank_account: Mapped[str | None] = mapped_column(String(200), comment="AES-256-GCM加密")
    bank_branch: Mapped[str | None] = mapped_column(String(200), comment="开户行支行")

    # 紧急联系人
    emergency_contact: Mapped[str | None] = mapped_column(String(50))
    emergency_phone: Mapped[str | None] = mapped_column(String(20))
    emergency_relation: Mapped[str | None] = mapped_column(String(20), comment="与紧急联系人关系")

    # 组织
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    preferences: Mapped[dict | None] = mapped_column(JSON, default=dict)
    performance_score: Mapped[str | None] = mapped_column(String(10))
    training_completed: Mapped[list | None] = mapped_column(ARRAY(String), default=list)
