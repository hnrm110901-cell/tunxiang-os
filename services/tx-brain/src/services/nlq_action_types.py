"""NLQ → 三类操作 Pydantic 类型 — S4-03 Issue #290 / Tier 1。

四个白名单 actionId（与 issue 验收一致）：
  - menu.toggle_availability  上下架
  - menu.update_price         改价
  - inventory.86              库存清零
  - roster.update             排班修改

设计要点：
  - ActionId 是单一来源（Literal），ALLOWED_ACTION_IDS 从它派生（registry.py）
  - 金额字段统一 fen（整数）— CLAUDE.md §15 v147 起规范
  - confirmation_token 由 dispatcher 在 dry-run 阶段生成，确认时回传校验
  - constraint_block 字段是 stub（PR1）— PR2 接 tx-agent constraints.ConstraintResult
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ─── 单一来源：四个白名单 actionId ───
ActionId = Literal[
    "menu.toggle_availability",
    "menu.update_price",
    "inventory.86",
    "roster.update",
]


class ActionRequest(BaseModel):
    """tx-brain NLQ → 三类操作 入参。"""

    action_id: ActionId
    tenant_id: str  # UUID 字符串（路由层用 TenantSession 校验）
    store_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    operator_id: str  # admin user id（决策留痕必填）
    natural_query: str  # 原始 NLQ 文本（决策留痕）


class DryRunDiff(BaseModel):
    """二次确认前的预览 diff。"""

    summary: str  # 例: 把『酸菜鱼』价格从 ¥88.00 改为 ¥99.00
    fields: dict[str, dict[str, Any]] = Field(default_factory=dict)
    affected_count: int = 1
    risk_warnings: list[str] = Field(default_factory=list)
    constraint_block: Optional[dict[str, Any]] = None  # PR1 stub；PR2 接 ConstraintResult


class ConfirmRequest(BaseModel):
    """用户二次确认入参。"""

    action_id: ActionId
    confirmation_token: str  # tx-brain 在 dry-run 阶段返回
    confirmed_at: datetime


class ActionResult(BaseModel):
    """执行结果。"""

    success: bool
    action_id: ActionId
    confirmation_token: str
    executed_at: Optional[datetime] = None
    result_data: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    constraint_block: Optional[dict[str, Any]] = None
