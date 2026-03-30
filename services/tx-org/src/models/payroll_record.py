"""工资记录数据模型

# SCHEMA SQL:
# CREATE TABLE payroll_records (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,
#     employee_id UUID NOT NULL,
#     store_id UUID NOT NULL,
#     payroll_month VARCHAR(7) NOT NULL,  -- "2026-03"
#     base_salary NUMERIC(10,2) DEFAULT 0,
#     attendance_days INTEGER DEFAULT 0,
#     attendance_deduction NUMERIC(10,2) DEFAULT 0,
#     commission NUMERIC(10,2) DEFAULT 0,
#     bonus NUMERIC(10,2) DEFAULT 0,
#     allowances NUMERIC(10,2) DEFAULT 0,
#     gross_salary NUMERIC(10,2) NOT NULL,     -- 应发工资
#     social_insurance_personal NUMERIC(10,2), -- 个人五险一金
#     income_tax NUMERIC(10,2) DEFAULT 0,      -- 个税
#     net_salary NUMERIC(10,2) NOT NULL,       -- 实发工资
#     social_insurance_company NUMERIC(10,2),  -- 公司五险一金
#     details JSONB,                           -- 计算明细
#     status VARCHAR(20) DEFAULT 'draft',      -- draft/confirmed/paid
#     confirmed_at TIMESTAMPTZ,
#     paid_at TIMESTAMPTZ,
#     created_at TIMESTAMPTZ DEFAULT NOW()
# );
#
# -- RLS 策略（使用 app.tenant_id）
# ALTER TABLE payroll_records ENABLE ROW LEVEL SECURITY;
# CREATE POLICY payroll_records_tenant_isolation ON payroll_records
#     USING (tenant_id = current_setting('app.tenant_id')::UUID);
#
# -- 索引
# CREATE INDEX idx_payroll_records_tenant_month ON payroll_records(tenant_id, payroll_month);
# CREATE INDEX idx_payroll_records_employee ON payroll_records(employee_id, payroll_month);
# CREATE INDEX idx_payroll_records_store ON payroll_records(store_id, payroll_month);
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class PayrollRecordStatus:
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    PAID = "paid"


class PayrollRecord(BaseModel):
    """工资记录模型（对应 payroll_records 表）"""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    employee_id: UUID
    store_id: UUID
    payroll_month: str = Field(..., pattern=r"^\d{4}-\d{2}$", description="格式 YYYY-MM")

    # 收入项（元）
    base_salary: float = Field(default=0.0, description="基本工资（元）")
    attendance_days: int = Field(default=0, description="实际出勤天数")
    attendance_deduction: float = Field(default=0.0, description="考勤扣款（元）")
    commission: float = Field(default=0.0, description="提成（元）")
    bonus: float = Field(default=0.0, description="绩效奖金（元）")
    allowances: float = Field(default=0.0, description="各类补贴合计（元）")

    # 汇总项（元）
    gross_salary: float = Field(..., description="应发工资（元）")
    social_insurance_personal: Optional[float] = Field(None, description="个人五险一金（元）")
    income_tax: float = Field(default=0.0, description="个税（元）")
    net_salary: float = Field(..., description="实发工资（元）")
    social_insurance_company: Optional[float] = Field(None, description="公司五险一金（元）")

    # 详细明细（JSON）
    details: Optional[Dict[str, Any]] = Field(None, description="计算明细，含各险种分项")

    # 状态
    status: str = Field(default=PayrollRecordStatus.DRAFT)
    confirmed_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)

    model_config = {"json_encoders": {UUID: str, datetime: lambda v: v.isoformat()}}

    def confirm(self) -> None:
        """确认工资单"""
        if self.status != PayrollRecordStatus.DRAFT:
            raise ValueError(f"只有草稿状态可以确认，当前状态：{self.status}")
        self.status = PayrollRecordStatus.CONFIRMED
        self.confirmed_at = datetime.now()

    def mark_paid(self) -> None:
        """标记已发放"""
        if self.status != PayrollRecordStatus.CONFIRMED:
            raise ValueError(f"只有已确认状态可标记发放，当前状态：{self.status}")
        self.status = PayrollRecordStatus.PAID
        self.paid_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class StoreSalarySummary(BaseModel):
    """门店月度薪资汇总"""

    store_id: str
    payroll_month: str
    tenant_id: str
    employee_count: int
    total_gross_yuan: float
    total_net_yuan: float
    total_social_insurance_personal_yuan: float
    total_social_insurance_company_yuan: float
    total_income_tax_yuan: float
    total_labor_cost_yuan: float  # 企业总人力成本 = gross + company_si
    records: list[PayrollRecord] = Field(default_factory=list)
