"""盘亏处理审批闭环 ORM 模型 + Pydantic V2 schema

对应 v370 迁移建立的 4 张表：
  StocktakeLossCaseORM      — 盘亏案件主表
  StocktakeLossItemORM      — 案件明细
  StocktakeLossApprovalORM  — 审批节点流水
  StocktakeLossWriteoffORM  — 财务核销凭证

状态机（CaseStatus）单向不可逆：
  DRAFT → PENDING_APPROVAL → APPROVED → WRITTEN_OFF
                          ↓
                       REJECTED（终态）
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase

# ─────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────


class CaseStatus(str, Enum):
    """案件状态机（单向不可逆，REJECTED 为终态）"""

    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ResponsiblePartyType(str, Enum):
    """责任方类型"""

    STORE = "STORE"
    EMPLOYEE = "EMPLOYEE"
    SUPPLIER = "SUPPLIER"
    UNKNOWN = "UNKNOWN"


class ApproverRole(str, Enum):
    """审批角色"""

    STORE_MANAGER = "STORE_MANAGER"
    REGIONAL_MANAGER = "REGIONAL_MANAGER"
    FINANCE = "FINANCE"


class Decision(str, Enum):
    """审批决策"""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReasonCode(str, Enum):
    """盘亏原因代码"""

    EXPIRED = "EXPIRED"
    BROKEN = "BROKEN"
    THEFT = "THEFT"
    MEASUREMENT = "MEASUREMENT"
    UNRECORDED_USE = "UNRECORDED_USE"
    OTHER = "OTHER"


# ─────────────────────────────────────────────────────────────────────
# 状态机合法转换映射（service 层使用）
# ─────────────────────────────────────────────────────────────────────

ALLOWED_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.DRAFT: {CaseStatus.PENDING_APPROVAL},
    CaseStatus.PENDING_APPROVAL: {CaseStatus.APPROVED, CaseStatus.REJECTED},
    CaseStatus.APPROVED: {CaseStatus.WRITTEN_OFF},
    CaseStatus.REJECTED: set(),  # 终态
    CaseStatus.WRITTEN_OFF: set(),  # 终态
}


class InvalidStateTransition(Exception):
    """非法状态转换异常（如 DRAFT → APPROVED 直接跳转）"""

    def __init__(self, current: CaseStatus, target: CaseStatus):
        self.current = current
        self.target = target
        super().__init__(
            f"Invalid state transition: {current.value} → {target.value}"
        )


def assert_can_transition(current: CaseStatus, target: CaseStatus) -> None:
    """校验状态转换合法性，非法则抛 InvalidStateTransition。"""
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidStateTransition(current, target)


# ─────────────────────────────────────────────────────────────────────
# ORM Models
# ─────────────────────────────────────────────────────────────────────


class StocktakeLossCaseORM(TenantBase):
    """盘亏案件主表"""

    __tablename__ = "stocktake_loss_cases"

    stocktake_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="关联 stocktakes.id"
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="门店 ID"
    )
    case_no: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="案件号 LOSS-YYYYMMDD-NNNN"
    )
    total_loss_amount_fen: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="盘亏总金额（分）"
    )
    total_gain_amount_fen: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="盘盈总金额（分）"
    )
    # 生成列：DB 维护，ORM 仅读取
    net_loss_amount_fen: Mapped[int] = mapped_column(
        BigInteger,
        nullable=True,
        comment="净亏损 = total_loss - total_gain（DB 生成列）",
    )
    responsible_party_type: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    responsible_party_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    responsible_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    case_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CaseStatus.DRAFT.value
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    final_approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    written_off_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    items: Mapped[list[StocktakeLossItemORM]] = relationship(
        "StocktakeLossItemORM",
        back_populates="case",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    approvals: Mapped[list[StocktakeLossApprovalORM]] = relationship(
        "StocktakeLossApprovalORM",
        back_populates="case",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    writeoffs: Mapped[list[StocktakeLossWriteoffORM]] = relationship(
        "StocktakeLossWriteoffORM",
        back_populates="case",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "case_no", name="uq_stl_cases_tenant_caseno"),
        Index(
            "idx_stl_cases_tenant_status_created",
            "tenant_id",
            "case_status",
            "created_at",
        ),
        Index("idx_stl_cases_tenant_stocktake", "tenant_id", "stocktake_id"),
    )


class StocktakeLossItemORM(TenantBase):
    """案件明细（每条食材一行）"""

    __tablename__ = "stocktake_loss_items"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stocktake_loss_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    batch_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    expected_qty: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    actual_qty: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    # 生成列
    diff_qty: Mapped[Optional[float]] = mapped_column(Numeric(14, 3), nullable=True)
    unit_cost_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    diff_amount_fen: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    reason_code: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    reason_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    case: Mapped[StocktakeLossCaseORM] = relationship(
        "StocktakeLossCaseORM", back_populates="items"
    )

    __table_args__ = (
        Index("idx_stl_items_tenant_case", "tenant_id", "case_id"),
        Index("idx_stl_items_tenant_ingredient", "tenant_id", "ingredient_id"),
    )


class StocktakeLossApprovalORM(TenantBase):
    """审批节点流水"""

    __tablename__ = "stocktake_loss_approvals"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stocktake_loss_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    approval_node_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_role: Mapped[str] = mapped_column(String(32), nullable=False)
    approver_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    decision: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    case: Mapped[StocktakeLossCaseORM] = relationship(
        "StocktakeLossCaseORM", back_populates="approvals"
    )

    __table_args__ = (
        UniqueConstraint(
            "case_id", "approval_node_seq", name="uq_stl_approvals_case_seq"
        ),
        Index(
            "idx_stl_approvals_tenant_case_seq",
            "tenant_id",
            "case_id",
            "approval_node_seq",
        ),
    )


class StocktakeLossWriteoffORM(TenantBase):
    """财务核销凭证"""

    __tablename__ = "stocktake_loss_writeoffs"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stocktake_loss_cases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    writeoff_voucher_no: Mapped[str] = mapped_column(String(64), nullable=False)
    writeoff_amount_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    accounting_subject: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    writeoff_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finance_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    attachment_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    case: Mapped[StocktakeLossCaseORM] = relationship(
        "StocktakeLossCaseORM", back_populates="writeoffs"
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "writeoff_voucher_no",
            name="uq_stl_writeoffs_tenant_voucher",
        ),
        Index("idx_stl_writeoffs_tenant_case", "tenant_id", "case_id"),
    )


# ─────────────────────────────────────────────────────────────────────
# Pydantic V2 schemas（API 入参 / 出参）
# ─────────────────────────────────────────────────────────────────────


class LossItemInput(BaseModel):
    """单条盘亏明细入参"""

    ingredient_id: str = Field(..., description="食材 ID")
    expected_qty: float = Field(..., description="账面数量")
    actual_qty: float = Field(..., description="实盘数量")
    unit_cost_fen: int = Field(..., ge=0, description="单价（分）")
    batch_no: Optional[str] = None
    reason_code: Optional[ReasonCode] = None
    reason_detail: Optional[str] = None


class CreateLossCasePayload(BaseModel):
    """手动创建案件入参"""

    stocktake_id: str
    store_id: str
    items: list[LossItemInput] = Field(default_factory=list)
    responsible_party_type: Optional[ResponsiblePartyType] = None
    responsible_party_id: Optional[str] = None
    responsible_reason: Optional[str] = None
    created_by: str

    @field_validator("items")
    @classmethod
    def _items_non_negative(cls, v: list[LossItemInput]) -> list[LossItemInput]:
        for it in v:
            if it.expected_qty < 0 or it.actual_qty < 0:
                raise ValueError("expected_qty / actual_qty must be >= 0")
        return v


class AssignResponsibilityPayload(BaseModel):
    """指派责任方入参"""

    responsible_party_type: ResponsiblePartyType
    responsible_party_id: Optional[str] = None
    responsible_reason: Optional[str] = None


class SubmitForApprovalPayload(BaseModel):
    """提交审批入参（可选自定义审批链；未提供则按净亏损金额自动确定）"""

    submitted_by: str
    approval_chain: Optional[list[ApproverRole]] = Field(
        default=None,
        description="自定义审批链节点；省略时按金额规则自动决定",
    )


class ApproveDecisionPayload(BaseModel):
    """审批决策入参"""

    approver_id: str
    approver_role: ApproverRole
    comment: Optional[str] = None


class WriteoffPayload(BaseModel):
    """核销入参"""

    writeoff_voucher_no: str = Field(..., min_length=1, max_length=64)
    writeoff_amount_fen: int = Field(..., gt=0)
    accounting_subject: Optional[str] = Field(
        default="管理费用-存货损失", max_length=64
    )
    finance_user_id: str
    attachment_url: Optional[str] = None
    comment: Optional[str] = None


class LossStatsFilter(BaseModel):
    """统计入参"""

    from_date: str = Field(..., description="YYYY-MM-DD")
    to_date: str = Field(..., description="YYYY-MM-DD")
    store_id: Optional[str] = None
