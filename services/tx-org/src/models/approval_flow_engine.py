"""审批流引擎数据模型（v2，基于 approval_flow_templates + approval_flow_nodes）

对应 v060 迁移创建的 4 张表：
  - approval_flow_templates    — 审批流模板
  - approval_flow_nodes        — 审批节点
  - approval_instances         — 审批单实例（扩展字段）
  - approval_node_instances    — 节点审批记录

所有 Pydantic 模型用于 API 请求/响应校验。
SQLAlchemy ORM 模型用于数据库操作。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# ── 常量 ──────────────────────────────────────────────────────────────────────

VALID_BUSINESS_TYPES: frozenset[str] = frozenset(
    ["leave", "purchase", "discount", "price_change", "refund", "expense", "custom"]
)

BusinessType = Literal[
    "leave", "purchase", "discount", "price_change", "refund", "expense", "custom"
]

NodeType = Literal["role_level", "specific_role", "specific_person", "auto"]

ApproveType = Literal["any_one", "all_must"]

InstanceStatus = Literal["pending", "approved", "rejected", "cancelled", "timeout"]

NodeInstanceStatus = Literal["pending", "approved", "rejected", "skipped", "timeout"]

TimeoutAction = Literal["auto_approve", "auto_reject", "escalate"]


# ── 条件评估 ──────────────────────────────────────────────────────────────────


def eval_condition(condition: dict[str, Any] | None, ctx: dict[str, Any]) -> bool:
    """
    评估单个条件是否满足。

    condition 格式：{"field": "amount", "op": ">=", "value": 100000}
    condition 为 None 或空时返回 True（无条件满足）。
    """
    if not condition:
        return True
    field = condition.get("field")
    op = condition.get("op")
    threshold = condition.get("value")
    if field is None or op is None or threshold is None:
        return True
    actual = ctx.get(field)
    if actual is None:
        return False
    try:
        actual_f = float(actual)
        threshold_f = float(threshold)
    except (TypeError, ValueError):
        return False
    result_map: dict[str, bool] = {
        ">": actual_f > threshold_f,
        ">=": actual_f >= threshold_f,
        "<": actual_f < threshold_f,
        "<=": actual_f <= threshold_f,
        "==": actual_f == threshold_f,
        "!=": actual_f != threshold_f,
    }
    return result_map.get(op, False)


def eval_trigger_conditions(
    trigger_conditions: dict[str, Any], ctx: dict[str, Any]
) -> bool:
    """
    评估模板触发条件是否满足（ALL 语义，每个字段条件都要满足）。

    trigger_conditions 格式：{"amount": {"op": ">=", "value": 100000}}
    空 {} 表示无条件触发（始终需要审批）。
    """
    if not trigger_conditions:
        return True
    for field, rule in trigger_conditions.items():
        if not eval_condition({"field": field, **rule}, ctx):
            return False
    return True


# ── API 请求 / 响应 Pydantic 模型 ─────────────────────────────────────────────


class NodeConditionSchema(BaseModel):
    """条件 JSON 结构"""

    field: str = Field(..., description="条件字段，如 'amount'")
    op: str = Field(..., description="运算符：>, >=, <, <=, ==, !=")
    value: float = Field(..., description="阈值")


class CreateNodeReq(BaseModel):
    """创建/更新审批节点请求"""

    node_order: int = Field(..., ge=1, description="节点序号，从 1 开始")
    node_name: str = Field(..., max_length=100, description="节点名称，如'直属上级'")
    node_type: NodeType
    approver_role_level: Optional[int] = Field(
        None, ge=1, le=10,
        description="node_type='role_level' 时的最低角色等级"
    )
    approver_role_id: Optional[UUID] = Field(
        None, description="node_type='specific_role' 时的角色配置 ID"
    )
    approver_employee_id: Optional[UUID] = Field(
        None, description="node_type='specific_person' 时的员工 ID"
    )
    approve_type: ApproveType = Field(
        default="any_one",
        description="多人审批时：any_one=任一通过, all_must=全部通过"
    )
    auto_approve_condition: Optional[NodeConditionSchema] = Field(
        None, description="节点自动审批条件，满足时自动通过"
    )
    timeout_hours: Optional[int] = Field(
        None, ge=1, description="超时小时数，NULL 表示不超时"
    )
    timeout_action: Optional[TimeoutAction] = None


class CreateTemplateReq(BaseModel):
    """创建审批流模板请求"""

    template_name: str = Field(..., max_length=100)
    business_type: BusinessType
    trigger_conditions: dict[str, Any] = Field(
        default_factory=dict,
        description="触发条件 JSONB，为空则始终触发审批"
    )
    nodes: list[CreateNodeReq] = Field(default_factory=list)


class UpdateTemplateReq(BaseModel):
    """更新审批流模板请求"""

    template_name: Optional[str] = Field(None, max_length=100)
    trigger_conditions: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None


class CreateInstanceReq(BaseModel):
    """发起审批请求"""

    template_id: UUID = Field(..., description="审批流模板 ID")
    business_type: BusinessType
    business_id: str = Field(..., description="关联业务单据 ID")
    initiator_id: UUID = Field(..., description="发起人员工 ID")
    store_id: UUID = Field(..., description="门店 ID，用于查找审批人")
    title: str = Field(..., max_length=200, description="审批标题，如'张三请年假3天'")
    summary: dict[str, Any] = Field(
        default_factory=dict,
        description="业务摘要，如 {amount: 5000, days: 3}"
    )


class ApproveReq(BaseModel):
    """审批同意请求"""

    approver_id: UUID
    comment: Optional[str] = None


class RejectReq(BaseModel):
    """审批拒绝请求"""

    approver_id: UUID
    comment: Optional[str] = None


class CancelReq(BaseModel):
    """撤回审批请求"""

    initiator_id: UUID = Field(..., description="发起人 ID，需与创建时一致")


# ── 数据行映射 Dict 类型（从 DB 查询结果构建） ─────────────────────────────────

# 用于内部传递，避免多余的 ORM 模型层
TemplateRow = dict[str, Any]
NodeRow = dict[str, Any]
InstanceRow = dict[str, Any]
NodeInstanceRow = dict[str, Any]
