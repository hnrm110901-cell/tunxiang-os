"""channel_dispute — Sprint E4 异议工作流 Pydantic schema

DisputeType / DisputeState / OpenDisputeRequest / ResolveDisputeRequest /
DisputeRecord / DisputeListResponse。

设计（CLAUDE.md §10/§14）：
  - Pydantic V2 + Literal 枚举，全 snake_case
  - 金额一律 int 分
  - state CHECK 与 v277 迁移一致
  - decision_by/decision_at/decision_reason 仅在 resolve 阶段写入
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# 与 v277 CHECK 一致
DisputeType = Literal[
    "missing_item",
    "wrong_item",
    "delivery_late",
    "quality",
    "platform_audit",   # 平台审核异议（强制人工）
    "refund_request",
    "chargeback",
    "other",
]

DisputeState = Literal[
    "pending",
    "auto_accepted",
    "manual_reviewing",
    "accepted",
    "rejected",
    "escalated",
]

# 决策点 #5 默认（待创始人最终签字）
DEFAULT_AUTO_ACCEPT_THRESHOLD_FEN = 5000  # ¥50

# 这些 dispute_type 不允许 auto_accept（强制人工）
NON_AUTO_ACCEPT_TYPES: frozenset[str] = frozenset({"platform_audit", "chargeback"})


class OpenDisputeRequest(BaseModel):
    """POST /channels/disputes/open 入参。"""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    store_id: UUID
    canonical_order_id: UUID
    channel_code: str = Field(..., min_length=1, max_length=64)
    external_dispute_id: str = Field(..., min_length=1, max_length=128)
    dispute_type: DisputeType
    claimed_amount_fen: int = Field(..., ge=0)
    opened_at: datetime
    payload: dict[str, Any]


class ResolveDisputeRequest(BaseModel):
    """POST /channels/disputes/{id}/resolve 入参。"""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    decision: Literal["accepted", "rejected", "escalated"]
    reason: str = Field(..., min_length=1, max_length=500)


class DisputeRecord(BaseModel):
    """DB 读模型。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    store_id: UUID
    canonical_order_id: UUID
    channel_code: str
    external_dispute_id: str
    dispute_type: str
    claimed_amount_fen: int
    state: str
    auto_accept_threshold_fen: Optional[int] = None
    decision_reason: Optional[str] = None
    decision_by: Optional[UUID] = None
    decision_at: Optional[datetime] = None
    payload: dict[str, Any]
    opened_at: datetime
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


class DisputeListResponse(BaseModel):
    """GET /channels/disputes 响应。"""

    model_config = ConfigDict(extra="forbid")

    items: list[DisputeRecord]
    total: int
    page: int
    size: int
