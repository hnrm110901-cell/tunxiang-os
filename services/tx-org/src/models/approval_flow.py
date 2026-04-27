"""审批流数据模型

# SCHEMA SQL:
# CREATE TABLE approval_flow_definitions (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,
#     flow_name VARCHAR(100) NOT NULL,
#     business_type VARCHAR(50) NOT NULL,  -- discount/purchase/salary_adjust/menu_change
#     steps JSONB NOT NULL,
#     -- steps格式: [{"step": 1, "role": "store_manager", "timeout_hours": 24,
#     --              "condition": {"field": "amount", "op": ">", "value": 500}}]
#     is_active BOOLEAN DEFAULT TRUE,
#     created_at TIMESTAMPTZ DEFAULT NOW()
# );
#
# CREATE TABLE approval_instances (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,
#     flow_def_id UUID REFERENCES approval_flow_definitions(id),
#     business_type VARCHAR(50) NOT NULL,
#     source_id UUID,            -- 关联业务单据ID
#     title VARCHAR(200) NOT NULL,
#     amount NUMERIC(12,2),      -- 用于条件路由
#     current_step INTEGER DEFAULT 1,
#     status VARCHAR(20) DEFAULT 'pending',  -- pending/approved/rejected/cancelled
#     initiator_id UUID NOT NULL,
#     store_id UUID NOT NULL,
#     context JSONB DEFAULT '{}',  -- 业务上下文
#     created_at TIMESTAMPTZ DEFAULT NOW(),
#     completed_at TIMESTAMPTZ
# );
#
# CREATE TABLE approval_records (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,
#     instance_id UUID NOT NULL REFERENCES approval_instances(id),
#     step INTEGER NOT NULL,
#     approver_id UUID NOT NULL,
#     action VARCHAR(20) NOT NULL,  -- approved/rejected/transferred
#     comment TEXT,
#     acted_at TIMESTAMPTZ DEFAULT NOW()
# );
#
# -- RLS 策略（使用 app.tenant_id）
# ALTER TABLE approval_flow_definitions ENABLE ROW LEVEL SECURITY;
# CREATE POLICY approval_flow_definitions_tenant_isolation ON approval_flow_definitions
#     USING (tenant_id = current_setting('app.tenant_id')::UUID);
#
# ALTER TABLE approval_instances ENABLE ROW LEVEL SECURITY;
# CREATE POLICY approval_instances_tenant_isolation ON approval_instances
#     USING (tenant_id = current_setting('app.tenant_id')::UUID);
#
# ALTER TABLE approval_records ENABLE ROW LEVEL SECURITY;
# CREATE POLICY approval_records_tenant_isolation ON approval_records
#     USING (tenant_id = current_setting('app.tenant_id')::UUID);
#
# -- 索引
# CREATE INDEX idx_approval_flow_defs_tenant ON approval_flow_definitions(tenant_id, business_type);
# CREATE INDEX idx_approval_instances_tenant_status ON approval_instances(tenant_id, status);
# CREATE INDEX idx_approval_instances_initiator ON approval_instances(tenant_id, initiator_id);
# CREATE INDEX idx_approval_records_instance ON approval_records(instance_id);
# CREATE INDEX idx_approval_records_approver ON approval_records(tenant_id, approver_id);
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# ── 常量 ──────────────────────────────────────────────────────────────────────

VALID_BUSINESS_TYPES = frozenset(["discount", "purchase", "salary_adjust", "menu_change"])

VALID_STEP_OPS = frozenset([">", ">=", "<", "<=", "==", "!="])


class InstanceStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class RecordAction:
    APPROVED = "approved"
    REJECTED = "rejected"
    TRANSFERRED = "transferred"


# ── 条件路由规则 ───────────────────────────────────────────────────────────────


class StepCondition(BaseModel):
    """步骤条件：当 field op value 为真时，该步骤生效"""

    field: str = Field(..., description="评估字段，如 'amount'")
    op: str = Field(..., description="比较运算符：>, >=, <, <=, ==, !=")
    value: float = Field(..., description="比较阈值")

    def evaluate(self, context: Dict[str, Any]) -> bool:
        """根据上下文评估条件是否满足"""
        actual = context.get(self.field)
        if actual is None:
            return False
        try:
            actual_f = float(actual)
        except (TypeError, ValueError):
            return False

        ops = {
            ">": actual_f > self.value,
            ">=": actual_f >= self.value,
            "<": actual_f < self.value,
            "<=": actual_f <= self.value,
            "==": actual_f == self.value,
            "!=": actual_f != self.value,
        }
        return ops.get(self.op, False)


class FlowStep(BaseModel):
    """审批流步骤定义"""

    step: int = Field(..., ge=1, description="步骤序号，从 1 开始")
    role: str = Field(..., description="审批角色，如 store_manager/area_director/hq_finance")
    timeout_hours: int = Field(default=48, ge=1, description="超时催办时间（小时）")
    condition: Optional[StepCondition] = Field(None, description="步骤触发条件，为 None 时表示无条件执行")


# ── 流程定义模型 ───────────────────────────────────────────────────────────────


class ApprovalFlowDefinition(BaseModel):
    """审批流定义（对应 approval_flow_definitions 表）"""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    flow_name: str = Field(..., max_length=100)
    business_type: str = Field(..., description="业务类型: discount/purchase/salary_adjust/menu_change")
    steps: List[FlowStep] = Field(..., min_length=1, description="审批步骤列表，按 step 字段排序")
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)

    model_config = {"json_encoders": {UUID: str, datetime: lambda v: v.isoformat()}}

    def get_applicable_steps(self, context: Dict[str, Any]) -> List[FlowStep]:
        """返回在当前上下文中生效的步骤（按 step 升序）"""
        result: List[FlowStep] = []
        for step in sorted(self.steps, key=lambda s: s.step):
            if step.condition is None or step.condition.evaluate(context):
                result.append(step)
        return result

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


# ── 审批实例模型 ───────────────────────────────────────────────────────────────


class ApprovalInstance(BaseModel):
    """审批实例（对应 approval_instances 表）"""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    flow_def_id: UUID
    business_type: str
    source_id: Optional[UUID] = None
    title: str = Field(..., max_length=200)
    amount: Optional[float] = Field(None, description="关联金额，用于条件路由")
    current_step: int = Field(default=1, ge=1)
    status: str = Field(default=InstanceStatus.PENDING)
    initiator_id: UUID
    store_id: UUID
    context: Dict[str, Any] = Field(default_factory=dict, description="业务上下文")
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    model_config = {"json_encoders": {UUID: str, datetime: lambda v: v.isoformat()}}

    def is_terminal(self) -> bool:
        return self.status in (
            InstanceStatus.APPROVED,
            InstanceStatus.REJECTED,
            InstanceStatus.CANCELLED,
        )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


# ── 审批记录模型 ───────────────────────────────────────────────────────────────


class ApprovalRecord(BaseModel):
    """审批操作记录（对应 approval_records 表）"""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    instance_id: UUID
    step: int = Field(..., ge=1)
    approver_id: UUID
    action: str = Field(..., description="approved/rejected/transferred")
    comment: Optional[str] = None
    acted_at: datetime = Field(default_factory=datetime.now)

    model_config = {"json_encoders": {UUID: str, datetime: lambda v: v.isoformat()}}

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")
