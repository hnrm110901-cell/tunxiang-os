"""POS 销售分成转入库 ORM + Pydantic Schema（PRD-11 sub-A / Phase 2 W11 / T2 + Tier 1 邻接）

ORM（SQLAlchemy 2.0 typed Mapped[]）:
  ShareSplitRule — 配置表 (每 dish 一条 active rule, UNIQUE)

Pydantic V2 Schema:
  ShareSplitMethod enum — even / weighted / manual (3-way 创始人锁定)
  ShareSplitRuleCreate / Update / Read
  ShareSplitSpec — caller (PR-B tx-trade) 调 auto_deduction 时传入的 spec dict 验证
  ResolvedShare — resolve_split 输出 (单个 share 的 cost 归属)
  ResolvedSplitResult — resolve_split 总输出 (含所有 shares + cost 校验)

业务流：
  总部食安/采购总监建 share_split_rule (dish 级 allow_share + default_method) →
  POS 端 caller 提供 ShareSplitSpec (含 method + count + weights/amounts) →
  share_split_service.resolve_split() 验证 + 分配 bom_cost_total_fen →
  auto_deduction emit inventory.split_attributed 事件 →
  (PR-C) tx-analytics 消费事件做 per-customer cost attribution dashboard

ShareSplitMethod 三选一:
  EVEN     — 均分: 1/N cost; caller 只传 count, server 处理 remainder fen
  WEIGHTED — 加权: 按 weights[] 归一化; sum(weights) > 0 必须
  MANUAL   — 手动: caller 传 amounts_fen[]; sum(amounts_fen) == bom_cost_total_fen 严格相等

每种 method 的 caller 输入校验:
  EVEN: weights=None, amounts_fen=None, count >= 2
  WEIGHTED: len(weights) == count, 所有 weight > 0
  MANUAL: len(amounts_fen) == count, 所有 amount >= 0, sum 后服务层校验
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import (
    Boolean,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


# ─────────────────────────────────────────────────────────────────────────────
# 枚举 (与 v434 CHECK 约束对齐)
# ─────────────────────────────────────────────────────────────────────────────


class ShareSplitMethod(str, Enum):
    """分享拆分方法 — 创始人 AskUserQuestion 锁定支持 3 种。

    - EVEN:     均分. server 自动 1/N 分配 + 余数 fen 分摊到 share[0..r-1].
    - WEIGHTED: 按 caller 传入的 weights[] 比例归一化分配.
    - MANUAL:   caller 直接传 amounts_fen[]; sum 必须等于 bom_cost_total_fen.
    """

    EVEN = "even"
    WEIGHTED = "weighted"
    MANUAL = "manual"


# ─────────────────────────────────────────────────────────────────────────────
# ORM 模型
# ─────────────────────────────────────────────────────────────────────────────


class ShareSplitRule(TenantBase):
    """share_split_rules — 每 dish 一条 active rule (UNIQUE (tenant, dish))

    - allow_share=FALSE 即"禁止分享" (例: 单人套餐 / 不可拆分的酒水)
    - default_method 是 caller 未指定时 fallback
    - max_share_count NULL = 不限人数; 非 NULL = 业务上限防极端拆分
    """

    __tablename__ = "share_split_rules"

    dish_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    allow_share: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_method: Mapped[str] = mapped_column(
        String(20), nullable=False, default="even"
    )
    max_share_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic V2 Schemas — 配置 CRUD
# ─────────────────────────────────────────────────────────────────────────────


class _BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ShareSplitRuleCreate(_BaseSchema):
    """新建分享规则。max_share_count NULL = 不限人数。"""

    dish_id: uuid.UUID
    allow_share: bool = True
    default_method: ShareSplitMethod = ShareSplitMethod.EVEN
    max_share_count: Optional[int] = Field(default=None, ge=2)
    notes: Optional[str] = Field(default=None, max_length=500)


class ShareSplitRuleUpdate(_BaseSchema):
    """更新分享规则。"""

    allow_share: Optional[bool] = None
    default_method: Optional[ShareSplitMethod] = None
    max_share_count: Optional[int] = Field(default=None, ge=2)
    is_active: Optional[bool] = None
    notes: Optional[str] = Field(default=None, max_length=500)


class ShareSplitRuleRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    dish_id: uuid.UUID
    allow_share: bool
    default_method: str
    max_share_count: Optional[int]
    is_active: bool
    notes: Optional[str]
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic V2 Schemas — Spec / resolve 输入输出
# ─────────────────────────────────────────────────────────────────────────────


class ShareSplitSpec(_BaseSchema):
    """caller (PR-B tx-trade cashier_engine / auto_deduction caller) 传入的 spec.

    method 决定 weights / amounts_fen 谁必填:
      - EVEN:     weights=None, amounts_fen=None
      - WEIGHTED: weights 必填, len == count, 每项 > 0
      - MANUAL:   amounts_fen 必填, len == count, 每项 >= 0, sum 由 service 验
    """

    method: ShareSplitMethod
    count: int = Field(ge=2, le=50, description="分享人数 (2-50)")
    weights: Optional[list[Decimal]] = Field(default=None, description="weighted 必填")
    amounts_fen: Optional[list[int]] = Field(default=None, description="manual 必填 (分)")

    @model_validator(mode="after")
    def _validate_method_params(self) -> ShareSplitSpec:
        if self.method == ShareSplitMethod.EVEN:
            if self.weights is not None or self.amounts_fen is not None:
                raise ValueError(
                    "ShareSplitSpec: method=even 不应传 weights/amounts_fen"
                )
        elif self.method == ShareSplitMethod.WEIGHTED:
            if self.weights is None:
                raise ValueError("ShareSplitSpec: method=weighted 必须传 weights[]")
            if self.amounts_fen is not None:
                raise ValueError(
                    "ShareSplitSpec: method=weighted 不应传 amounts_fen"
                )
            if len(self.weights) != self.count:
                raise ValueError(
                    f"ShareSplitSpec: weights len ({len(self.weights)}) != count ({self.count})"
                )
            for w in self.weights:
                if w <= 0:
                    raise ValueError("ShareSplitSpec: weights 每项必须 > 0")
        elif self.method == ShareSplitMethod.MANUAL:
            if self.amounts_fen is None:
                raise ValueError("ShareSplitSpec: method=manual 必须传 amounts_fen[]")
            if self.weights is not None:
                raise ValueError(
                    "ShareSplitSpec: method=manual 不应传 weights"
                )
            if len(self.amounts_fen) != self.count:
                raise ValueError(
                    f"ShareSplitSpec: amounts_fen len ({len(self.amounts_fen)}) != count ({self.count})"
                )
            for a in self.amounts_fen:
                if a < 0:
                    raise ValueError("ShareSplitSpec: amounts_fen 每项必须 >= 0")
        return self


class ResolvedShare(_BaseSchema):
    """单个 share 的解析结果。"""

    share_index: int = Field(ge=0)
    weight: Decimal = Field(description="归一化后权重 (1/N 或 weighted/sum)")
    attributed_cost_fen: int = Field(ge=0, description="分摊到本 share 的成本 (分)")


class ResolvedSplitResult(_BaseSchema):
    """resolve_split 总输出。"""

    method: ShareSplitMethod
    count: int
    bom_cost_total_fen: int = Field(ge=0)
    shares: list[ResolvedShare]
    # checksum: sum(shares.attributed_cost_fen) == bom_cost_total_fen 必为真


# ─────────────────────────────────────────────────────────────────────────────
# Validate-Spec request schema (REST endpoint /validate)
# ─────────────────────────────────────────────────────────────────────────────


class ValidateSpecRequest(_BaseSchema):
    """前端预校验 endpoint: 给定 spec + dish_id + bom_cost_total_fen,
    返回 ResolvedSplitResult 或 ValueError 描述.
    """

    dish_id: uuid.UUID
    spec: ShareSplitSpec
    bom_cost_total_fen: int = Field(ge=0)
