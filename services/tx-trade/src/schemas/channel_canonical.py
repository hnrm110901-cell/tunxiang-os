"""channel_canonical — Sprint E1 渠道 canonical Pydantic schema

定义 channel_canonical_orders 表对应的请求/读模型契约。

设计原则（CLAUDE.md §10/§15）：
  - Pydantic V2，全部 snake_case
  - 金额一律 int 分（不接受浮点）
  - ChannelCode 用 Literal 枚举，新增渠道必须先在此处注册
  - status 与迁移 v276 CHECK 一致

E1 范围（红线：本模块为新增契约，不修改现有适配器）：
  - CanonicalOrderItem      — 嵌套商品行
  - CanonicalOrderRequest   — POST /channels/canonical/orders 入参
  - CanonicalOrderRecord    — DB 读模型（GET 路由响应 data 字段）

后续 E2/E3：
  - 各适配器（pinjin/aiqiwei/meituan/eleme/douyin/...）以纯函数方式
    将渠道原始报文映射为 CanonicalOrderRequest，实现彻底解耦
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ─── 渠道码（与适配器目录命名对齐）──────────────────────────────────────
#
# 新增渠道：先在此处加 Literal 值，再在迁移 v276 status CHECK 之外（status
# 与 channel_code 是两个独立维度，不共享 CHECK）配套加适配器实现。
ChannelCode = Literal[
    "meituan",       # 美团外卖
    "eleme",         # 饿了么
    "douyin",        # 抖音外卖
    "xiaohongshu",   # 小红书外卖（试点渠道）
    "wechat_self",   # 微信小程序自有外卖
    "wechat_group",  # 微信社群团购
    "self_pickup",   # 自提渠道（线上下单到店取餐）
]

CanonicalOrderStatus = Literal[
    "received",   # 已接收（默认初始态）
    "accepted",   # 商家接单
    "rejected",   # 商家拒单
    "delivered",  # 已送达 / 已完成
    "cancelled",  # 已取消
    "disputed",   # 异议进行中
]


class CanonicalOrderItem(BaseModel):
    """单条订单明细。"""

    model_config = ConfigDict(extra="forbid")

    dish_external_id: str = Field(..., min_length=1, max_length=128, description="渠道菜品 ID")
    dish_name: str = Field(..., min_length=1, max_length=200)
    quantity: int = Field(..., ge=1, description="份数")
    unit_price_fen: int = Field(..., ge=0, description="单价（分）")
    spec: Optional[str] = Field(default=None, max_length=200)
    line_subsidy_fen: int = Field(default=0, ge=0, description="本行渠道补贴")
    line_merchant_share_fen: int = Field(default=0, ge=0, description="本行商家承担补贴")


class CanonicalOrderRequest(BaseModel):
    """POST /channels/canonical/orders 入参。

    适配器侧（pinjin/aiqiwei/meituan/...）将渠道原始报文映射为本模型。
    payload 字段保留原始报文，后续若 mapping 需升级可基于 payload 重建。
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    store_id: UUID
    channel_code: ChannelCode
    external_order_id: str = Field(..., min_length=1, max_length=128)
    status: CanonicalOrderStatus = "received"
    items: list[CanonicalOrderItem] = Field(..., min_length=1, max_length=200)
    total_fen: int = Field(..., ge=0)
    subsidy_fen: int = Field(default=0, ge=0)
    merchant_share_fen: int = Field(default=0, ge=0)
    commission_fen: int = Field(default=0, ge=0)
    received_at: datetime
    payload: dict[str, Any] = Field(
        ...,
        description="渠道原始报文（保留全量，便于 mapping 升级时回放）",
    )

    @field_validator("subsidy_fen", "merchant_share_fen", "commission_fen")
    @classmethod
    def _amount_within_total(cls, v: int) -> int:
        # 单字段非负在 Field 已校验；此处只兜底类型
        return int(v)

    def assert_amount_consistency(self) -> None:
        """业务一致性校验：subsidy + commission 不能超过 total。

        Service 层 ingest 时调用，违反则 400 INVALID_AMOUNTS。
        merchant_share_fen 是 subsidy_fen 内部子项（商家承担部分），
        因此不参与"不超过 total"的判断。
        """
        if self.subsidy_fen + self.commission_fen > self.total_fen:
            raise ValueError(
                "subsidy_fen + commission_fen must not exceed total_fen"
            )
        if self.merchant_share_fen > self.subsidy_fen:
            raise ValueError(
                "merchant_share_fen must not exceed subsidy_fen"
            )


class CanonicalOrderRecord(BaseModel):
    """DB 读模型（GET 路由响应 data）。

    settlement_fen 由数据库 GENERATED STORED 列计算，应用层只读。
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    store_id: UUID
    channel_code: str
    external_order_id: str
    canonical_order_id: Optional[UUID] = None
    status: str
    total_fen: int
    subsidy_fen: int
    merchant_share_fen: int
    commission_fen: int
    settlement_fen: int
    payload: dict[str, Any]
    received_at: datetime
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


class CanonicalOrderListResponse(BaseModel):
    """GET /channels/canonical/orders 列表响应。"""

    model_config = ConfigDict(extra="forbid")

    items: list[CanonicalOrderRecord]
    total: int
    page: int
    size: int
