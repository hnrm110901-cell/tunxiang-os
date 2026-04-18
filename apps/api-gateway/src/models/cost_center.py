"""
成本中心模型 — 门店成本核算的分组基础
- CostCenter: 成本中心树（正餐/NPC/PC/后勤/中央厨房/总部）
- EmployeeCostCenter: 员工-成本中心分摊（支持一员工多中心按比例分摊）
- CostCenterBudget: 月度预算（人力预算/营收目标/实际人力）

金额统一存分（fen），含 `_yuan` 只读属性。
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, TimestampMixin


class CostCenter(Base, TimestampMixin):
    """成本中心（树形结构）"""

    __tablename__ = "cost_centers"
    __table_args__ = (UniqueConstraint("store_id", "code", name="uq_cc_store_code"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 编码：全局唯一，支持父子层级 (如 FB01 / FB01.01)
    code = Column(String(50), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    # 分类: 正餐|NPC|PC|后勤|中央厨房|总部
    category = Column(String(30), nullable=False, index=True)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("cost_centers.id"), nullable=True, index=True)
    store_id = Column(String(50), nullable=True, index=True)  # 总部/中央厨房可为空
    is_active = Column(Boolean, nullable=False, default=True)
    description = Column(String(500), nullable=True)


class EmployeeCostCenter(Base, TimestampMixin):
    """员工-成本中心分摊（allocation_pct 总和 = 100%）"""

    __tablename__ = "employee_cost_centers"
    __table_args__ = (
        UniqueConstraint("employee_id", "cost_center_id", "effective_from", name="uq_emp_cc_from"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(String(50), ForeignKey("employees.id"), nullable=False, index=True)
    cost_center_id = Column(
        UUID(as_uuid=True), ForeignKey("cost_centers.id"), nullable=False, index=True
    )
    # 分摊比例 0-100
    allocation_pct = Column(Integer, nullable=False, default=100)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)


class CostCenterBudget(Base, TimestampMixin):
    """月度成本中心预算/实际"""

    __tablename__ = "cost_center_budgets"
    __table_args__ = (UniqueConstraint("cost_center_id", "year_month", name="uq_ccb_cc_ym"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cost_center_id = Column(
        UUID(as_uuid=True), ForeignKey("cost_centers.id"), nullable=False, index=True
    )
    year_month = Column(String(7), nullable=False, index=True)  # YYYY-MM
    labor_budget_fen = Column(BigInteger, nullable=False, default=0)
    revenue_target_fen = Column(BigInteger, nullable=False, default=0)
    actual_labor_fen = Column(BigInteger, nullable=False, default=0)

    @property
    def labor_budget_yuan(self) -> float:
        return round((self.labor_budget_fen or 0) / 100, 2)

    @property
    def revenue_target_yuan(self) -> float:
        return round((self.revenue_target_fen or 0) / 100, 2)

    @property
    def actual_labor_yuan(self) -> float:
        return round((self.actual_labor_fen or 0) / 100, 2)
