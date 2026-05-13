"""存酒管理 ORM 模型与 Pydantic Schema

表：
  wine_storage_records      — 存酒主记录（每次存入一条）
  wine_storage_transactions — 存酒操作流水（存入/取酒/续存/转台/核销/调整）

状态流转（wine_storage_records.status）：
  stored → partial_taken → fully_taken
         → expired（过期）
         → written_off（核销）

金额规范（CLAUDE.md §15+§17 Tier1）：
  存储一律用 fen int（storage_price_fen / price_at_trans_fen），
  Pydantic API 边界保留 Decimal 元字段（向后兼容）+ 新增 _fen 字段供新客户端。
"""

import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, Date, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

# ── 元 ↔ 分边界换算 helper（CLAUDE.md §15）─────────────────────────────────────


def _yuan_to_fen(yuan: Optional[Decimal]) -> Optional[int]:
    """元 Decimal → 分 int。None 透传；0 允许（赠酒/未定价）；负数拒。"""
    if yuan is None:
        return None
    if not isinstance(yuan, Decimal):
        yuan = Decimal(str(yuan))
    if yuan < 0:
        raise ValueError(f"金额不能为负，got {yuan}")
    fen = (yuan * 100).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    return int(fen)


def _fen_to_yuan_str(fen: Optional[int]) -> Optional[str]:
    """分 int → 元字符串两位小数（API 响应/SQL 序列化边界）。None 透传。"""
    if fen is None:
        return None
    return f"{Decimal(fen) / Decimal(100):.2f}"

# ─── SQLAlchemy ORM ───────────────────────────────────────────────────────────


class WineStorageRecord(TenantBase):
    """存酒主记录 — 每次存入一瓶/批酒水对应一条记录"""

    __tablename__ = "wine_storage_records"

    # 关联维度
    store_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    table_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    member_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    # 酒水信息
    bottle_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="酒水编号/条码")
    wine_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="酒水名称")
    wine_brand: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="品牌")
    wine_spec: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="规格，如 500ml/750ml")

    # 数量信息
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment="存入数量")
    remaining_quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment="剩余数量")
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="瓶", comment="单位：瓶/支/升")

    # 时间信息
    storage_date: Mapped[date] = mapped_column(Date, nullable=False, comment="存酒日期")
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="到期日，NULL=长期有效")

    # 状态与金额
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="stored",
        index=True,
        comment="stored/partial_taken/fully_taken/expired/written_off",
    )
    # 金额一律 fen 整数（CLAUDE.md §15）；存酒可未定价（赠酒/会员存）所以 nullable
    storage_price_fen: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="存入时金额（分）")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 操作人
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="操作员 ID")


class WineStorageTransaction(TenantBase):
    """存酒操作流水 — 每次取酒/续存/转台等操作对应一条流水"""

    __tablename__ = "wine_storage_transactions"

    # 关联主记录
    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wine_storage_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    store_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # 操作类型
    trans_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="store_in/take_out/extend/transfer_in/transfer_out/write_off/adjustment",
    )

    # 操作数量与金额
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment="本次操作数量（正数）")
    # 金额一律 fen 整数（CLAUDE.md §15）；7 类流水 store_in/take_out/extend/transfer_in/transfer_out/write_off/adjustment 共用此字段
    price_at_trans_fen: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="操作时单价或费用（分）"
    )

    # 关联上下文
    table_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="关联台位（取酒/转台时）")
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="关联订单 ID（取酒核销时）")

    # 操作人与审批
    operated_by: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="操作员 ID")
    operated_at: Mapped[datetime | None] = mapped_column(nullable=True, comment="操作时间")
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="审批人 ID（核销/调整时）")

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ─── Pydantic Schemas ─────────────────────────────────────────────────────────


class WineStoreRequest(BaseModel):
    """存酒入库请求"""

    store_id: str = Field(..., description="门店 ID")
    table_id: Optional[str] = Field(None, description="台位 ID（可选）")
    member_id: Optional[str] = Field(None, description="会员 ID（可选）")
    bottle_code: str = Field(..., min_length=1, max_length=64, description="酒水编号/条码")
    wine_name: str = Field(..., min_length=1, max_length=128, description="酒水名称")
    wine_brand: Optional[str] = Field(None, max_length=128, description="品牌")
    wine_spec: Optional[str] = Field(None, max_length=64, description="规格，如 500ml/750ml")
    quantity: int = Field(..., gt=0, description="存入数量")
    unit: str = Field("瓶", description="单位：瓶/支/升")
    storage_date: date = Field(..., description="存酒日期")
    expiry_date: Optional[date] = Field(None, description="到期日，不填表示长期有效")
    storage_price: Optional[Decimal] = Field(None, ge=0, description="存入时金额（元）")
    notes: Optional[str] = Field(None, max_length=500)
    created_by: Optional[str] = Field(None, description="操作员 ID")


