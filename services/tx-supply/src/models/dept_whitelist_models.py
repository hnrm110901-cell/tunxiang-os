"""部门用料白名单 ORM + Pydantic Schema（PRD-08 / Phase 2 W11 / T2 + Tier 1 邻接）

ORM（SQLAlchemy 2.0 typed Mapped[]）:
  DepartmentIngredientWhitelist — 部门白名单主表

Pydantic V2 Schema:
  WhitelistCreate / Update / Read +
  BulkAuthorizeRequest / ValidateRequest

业务流：
  总部食安总监 / 采购总监建白名单（部门 × 食材 矩阵）→ 后厨领料 / BOM 扣料路径
  → dept_whitelist_service.validate_ingredient_allowed 校验 →
  违反 raise IngredientNotAllowedError（路由层映射 403 Forbidden / event AUDIT）

Typed Exception:
  IngredientNotAllowedError — 部门用料硬阻塞专用异常（与 ValueError 区分以让路由层
  典型场景映射 403 而非 422 — 这是"权限/合规"问题而非"参数错误"）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Boolean,
    Numeric,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


# ─────────────────────────────────────────────────────────────────────────────
# Typed Exception — 部门用料硬阻塞
# ─────────────────────────────────────────────────────────────────────────────


class IngredientNotAllowedError(Exception):
    """部门白名单硬阻塞专用异常。

    与 ValueError 区分：路由层应映射 403 Forbidden（合规/权限层面）
    而非 422 Unprocessable Entity（参数错误层面）。
    """

    def __init__(
        self,
        dept_id: str,
        ingredient_id: str,
        ingredient_name: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        self.dept_id = dept_id
        self.ingredient_id = ingredient_id
        self.ingredient_name = ingredient_name
        if message is None:
            name_hint = f"（{ingredient_name}）" if ingredient_name else ""
            message = (
                f"部门 dept_id={dept_id} 未授权使用食材 ingredient_id={ingredient_id}"
                f"{name_hint} — 请联系食安/采购总监添加白名单"
            )
        self.message = message
        super().__init__(message)


# ─────────────────────────────────────────────────────────────────────────────
# ORM 模型
# ─────────────────────────────────────────────────────────────────────────────


class DepartmentIngredientWhitelist(TenantBase):
    """部门-食材白名单（department_ingredient_whitelists）

    - max_qty_per_day NULL = 不限量（仅校验白名单存在性）— D1 锁定
    - is_active=FALSE 即"软禁用"，校验视为不存在
    - UNIQUE (tenant_id, dept_id, ingredient_id) WHERE is_deleted=FALSE
    """

    __tablename__ = "department_ingredient_whitelists"

    dept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    max_qty_per_day: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 4), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic V2 Schemas
# ─────────────────────────────────────────────────────────────────────────────


class _BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


# ── 白名单 CRUD ─────────────────────────────────────────────────────────────


class WhitelistCreate(_BaseSchema):
    """新建白名单。max_qty_per_day NULL = 不限量。"""

    dept_id: uuid.UUID
    ingredient_id: uuid.UUID
    max_qty_per_day: Optional[Decimal] = Field(default=None, gt=0)
    notes: Optional[str] = Field(default=None, max_length=500)


class WhitelistUpdate(_BaseSchema):
    """更新白名单。max_qty_per_day 显式传 None 不可（用 PATCH 语义保留原值）。"""

    max_qty_per_day: Optional[Decimal] = Field(default=None, gt=0)
    is_active: Optional[bool] = None
    notes: Optional[str] = Field(default=None, max_length=500)


class WhitelistRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    dept_id: uuid.UUID
    ingredient_id: uuid.UUID
    max_qty_per_day: Optional[Decimal]
    is_active: bool
    notes: Optional[str]
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


# ── 批量授权（矩阵编辑器一键提交）────────────────────────────────────────────


class BulkAuthorizeItem(_BaseSchema):
    ingredient_id: uuid.UUID
    max_qty_per_day: Optional[Decimal] = Field(default=None, gt=0)
    notes: Optional[str] = Field(default=None, max_length=500)


class BulkAuthorizeRequest(_BaseSchema):
    """一个部门 → 多个食材一次性授权（矩阵编辑器场景）。

    重复 (dept_id, ingredient_id) 已存在 → upsert：恢复 is_active=TRUE + 更新 max_qty_per_day。
    """

    dept_id: uuid.UUID
    items: list[BulkAuthorizeItem] = Field(min_length=1, max_length=200)


class BulkAuthorizeResult(_BaseSchema):
    dept_id: uuid.UUID
    created_count: int
    updated_count: int
    items: list[WhitelistRead]


# ── 校验请求（route 层 + 内部 service-to-service 共用）──────────────────────


class ValidateRequest(_BaseSchema):
    """校验某部门是否可领某食材（指定数量可选）。"""

    dept_id: uuid.UUID
    ingredient_id: uuid.UUID
    qty: Optional[Decimal] = Field(default=None, gt=0)


class ValidateResult(_BaseSchema):
    allowed: bool
    reason: str = Field(description="拒绝原因，allowed=True 时为'OK'")
    max_qty_per_day: Optional[Decimal] = None
