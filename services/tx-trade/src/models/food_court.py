"""智慧商街/美食广场多商户POS模型

支持一个物理场所（商街/美食广场/食堂）下运营多个独立档口商户：
- 统一收银台收单，各档口独立KDS出餐
- 一笔支付按档口分账
- 独立营业额核算与日结

所有表包含 tenant_id + RLS 租户隔离。金额统一用分（整数）。
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

from pydantic import BaseModel, Field


# ─── SQLAlchemy ORM 模型 ─────────────────────────────────────────────────────


class FoodCourt(TenantBase):
    """商街/美食广场 — 统一收银场所"""
    __tablename__ = "food_courts"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="所属主门店ID（外键逻辑引用 stores.id）"
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="商街名称，如：XX美食广场"
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(500), comment="描述/简介"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active",
        comment="active=营业中 / inactive=停用"
    )
    unified_cashier: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        comment="是否启用统一收银台（True=顾客在统一收银点结账）"
    )
    # 扩展配置：营业时间、收银台数量等
    config: Mapped[Optional[dict]] = mapped_column(
        JSON, default=dict, comment="扩展配置JSON"
    )


class FoodCourtVendor(TenantBase):
    """商街档口（子商户）"""
    __tablename__ = "food_court_vendors"

    food_court_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food_courts.id"), nullable=False, index=True,
        comment="所属商街ID"
    )
    vendor_code: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="档口编号，如：A1 / B2（同一商街内唯一）"
    )
    vendor_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="档口名称，如：阿强烧腊、李姐粉面"
    )
    category: Mapped[Optional[str]] = mapped_column(
        String(50), comment="档口分类：烧腊/粉面/饮料/小吃/快餐等"
    )
    owner_name: Mapped[Optional[str]] = mapped_column(
        String(50), comment="档主姓名"
    )
    contact_phone: Mapped[Optional[str]] = mapped_column(
        String(20), comment="联系电话"
    )
    commission_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 4), comment="抽成比例，小数表示（如 0.08 = 8%）"
    )
    kds_station_id: Mapped[Optional[str]] = mapped_column(
        String(50), comment="对应KDS档口站点ID，KDS推送时使用"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active",
        comment="active=正常营业 / inactive=暂停 / suspended=被暂停（违规等）"
    )
    # 结算账户信息（银行卡/微信商户号等），不存敏感完整信息
    settlement_account: Mapped[Optional[dict]] = mapped_column(
        JSON, default=dict,
        comment="结算账户信息JSON：{type, account_last4, holder_name, bank_name}"
    )
    display_order: Mapped[int] = mapped_column(
        Integer, default=1, comment="排列顺序（收银台菜单分组顺序）"
    )


class FoodCourtOrder(TenantBase):
    """商街订单（跨档口统一订单）"""
    __tablename__ = "food_court_orders"

    food_court_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food_courts.id"), nullable=False, index=True,
        comment="所属商街ID"
    )
    order_no: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True,
        comment="订单号，格式：FC{YYYYMMDD}{6位序号}"
    )
    total_amount_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="订单总金额（分）"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
        comment="pending=待支付 / paid=已支付 / completed=已完成 / cancelled=已取消"
    )
    payment_method: Mapped[Optional[str]] = mapped_column(
        String(30), comment="支付方式：cash/wechat/alipay/unionpay/member_balance"
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), comment="支付完成时间"
    )
    cashier_id: Mapped[Optional[str]] = mapped_column(
        String(50), comment="收银员工号/ID"
    )
    notes: Mapped[Optional[str]] = mapped_column(
        String(500), comment="订单备注"
    )
    # 幂等键，防止重复支付
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(128), unique=True, index=True, comment="支付幂等键"
    )


class FoodCourtOrderItem(TenantBase):
    """商街订单行（按档口分组的菜品明细）"""
    __tablename__ = "food_court_order_items"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food_court_orders.id"), nullable=False, index=True,
        comment="所属商街订单ID"
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food_court_vendors.id"), nullable=False, index=True,
        comment="所属档口ID（KDS分发依据）"
    )
    dish_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="菜品名称（冗余存储，防止菜品被删改影响订单记录）"
    )
    dish_id: Mapped[Optional[str]] = mapped_column(
        String(50), comment="菜品ID（可空：档口有自己菜单时填写）"
    )
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="数量"
    )
    unit_price_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="单价（分）"
    )
    subtotal_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="小计（分）= quantity × unit_price_fen"
    )
    notes: Mapped[Optional[str]] = mapped_column(
        String(200), comment="菜品备注/做法要求"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
        comment="pending=待制作 / preparing=制作中 / ready=已出餐 / served=已取餐"
    )
    # KDS确认出餐时间戳
    ready_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), comment="档口标记出餐时间"
    )


class FoodCourtVendorSettlement(TenantBase):
    """档口结算记录（日结）"""
    __tablename__ = "food_court_vendor_settlements"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food_court_vendors.id"), nullable=False, index=True,
        comment="档口ID"
    )
    food_court_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food_courts.id"), nullable=False, index=True,
        comment="商街ID"
    )
    settlement_date: Mapped[date] = mapped_column(
        Date, nullable=False, index=True, comment="结算日期"
    )
    order_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="当日订单笔数"
    )
    item_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="当日菜品份数"
    )
    gross_amount_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="当日营业总额（分）"
    )
    commission_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="平台抽成（分）"
    )
    net_amount_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="档口实得金额（分）= gross - commission"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
        comment="pending=待结算 / settled=已结算"
    )
    settled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), comment="结算确认时间"
    )
    operator_id: Mapped[Optional[str]] = mapped_column(
        String(50), comment="财务确认人ID"
    )
    # 结算明细快照
    details: Mapped[Optional[dict]] = mapped_column(
        JSON, default=dict,
        comment="结算明细快照JSON：{orders: [], payment_breakdown: {}}"
    )


# ─── Pydantic Schemas（请求/响应） ────────────────────────────────────────────


class CreateFoodCourtReq(BaseModel):
    store_id: str = Field(description="所属门店ID")
    name: str = Field(max_length=100, description="商街名称")
    description: Optional[str] = Field(default=None, max_length=500)
    unified_cashier: bool = Field(default=True, description="是否启用统一收银台")
    config: Optional[dict] = Field(default=None, description="扩展配置JSON")


class UpdateFoodCourtReq(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    unified_cashier: Optional[bool] = None
    status: Optional[str] = Field(default=None, pattern="^(active|inactive)$")
    config: Optional[dict] = None


class CreateVendorReq(BaseModel):
    vendor_code: str = Field(max_length=20, description="档口编号，如 A1/B2")
    vendor_name: str = Field(max_length=100, description="档口名称")
    category: Optional[str] = Field(default=None, max_length=50, description="分类：烧腊/粉面/饮料")
    owner_name: Optional[str] = Field(default=None, max_length=50)
    contact_phone: Optional[str] = Field(default=None, max_length=20)
    commission_rate: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="抽成比例（0.0–1.0）"
    )
    kds_station_id: Optional[str] = Field(default=None, max_length=50, description="KDS站点ID")
    settlement_account: Optional[dict] = Field(default=None, description="结算账户信息JSON")
    display_order: int = Field(default=1, ge=1)


class UpdateVendorReq(BaseModel):
    vendor_name: Optional[str] = Field(default=None, max_length=100)
    category: Optional[str] = Field(default=None, max_length=50)
    owner_name: Optional[str] = Field(default=None, max_length=50)
    contact_phone: Optional[str] = Field(default=None, max_length=20)
    commission_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    kds_station_id: Optional[str] = Field(default=None, max_length=50)
    settlement_account: Optional[dict] = None
    display_order: Optional[int] = Field(default=None, ge=1)
    status: Optional[str] = Field(
        default=None, pattern="^(active|inactive|suspended)$"
    )


class FoodCourtOrderItemReq(BaseModel):
    vendor_id: str = Field(description="档口ID")
    dish_name: str = Field(max_length=100, description="菜品名称")
    dish_id: Optional[str] = Field(default=None, max_length=50, description="菜品ID（可选）")
    quantity: int = Field(ge=1, description="数量")
    unit_price_fen: int = Field(ge=0, description="单价（分）")
    notes: Optional[str] = Field(default=None, max_length=200)


class CreateFoodCourtOrderReq(BaseModel):
    items: list[FoodCourtOrderItemReq] = Field(min_length=1, description="订单菜品列表")
    cashier_id: Optional[str] = Field(default=None, description="收银员ID")
    notes: Optional[str] = Field(default=None, max_length=500)


class PayFoodCourtOrderReq(BaseModel):
    payment_method: str = Field(
        description="支付方式：cash/wechat/alipay/unionpay/member_balance"
    )
    amount_fen: int = Field(ge=1, description="实付金额（分）")
    idempotency_key: Optional[str] = Field(default=None, max_length=128, description="幂等键防重复扣款")


class GenerateSettlementReq(BaseModel):
    settlement_date: str = Field(description="结算日期，格式：YYYY-MM-DD")
    vendor_ids: Optional[list[str]] = Field(
        default=None, description="指定档口ID列表，不传则结算所有档口"
    )