class WineTakeRequest(BaseModel):
    """取酒请求"""

    quantity: int = Field(..., gt=0, description="取出数量")
    table_id: Optional[str] = Field(None, description="关联台位")
    order_id: Optional[str] = Field(None, description="关联订单 ID")
    operated_by: Optional[str] = Field(None, description="操作员 ID")
    notes: Optional[str] = Field(None, max_length=500)


class WineExtendRequest(BaseModel):
    """续存请求"""

    new_expiry_date: date = Field(..., description="新到期日")
    fee: Optional[Decimal] = Field(None, ge=0, description="续存费用（元，可选）")
    operated_by: Optional[str] = Field(None, description="操作员 ID")
    notes: Optional[str] = Field(None, max_length=500)


class WineTransferRequest(BaseModel):
    """转台请求"""

    to_table_id: str = Field(..., description="目标台位 ID")
    operated_by: Optional[str] = Field(None, description="操作员 ID")
    notes: Optional[str] = Field(None, max_length=500)


class WineWriteOffRequest(BaseModel):
    """核销请求"""

    reason: str = Field(..., min_length=1, max_length=500, description="核销原因")
    order_id: Optional[str] = Field(None, description="关联订单 ID（可选）")
    approved_by: Optional[str] = Field(None, description="审批人 ID")
    operated_by: Optional[str] = Field(None, description="操作员 ID")


class WineStorageTransactionResponse(BaseModel):
    """存酒流水响应

    金额字段对齐 ORM 列名 price_at_trans_fen（fen int），同时输出
    price_at_trans_yuan 元字符串供前端展示（PR #272 verifier 修复：
    原 price_at_trans: Decimal 与 ORM 列名不匹配，from_attributes=True
    会静默返回 None 丢失金额）。
    """

    id: str
    record_id: str
    trans_type: str
    quantity: int
    price_at_trans_fen: Optional[int] = None
    price_at_trans_yuan: Optional[str] = None
    table_id: Optional[str]
    order_id: Optional[str]
    operated_by: Optional[str]
    operated_at: Optional[datetime]
    approved_by: Optional[str]
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class WineStorageResponse(BaseModel):
    """存酒主记录响应（含计算字段）

    金额字段对齐 ORM 列名 storage_price_fen（fen int）+ 输出 storage_price_yuan
    元字符串供前端（PR #272 verifier 修复：原 storage_price: Decimal 与
    ORM 列名不匹配，from_attributes=True 会静默丢失金额）。
    """

    id: str
    tenant_id: str
    store_id: str
    table_id: Optional[str]
    member_id: Optional[str]
    bottle_code: str
    wine_name: str
    wine_brand: Optional[str]
    wine_spec: Optional[str]
    quantity: int
    remaining_quantity: int
    unit: str
    storage_date: date
    expiry_date: Optional[date]
    status: str
    storage_price_fen: Optional[int] = None
    storage_price_yuan: Optional[str] = None
    notes: Optional[str]
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    # 计算字段
    days_until_expiry: Optional[int] = Field(None, description="距到期天数，NULL=长期有效，负数=已过期")
    expiry_warning: bool = Field(False, description="true 表示 7 天内到期")

    # 关联流水（详情接口时填充）
    transactions: Optional[list[WineStorageTransactionResponse]] = Field(None)

    class Config:
        from_attributes = True


class WineStorageListQuery(BaseModel):
    """存酒列表查询参数"""

    store_id: Optional[str] = Field(None, description="按门店过滤")
    member_id: Optional[str] = Field(None, description="按会员过滤")
    status: Optional[str] = Field(None, description="按状态过滤，多个用逗号分隔")
    bottle_code: Optional[str] = Field(None, description="按酒水编号精确匹配")
    wine_name: Optional[str] = Field(None, description="按酒水名称模糊搜索")
    storage_date_from: Optional[date] = Field(None, description="存酒日期起始")
    storage_date_to: Optional[date] = Field(None, description="存酒日期截止")
    expiry_warning_only: bool = Field(False, description="仅返回 7 天内到期记录")
    page: int = Field(1, ge=1, description="页码（从 1 开始）")
    size: int = Field(20, ge=1, le=100, description="每页条数")
