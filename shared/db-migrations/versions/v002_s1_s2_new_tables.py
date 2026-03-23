"""V3.2 新增 12 张业务表 — 桌台/支付/退款/日结/交接班/小票/出品部门/日清日结/Agent决策

Revision ID: v002
Revises: v001
Create Date: 2026-03-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision: str = "v002"
down_revision: Union[str, None] = "v001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 本次新增的 12 张表（按依赖顺序排列）
NEW_TABLES = [
    "tables",
    "payments",
    "refunds",
    "settlements",
    "shift_handovers",
    "receipt_templates",
    "receipt_logs",
    "production_depts",
    "dish_dept_mappings",
    "daily_ops_flows",
    "daily_ops_nodes",
    "agent_decision_logs",
]


def _enable_rls(table_name: str) -> None:
    """为表启用 RLS + 创建租户隔离策略"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table_name} ON {table_name} "
        f"USING (tenant_id = current_setting('app.tenant_id')::UUID)"
    )
    op.execute(
        f"CREATE POLICY tenant_insert_{table_name} ON {table_name} "
        f"FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID)"
    )


def _disable_rls(table_name: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_insert_{table_name} ON {table_name}")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table_name} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # ---------------------------------------------------------------
    # 1. tables (桌台)
    # ---------------------------------------------------------------
    op.create_table(
        "tables",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("table_no", sa.String(20), nullable=False, comment="桌号如A01"),
        sa.Column("area", sa.String(50), comment="区域：大厅/包间/露台"),
        sa.Column("floor", sa.Integer, server_default="1"),
        sa.Column("seats", sa.Integer, nullable=False, comment="座位数"),
        sa.Column("min_consume_fen", sa.Integer, server_default="0", comment="最低消费(分)"),
        sa.Column("status", sa.String(20), nullable=False, server_default="free", index=True),
        sa.Column("current_order_id", UUID(as_uuid=True), comment="当前订单ID"),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("config", JSON, comment="桌台特殊配置"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_tables_store_status", "tables", ["store_id", "status"])

    # ---------------------------------------------------------------
    # 2. payments (支付)
    # ---------------------------------------------------------------
    op.create_table(
        "payments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False, index=True),
        sa.Column("payment_no", sa.String(64), unique=True, nullable=False, comment="支付流水号"),
        sa.Column("method", sa.String(20), nullable=False, server_default="cash"),
        sa.Column("amount_fen", sa.Integer, nullable=False, comment="支付金额(分)"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("is_actual_revenue", sa.Boolean, nullable=False, server_default="true", comment="是否计入实收"),
        sa.Column("actual_revenue_ratio", sa.Float, nullable=False, server_default="1.0",
                  comment="实收比例(0-1)"),
        sa.Column("payment_category", sa.String(20), nullable=False, server_default="other",
                  comment="支付类别"),
        sa.Column("trade_no", sa.String(128), comment="第三方交易号"),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("credit_account_name", sa.String(100), comment="挂账单位/人"),
        sa.Column("credit_account_phone", sa.String(20)),
        sa.Column("notes", sa.Text),
        sa.Column("extra", JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # ---------------------------------------------------------------
    # 3. refunds (退款)
    # ---------------------------------------------------------------
    op.create_table(
        "refunds",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False, index=True),
        sa.Column("payment_id", UUID(as_uuid=True), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("refund_no", sa.String(64), unique=True, nullable=False),
        sa.Column("refund_type", sa.String(20), nullable=False, server_default="full"),
        sa.Column("amount_fen", sa.Integer, nullable=False, comment="退款金额(分)"),
        sa.Column("reason", sa.String(500)),
        sa.Column("operator_id", sa.String(50), comment="操作员ID"),
        sa.Column("refunded_at", sa.DateTime(timezone=True)),
        sa.Column("trade_no", sa.String(128), comment="第三方退款交易号"),
        sa.Column("extra", JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # ---------------------------------------------------------------
    # 4. settlements (日结)
    # ---------------------------------------------------------------
    op.create_table(
        "settlements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("settlement_date", sa.Date, nullable=False, index=True),
        sa.Column("settlement_type", sa.String(20), nullable=False, server_default="daily"),
        # 汇总金额(分)
        sa.Column("total_revenue_fen", sa.Integer, server_default="0", comment="总营收(分)"),
        sa.Column("total_discount_fen", sa.Integer, server_default="0", comment="总折扣(分)"),
        sa.Column("total_refund_fen", sa.Integer, server_default="0", comment="总退款(分)"),
        sa.Column("net_revenue_fen", sa.Integer, server_default="0", comment="净营收(分)"),
        # 按支付方式汇总
        sa.Column("cash_fen", sa.Integer, server_default="0"),
        sa.Column("wechat_fen", sa.Integer, server_default="0"),
        sa.Column("alipay_fen", sa.Integer, server_default="0"),
        sa.Column("unionpay_fen", sa.Integer, server_default="0"),
        sa.Column("credit_fen", sa.Integer, server_default="0", comment="挂账(分)"),
        sa.Column("member_balance_fen", sa.Integer, server_default="0", comment="会员余额(分)"),
        # 订单统计
        sa.Column("total_orders", sa.Integer, server_default="0"),
        sa.Column("total_guests", sa.Integer, server_default="0"),
        sa.Column("avg_per_guest_fen", sa.Integer, server_default="0", comment="客单价(分)"),
        # 现金盘点
        sa.Column("cash_expected_fen", sa.Integer, server_default="0", comment="应有现金(分)"),
        sa.Column("cash_actual_fen", sa.Integer, comment="实际现金(分)"),
        sa.Column("cash_diff_fen", sa.Integer, comment="现金差异(分)"),
        sa.Column("operator_id", sa.String(50), comment="结算操作员"),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("details", JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_settlement_store_date", "settlements", ["store_id", "settlement_date"])

    # ---------------------------------------------------------------
    # 5. shift_handovers (交接班)
    # ---------------------------------------------------------------
    op.create_table(
        "shift_handovers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("from_employee_id", sa.String(50), nullable=False),
        sa.Column("to_employee_id", sa.String(50), nullable=False),
        sa.Column("handover_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("orders_count", sa.Integer, server_default="0"),
        sa.Column("revenue_fen", sa.Integer, server_default="0"),
        sa.Column("cash_on_hand_fen", sa.Integer, comment="交接时现金(分)"),
        sa.Column("pending_issues", JSON, comment="待处理事项列表"),
        sa.Column("notes", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # ---------------------------------------------------------------
    # 6. receipt_templates (小票模板)
    # ---------------------------------------------------------------
    op.create_table(
        "receipt_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("template_name", sa.String(100), nullable=False),
        sa.Column("print_type", sa.String(20), nullable=False, server_default="receipt"),
        sa.Column("template_content", sa.Text, nullable=False),
        sa.Column("paper_width", sa.Integer, server_default="58", comment="纸宽mm: 58/80"),
        sa.Column("is_default", sa.Boolean, server_default="false"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("config", JSON, comment="字体/对齐/二维码等配置"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # ---------------------------------------------------------------
    # 7. receipt_logs (打印日志)
    # ---------------------------------------------------------------
    op.create_table(
        "receipt_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("print_type", sa.String(20), nullable=False),
        sa.Column("printer_id", sa.String(50), comment="打印机标识"),
        sa.Column("kitchen_station", sa.String(50), comment="目标档口"),
        sa.Column("content_hash", sa.String(64), comment="内容哈希，防重复打印"),
        sa.Column("printed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("success", sa.Boolean, server_default="true"),
        sa.Column("error_message", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # ---------------------------------------------------------------
    # 8. production_depts (出品部门)
    # ---------------------------------------------------------------
    op.create_table(
        "production_depts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("dept_name", sa.String(50), nullable=False, comment="部门名称"),
        sa.Column("dept_code", sa.String(20), nullable=False, index=True, comment="部门编码"),
        sa.Column("brand_id", UUID(as_uuid=True), nullable=False, index=True, comment="品牌ID"),
        sa.Column("fixed_fee_type", sa.String(30), comment="固定费用类型"),
        sa.Column("sort_order", sa.Integer, server_default="0", comment="排序序号"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # ---------------------------------------------------------------
    # 9. dish_dept_mappings (菜品-出品部门映射)
    # ---------------------------------------------------------------
    op.create_table(
        "dish_dept_mappings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("dish_id", UUID(as_uuid=True), nullable=False, index=True, comment="菜品ID"),
        sa.Column("production_dept_id", UUID(as_uuid=True), sa.ForeignKey("production_depts.id"),
                  nullable=False, index=True),
        sa.Column("printer_id", UUID(as_uuid=True), comment="关联打印机ID"),
        sa.Column("kds_terminal_id", UUID(as_uuid=True), comment="关联KDS终端ID"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # ---------------------------------------------------------------
    # 10. daily_ops_flows (日清日结主流程)
    # ---------------------------------------------------------------
    op.create_table(
        "daily_ops_flows",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("ops_date", sa.Date, nullable=False, index=True),
        sa.Column("status", sa.String(20), server_default="not_started",
                  comment="not_started/in_progress/completed"),
        # 8 节点状态
        sa.Column("e1_open_store", sa.String(20), server_default="pending"),
        sa.Column("e2_cruise", sa.String(20), server_default="pending"),
        sa.Column("e3_exception", sa.String(20), server_default="pending"),
        sa.Column("e4_handover", sa.String(20), server_default="pending"),
        sa.Column("e5_close_check", sa.String(20), server_default="pending"),
        sa.Column("e6_settlement", sa.String(20), server_default="pending"),
        sa.Column("e7_review", sa.String(20), server_default="pending"),
        sa.Column("e8_rectification", sa.String(20), server_default="pending"),
        sa.Column("completed_nodes", sa.Integer, server_default="0"),
        sa.Column("total_nodes", sa.Integer, server_default="8"),
        sa.Column("operator_id", sa.String(50)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_daily_ops_store_date", "daily_ops_flows", ["store_id", "ops_date"], unique=True)

    # ---------------------------------------------------------------
    # 11. daily_ops_nodes (日清日结节点明细)
    # ---------------------------------------------------------------
    op.create_table(
        "daily_ops_nodes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("flow_id", UUID(as_uuid=True), sa.ForeignKey("daily_ops_flows.id"),
                  nullable=False, index=True),
        sa.Column("node_code", sa.String(10), nullable=False, comment="E1-E8"),
        sa.Column("node_name", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending",
                  comment="pending/in_progress/completed/skipped/abnormal"),
        sa.Column("check_items", JSON, comment="[{item, required, checked, result}]"),
        sa.Column("check_result", sa.String(20), comment="pass/fail/partial"),
        sa.Column("photo_urls", JSON),
        sa.Column("operator_id", sa.String(50)),
        sa.Column("operator_name", sa.String(50)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("duration_minutes", sa.Integer),
        sa.Column("notes", sa.Text),
        sa.Column("abnormal_flag", sa.Boolean, server_default="false"),
        sa.Column("abnormal_detail", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # ---------------------------------------------------------------
    # 12. agent_decision_logs (Agent决策日志)
    # ---------------------------------------------------------------
    op.create_table(
        "agent_decision_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("agent_id", sa.String(50), nullable=False, index=True, comment="Agent标识"),
        sa.Column("decision_type", sa.String(100), nullable=False, comment="决策类型"),
        sa.Column("store_id", UUID(as_uuid=True), index=True),
        # 推理链路
        sa.Column("input_context", JSON, nullable=False, comment="输入上下文"),
        sa.Column("reasoning", sa.Text, nullable=False, comment="推理过程"),
        sa.Column("output_action", JSON, nullable=False, comment="输出动作"),
        # 三条硬约束校验
        sa.Column("constraints_check", JSON, nullable=False, comment="三条硬约束校验"),
        # 元数据
        sa.Column("confidence", sa.Float, nullable=False, comment="置信度 0-1"),
        sa.Column("execution_ms", sa.Integer, comment="执行耗时ms"),
        sa.Column("inference_layer", sa.String(20), comment="edge/cloud"),
        sa.Column("model_id", sa.String(100), comment="使用的模型ID"),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_decision_agent_type", "agent_decision_logs", ["agent_id", "decision_type"])

    # ---------------------------------------------------------------
    # Enable RLS on all new tables
    # ---------------------------------------------------------------
    for table in NEW_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    # Disable RLS first
    for table in reversed(NEW_TABLES):
        _disable_rls(table)

    # Drop tables in reverse dependency order
    op.drop_table("agent_decision_logs")
    op.drop_table("daily_ops_nodes")
    op.drop_table("daily_ops_flows")
    op.drop_table("dish_dept_mappings")
    op.drop_table("production_depts")
    op.drop_table("receipt_logs")
    op.drop_table("receipt_templates")
    op.drop_table("shift_handovers")
    op.drop_table("settlements")
    op.drop_table("refunds")
    op.drop_table("payments")
    op.drop_table("tables")
