"""预测结果驱动排班 + 采购联动表

Revision: v219
Down: v218
Tables:
  - smart_schedules            AI排班建议主表
  - smart_schedule_slots       排班时段明细
  - smart_procurement_suggestions  AI采购建议
  - smart_procurement_orders   AI采购订单（一键下单）
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v219"
down_revision = "v218"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    # ── AI排班建议主表 ──

    if "smart_schedules" not in existing:
        op.create_table(
            "smart_schedules",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("schedule_date", sa.Date, nullable=False, comment="排班日期"),
            sa.Column("status", sa.VARCHAR(20), server_default="draft", comment="draft/applied/expired"),
            sa.Column("source", sa.VARCHAR(30), server_default="ai_suggested", comment="ai_suggested/manual"),
            sa.Column("total_labor_cost_fen", sa.BigInteger, server_default="0", comment="预估人力成本（分）"),
            sa.Column("predicted_traffic", sa.Integer, server_default="0", comment="预测客流人数"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
            sa.Column("is_deleted", sa.Boolean, server_default="FALSE"),
        )
        op.create_index(
            "ix_smart_schedules_tenant_store_date", "smart_schedules", ["tenant_id", "store_id", "schedule_date"]
        )

        # ── 排班时段明细 ──

    if "smart_schedule_slots" not in existing:
        op.create_table(
            "smart_schedule_slots",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=False, comment="关联 smart_schedules.id"),
            sa.Column("time_slot", sa.VARCHAR(20), nullable=False, comment="时段，如 09:00-11:00"),
            sa.Column("predicted_traffic", sa.Integer, server_default="0", comment="该时段预测客流"),
            sa.Column("required_headcount", sa.Integer, server_default="1", comment="需要人数"),
            sa.Column(
                "assigned_employee_ids",
                postgresql.JSONB,
                server_default=sa.text("'[]'::jsonb"),
                comment="推荐员工ID列表",
            ),
            sa.Column("labor_cost_fen", sa.BigInteger, server_default="0", comment="该时段人力成本（分）"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
            sa.Column("is_deleted", sa.Boolean, server_default="FALSE"),
        )
        op.create_index("ix_smart_schedule_slots_schedule", "smart_schedule_slots", ["schedule_id"])

        # ── AI采购建议 ──

    if "smart_procurement_suggestions" not in existing:
        op.create_table(
            "smart_procurement_suggestions",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("ingredient_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("ingredient_name", sa.VARCHAR(200), server_default=""),
            sa.Column("predicted_demand", sa.Numeric(12, 4), server_default="0", comment="预测需求量"),
            sa.Column("current_stock", sa.Numeric(12, 4), server_default="0", comment="当前库存"),
            sa.Column("safety_stock", sa.Numeric(12, 4), server_default="0", comment="安全库存"),
            sa.Column("suggested_qty", sa.Numeric(12, 4), nullable=False, comment="建议采购量"),
            sa.Column("unit", sa.VARCHAR(20), server_default="kg"),
            sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("supplier_name", sa.VARCHAR(200), server_default=""),
            sa.Column("estimated_cost_fen", sa.BigInteger, server_default="0", comment="预估金额（分）"),
            sa.Column("days_ahead", sa.Integer, server_default="3"),
            sa.Column("status", sa.VARCHAR(20), server_default="draft", comment="draft/ordered/expired"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
            sa.Column("is_deleted", sa.Boolean, server_default="FALSE"),
        )
        op.create_index(
            "ix_smart_procurement_suggestions_tenant_store", "smart_procurement_suggestions", ["tenant_id", "store_id"]
        )

        # ── AI采购订单 ──

    if "smart_procurement_orders" not in existing:
        op.create_table(
            "smart_procurement_orders",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "suggestion_ids", postgresql.JSONB, server_default=sa.text("'[]'::jsonb"), comment="来源建议ID列表"
            ),
            sa.Column("order_no", sa.VARCHAR(50), nullable=False, comment="采购单号 SP-YYYYMMDD-XXXX"),
            sa.Column("total_amount_fen", sa.BigInteger, server_default="0"),
            sa.Column("item_count", sa.Integer, server_default="0"),
            sa.Column(
                "status", sa.VARCHAR(20), server_default="pending", comment="pending/approved/completed/cancelled"
            ),
            sa.Column("source", sa.VARCHAR(30), server_default="ai_suggested"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
            sa.Column("is_deleted", sa.Boolean, server_default="FALSE"),
        )
        op.create_index(
            "ix_smart_procurement_orders_tenant_store", "smart_procurement_orders", ["tenant_id", "store_id"]
        )

        # ── RLS 策略 ──
        for tbl in (
            "smart_schedules",
            "smart_schedule_slots",
            "smart_procurement_suggestions",
            "smart_procurement_orders",
        ):
            op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
            op.execute(f"""
                CREATE POLICY {tbl}_tenant_isolation ON {tbl}
                USING (tenant_id::text = current_setting('app.tenant_id', TRUE))
            """)


def downgrade() -> None:
    for tbl in ("smart_procurement_orders", "smart_procurement_suggestions", "smart_schedule_slots", "smart_schedules"):
        op.drop_table(tbl)
