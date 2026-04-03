"""加盟商数据模型

# SCHEMA SQL:
# CREATE TABLE franchisees (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,           -- 所属集团
#     franchisee_name VARCHAR(100) NOT NULL,
#     contact_name VARCHAR(50),
#     contact_phone VARCHAR(20),
#     contract_start DATE,
#     contract_end DATE,
#     royalty_rate NUMERIC(5,4) NOT NULL DEFAULT 0.05,  -- 基础分润率5%
#     royalty_tiers JSONB DEFAULT '[]',
#     -- tiers: [{"min_revenue": 100000, "rate": 0.04}, {"min_revenue": 500000, "rate": 0.03}]
#     status VARCHAR(20) DEFAULT 'active',  -- active/suspended/terminated
#     created_at TIMESTAMPTZ DEFAULT NOW()
# );
#
# CREATE TABLE franchisee_stores (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,
#     franchisee_id UUID NOT NULL REFERENCES franchisees(id),
#     store_id UUID NOT NULL,
#     joined_at DATE NOT NULL,
#     UNIQUE(tenant_id, store_id)
# );
#
# CREATE TABLE royalty_bills (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,
#     franchisee_id UUID NOT NULL REFERENCES franchisees(id),
#     bill_month VARCHAR(7) NOT NULL,     -- "2026-03"
#     total_revenue NUMERIC(12,2) NOT NULL,
#     royalty_amount NUMERIC(10,2) NOT NULL,
#     status VARCHAR(20) DEFAULT 'pending',  -- pending/confirmed/paid/overdue
#     due_date DATE,
#     paid_at TIMESTAMPTZ,
#     created_at TIMESTAMPTZ DEFAULT NOW()
# );
#
# -- RLS 策略（使用 app.tenant_id，v006+ 安全标准）
# ALTER TABLE franchisees ENABLE ROW LEVEL SECURITY;
# ALTER TABLE franchisees FORCE ROW LEVEL SECURITY;
# CREATE POLICY franchisees_rls ON franchisees
#     USING (
#         current_setting('app.tenant_id', TRUE) IS NOT NULL
#         AND current_setting('app.tenant_id', TRUE) <> ''
#         AND tenant_id = current_setting('app.tenant_id')::UUID
#     );
#
# ALTER TABLE franchisee_stores ENABLE ROW LEVEL SECURITY;
# ALTER TABLE franchisee_stores FORCE ROW LEVEL SECURITY;
# CREATE POLICY franchisee_stores_rls ON franchisee_stores
#     USING (
#         current_setting('app.tenant_id', TRUE) IS NOT NULL
#         AND current_setting('app.tenant_id', TRUE) <> ''
#         AND tenant_id = current_setting('app.tenant_id')::UUID
#     );
#
# ALTER TABLE royalty_bills ENABLE ROW LEVEL SECURITY;
# ALTER TABLE royalty_bills FORCE ROW LEVEL SECURITY;
# CREATE POLICY royalty_bills_rls ON royalty_bills
#     USING (
#         current_setting('app.tenant_id', TRUE) IS NOT NULL
#         AND current_setting('app.tenant_id', TRUE) <> ''
#         AND tenant_id = current_setting('app.tenant_id')::UUID
#     );
#
# -- 索引
# CREATE INDEX idx_franchisees_tenant_status ON franchisees(tenant_id, status);
# CREATE INDEX idx_franchisee_stores_tenant ON franchisee_stores(tenant_id, franchisee_id);
# CREATE INDEX idx_franchisee_stores_store ON franchisee_stores(tenant_id, store_id);
# CREATE INDEX idx_royalty_bills_tenant_month ON royalty_bills(tenant_id, bill_month);
# CREATE INDEX idx_royalty_bills_franchisee ON royalty_bills(franchisee_id, bill_month);
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  状态常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class FranchiseeStatus:
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class RoyaltyBillStatus:
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PAID = "paid"
    OVERDUE = "overdue"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  阶梯分润层级
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class RoyaltyTier(BaseModel):
    """分润阶梯层级（营业额达到 min_revenue 后使用此 rate）"""

    min_revenue: float = Field(..., description="触发阶梯的最低月营业额（元）", ge=0)
    rate: float = Field(..., description="该阶梯适用的分润率", gt=0, lt=1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  加盟商
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class Franchisee(BaseModel):
    """加盟商（对应 franchisees 表）"""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID = Field(..., description="所属集团 tenant_id")
    franchisee_name: str = Field(..., max_length=100, description="加盟商名称")
    contact_name: Optional[str] = Field(None, max_length=50, description="联系人姓名")
    contact_phone: Optional[str] = Field(None, max_length=20, description="联系人电话")
    contract_start: Optional[date] = Field(None, description="合同开始日期")
    contract_end: Optional[date] = Field(None, description="合同结束日期")
    royalty_rate: float = Field(
        default=0.05,
        description="基础分润率（无阶梯时使用）",
        gt=0,
        lt=1,
    )
    royalty_tiers: List[RoyaltyTier] = Field(
        default_factory=list,
        description="阶梯分润配置（按 min_revenue 升序），空列表表示无阶梯",
    )
    status: str = Field(default=FranchiseeStatus.ACTIVE, description="active/suspended/terminated")
    created_at: datetime = Field(default_factory=datetime.now)

    model_config = {"json_encoders": {UUID: str, datetime: lambda v: v.isoformat(), date: str}}

    def is_active(self) -> bool:
        return self.status == FranchiseeStatus.ACTIVE

    def sorted_tiers(self) -> List[RoyaltyTier]:
        """按 min_revenue 升序排列阶梯（便于计算时二分查找）"""
        return sorted(self.royalty_tiers, key=lambda t: t.min_revenue)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  加盟商门店关联
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class FranchiseeStore(BaseModel):
    """加盟商门店关联（对应 franchisee_stores 表）"""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    franchisee_id: UUID
    store_id: UUID
    joined_at: date = Field(default_factory=date.today)

    model_config = {"json_encoders": {UUID: str, date: str}}

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  分润账单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class RoyaltyBill(BaseModel):
    """月度分润账单（对应 royalty_bills 表）"""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    franchisee_id: UUID
    bill_month: str = Field(..., pattern=r"^\d{4}-\d{2}$", description="格式 YYYY-MM")
    total_revenue: float = Field(..., description="当月总营业额（元）", ge=0)
    royalty_amount: float = Field(..., description="当月分润金额（元）", ge=0)
    status: str = Field(
        default=RoyaltyBillStatus.PENDING,
        description="pending/confirmed/paid/overdue",
    )
    due_date: Optional[date] = Field(None, description="账单到期日")
    paid_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)

    model_config = {"json_encoders": {UUID: str, datetime: lambda v: v.isoformat(), date: str}}

    def confirm(self) -> None:
        """总部确认账单"""
        if self.status != RoyaltyBillStatus.PENDING:
            raise ValueError(f"只有 pending 状态可以确认，当前状态：{self.status}")
        self.status = RoyaltyBillStatus.CONFIRMED

    def mark_paid(self) -> None:
        """标记已付款"""
        if self.status not in (RoyaltyBillStatus.CONFIRMED, RoyaltyBillStatus.OVERDUE):
            raise ValueError(f"只有 confirmed/overdue 状态可标记付款，当前状态：{self.status}")
        self.status = RoyaltyBillStatus.PAID
        self.paid_at = datetime.now()

    def mark_overdue(self) -> None:
        """标记逾期"""
        if self.status in (RoyaltyBillStatus.PAID, RoyaltyBillStatus.OVERDUE):
            return
        self.status = RoyaltyBillStatus.OVERDUE

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")
