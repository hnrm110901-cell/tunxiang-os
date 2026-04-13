"""
费控模块事件类型定义
包含 tx-expense 对外发出的事件 和 订阅的外部事件。

设计原则：
- 涉及资金的事件必须携带 tenant_id + application_id 以便审计
- Agent触发的事件必须携带 agent_type 字段便于可解释审计
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID


# ─────────────────────────────────────────────
# 对外发出的事件（tx-expense → 其他服务）
# ─────────────────────────────────────────────

EXPENSE_APPLICATION_SUBMITTED = "expense.application.submitted"
EXPENSE_APPLICATION_APPROVED = "expense.application.approved"
EXPENSE_APPLICATION_REJECTED = "expense.application.rejected"
EXPENSE_PETTY_CASH_BALANCE_LOW = "expense.petty_cash.balance_low"
EXPENSE_PETTY_CASH_ANOMALY = "expense.petty_cash.anomaly_detected"
EXPENSE_BUDGET_WARNING_80 = "expense.budget.warning_80"
EXPENSE_BUDGET_WARNING_95 = "expense.budget.warning_95"
EXPENSE_COST_ATTRIBUTION_COMPLETE = "expense.cost.attribution_complete"
EXPENSE_INVOICE_VERIFIED = "expense.invoice.verified"


@dataclass
class ExpenseApplicationSubmittedPayload:
    """费用申请提交事件 payload"""
    application_id: str
    tenant_id: str
    store_id: str
    applicant_id: str
    scenario_code: str
    total_amount: int      # 分(fen)
    submitted_at: str      # ISO8601


@dataclass
class ExpensePettyCashBalanceLowPayload:
    """备用金余额不足预警 payload（A1 Agent 触发）"""
    account_id: str
    store_id: str
    tenant_id: str
    current_balance: int   # 分(fen)
    threshold: int         # 分(fen)，触发预警的阈值
    days_of_coverage: float  # 按历史日均消耗，当前余额可用天数
    agent_type: str = "a1_petty_cash_guardian"


@dataclass
class ExpenseBudgetWarningPayload:
    """预算预警 payload（A4 Agent 触发）"""
    budget_plan_id: str
    tenant_id: str
    brand_id: str
    store_id: Optional[str]
    consumed_rate: float       # 消耗比例，如 0.82 表示82%
    consumed_amount: int       # 已消耗金额（分）
    budget_amount: int         # 预算总额（分）
    forecasted_overrun: Optional[int]  # 预测超支金额（分），None表示不会超支
    warning_level: str         # "yellow"(80%) 或 "red"(95%)
    agent_type: str = "a4_budget_monitor"


@dataclass
class ExpenseCostAttributionCompletePayload:
    """成本归因完成 payload（A6 Agent 触发，通知 tx-finance 更新 P&L）"""
    attribution_batch_id: str
    tenant_id: str
    store_id: str
    period: str            # 如 "2026-04"
    total_attributed: int  # 本次归集总金额（分）
    item_count: int        # 归集条目数
    agent_type: str = "a6_cost_attribution"


# ─────────────────────────────────────────────
# 订阅的外部事件（其他服务 → tx-expense）
# ─────────────────────────────────────────────

OPS_DAILY_CLOSE_COMPLETED = "ops.daily_close.completed"
# payload 包含: store_id, tenant_id, close_date, total_revenue(分), pos_session_id

ORG_EMPLOYEE_DEPARTED = "org.employee.departed"
# payload 包含: employee_id, tenant_id, store_id, departure_date, departure_reason

OPS_INSPECTION_TASK_CREATED = "ops.inspection_task.created"
# payload 包含: task_id, inspector_id, store_ids[], planned_start, planned_end

OPS_INSPECTION_TASK_STATUS_CHANGED = "ops.inspection_task.status_changed"
# payload 包含: task_id, inspector_id, new_status(departed/arrived/completed), store_id, gps_location

SUPPLY_PURCHASE_ORDER_GOODS_RECEIVED = "supply.purchase_order.goods_received"
# payload 包含: purchase_order_id, supplier_id, store_id, total_amount(分), received_items[]

TRADE_REVENUE_DAILY_SUMMARY = "trade.revenue.daily_summary"
# payload 包含: store_id, tenant_id, date, total_revenue(分), vs_last_week_rate, vs_budget_rate
