"""v004: Reservation, Queue, and Banquet tables for Sprint 3

New tables:
- reservations: 7-status reservation lifecycle with room/table allocation
- queues: 6-status queue management with estimated wait times
- banquet_halls: hall types, capacity, rental, equipment
- banquet_leads: 13-stage pipeline with followup records
- banquet_orders: linked to lead + hall + menu package
- banquet_contracts: contract_no, terms, deposit tracking
- menu_packages: per-table/per-person pricing with items
- banquet_checklists: T-7 to T+1 execution checklist items

Revision ID: v004
Revises: v003
Create Date: 2026-03-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision = "v004"
down_revision = "v003"
branch_labels = None
depends_on = None

NEW_TABLES = [
    "reservations",
    "queues",
    "banquet_halls",
    "banquet_leads",
    "banquet_orders",
    "banquet_contracts",
    "menu_packages",
    "banquet_checklists",
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
    # 1. reservations — 预订记录
    # ---------------------------------------------------------------
    op.create_table(
        "reservations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("confirmation_code", sa.String(16), nullable=False),
        sa.Column("customer_name", sa.String(128), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("consumer_id", UUID(as_uuid=True), nullable=True, comment="关联会员ID"),
        sa.Column("type", sa.String(32), nullable=False, comment="regular/banquet/private_room/outdoor/vip"),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("time", sa.Time, nullable=False),
        sa.Column("estimated_end_time", sa.Time, nullable=True),
        sa.Column("party_size", sa.Integer, nullable=False),
        sa.Column("room_name", sa.String(64), nullable=True),
        sa.Column("room_info", JSON, nullable=True),
        sa.Column("table_no", sa.String(32), nullable=True),
        sa.Column("special_requests", sa.Text, nullable=True),
        sa.Column("deposit_required", sa.Boolean, server_default="false"),
        sa.Column("deposit_amount_fen", sa.BigInteger, server_default="0"),
        sa.Column("deposit_paid", sa.Boolean, server_default="false"),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
            comment="pending/confirmed/arrived/queuing/seated/completed/cancelled/no_show",
        ),
        sa.Column("queue_id", UUID(as_uuid=True), nullable=True),
        sa.Column("order_id", UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_by", sa.String(64), nullable=True),
        sa.Column("cancel_reason", sa.Text, nullable=True),
        sa.Column("cancel_fee_fen", sa.BigInteger, server_default="0"),
        sa.Column("no_show_recorded", sa.Boolean, server_default="false"),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_reservations_store_date", "reservations", ["store_id", "date"])
    op.create_index("ix_reservations_phone", "reservations", ["phone"])
    op.create_index("ix_reservations_status", "reservations", ["status"])
    op.create_index("ix_reservations_confirmation_code", "reservations", ["confirmation_code"], unique=True)

    # ---------------------------------------------------------------
    # 2. queues — 排队叫号记录
    # ---------------------------------------------------------------
    op.create_table(
        "queues",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("queue_number", sa.String(16), nullable=False, comment="如 A001, B003"),
        sa.Column("prefix", sa.String(4), nullable=False, comment="A=小桌/B=中桌/C=大桌"),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("customer_name", sa.String(128), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("party_size", sa.Integer, nullable=False),
        sa.Column(
            "source",
            sa.String(32),
            nullable=False,
            server_default="walk_in",
            comment="walk_in/meituan/reservation/wechat",
        ),
        sa.Column("vip_priority", sa.Boolean, server_default="false"),
        sa.Column("reservation_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="waiting",
            comment="waiting/called/arrived/seated/skipped/cancelled",
        ),
        sa.Column("priority_ts", sa.DateTime(timezone=True), nullable=False, comment="排序用优先级时间戳"),
        sa.Column("table_no", sa.String(32), nullable=True),
        sa.Column("skip_reason", sa.String(64), nullable=True),
        sa.Column("cancel_reason", sa.String(256), nullable=True),
        sa.Column("notification_count", sa.Integer, server_default="0"),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_queues_store_date", "queues", ["store_id", "date"])
    op.create_index("ix_queues_store_date_status", "queues", ["store_id", "date", "status"])
    op.create_index("ix_queues_phone_date", "queues", ["phone", "date"])

    # ---------------------------------------------------------------
    # 3. banquet_halls — 宴会厅
    # ---------------------------------------------------------------
    op.create_table(
        "banquet_halls",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("hall_name", sa.String(64), nullable=False),
        sa.Column(
            "hall_type", sa.String(32), nullable=False, comment="small_hall/medium_hall/large_hall/vip_room/outdoor"
        ),
        sa.Column("capacity_min", sa.Integer, nullable=False),
        sa.Column("capacity_max", sa.Integer, nullable=False),
        sa.Column("table_capacity", sa.Integer, nullable=False, comment="最大桌数"),
        sa.Column("rental_fen", sa.BigInteger, nullable=False, comment="场地租金(分)"),
        sa.Column("equipment", JSON, nullable=True, comment='设备列表如 ["LED屏","音响"]'),
        sa.Column("features", JSON, nullable=True, comment="特色设施"),
        sa.Column("photos", JSON, nullable=True, comment="场地照片URL"),
        sa.Column("status", sa.String(20), server_default="active", comment="active/maintenance/closed"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_banquet_halls_store", "banquet_halls", ["store_id"])

    # ---------------------------------------------------------------
    # 4. banquet_leads — 宴会线索（13阶段流水线）
    # ---------------------------------------------------------------
    op.create_table(
        "banquet_leads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("customer_name", sa.String(128), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("estimated_tables", sa.Integer, nullable=False),
        sa.Column("estimated_guests", sa.Integer, nullable=False),
        sa.Column("estimated_budget_fen", sa.BigInteger, nullable=False),
        sa.Column("estimated_per_table_fen", sa.BigInteger, nullable=False),
        sa.Column("event_date", sa.Date, nullable=False),
        sa.Column("special_requirements", sa.Text, nullable=True),
        sa.Column("referral_source", sa.String(32), server_default="walk_in"),
        sa.Column(
            "stage",
            sa.String(32),
            nullable=False,
            server_default="lead",
            comment="lead/consultation/proposal/quotation/contract/deposit_paid/menu_confirmed/"
            "preparation/rehearsal/execution/settlement/feedback/archived/cancelled",
        ),
        sa.Column("assigned_sales", sa.String(64), nullable=True),
        sa.Column("proposal_id", UUID(as_uuid=True), nullable=True),
        sa.Column("quotation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("contract_id", UUID(as_uuid=True), nullable=True),
        sa.Column("stage_history", JSON, nullable=True, comment="阶段变更历史"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_banquet_leads_store_stage", "banquet_leads", ["store_id", "stage"])
    op.create_index("ix_banquet_leads_event_date", "banquet_leads", ["event_date"])
    op.create_index("ix_banquet_leads_phone", "banquet_leads", ["phone"])

    # ---------------------------------------------------------------
    # 5. banquet_orders — 宴会订单
    # ---------------------------------------------------------------
    op.create_table(
        "banquet_orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), nullable=False),
        sa.Column("contract_id", UUID(as_uuid=True), nullable=True),
        sa.Column("hall_id", UUID(as_uuid=True), nullable=True),
        sa.Column("menu_package_id", UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("event_date", sa.Date, nullable=False),
        sa.Column("guest_count", sa.Integer, nullable=False),
        sa.Column("table_count", sa.Integer, nullable=False),
        sa.Column("menu_items", JSON, nullable=True),
        sa.Column("venue_info", JSON, nullable=True),
        sa.Column("decoration_info", JSON, nullable=True),
        sa.Column("service_plan", JSON, nullable=True),
        sa.Column("total_fen", sa.BigInteger, nullable=False),
        sa.Column("deposit_fen", sa.BigInteger, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_banquet_orders_store_date", "banquet_orders", ["store_id", "event_date"])
    op.create_index("ix_banquet_orders_lead", "banquet_orders", ["lead_id"])

    # ---------------------------------------------------------------
    # 6. banquet_contracts — 宴会合同
    # ---------------------------------------------------------------
    op.create_table(
        "banquet_contracts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("contract_no", sa.String(64), nullable=False, unique=True),
        sa.Column("lead_id", UUID(as_uuid=True), nullable=False),
        sa.Column("quotation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("customer_name", sa.String(128), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("event_date", sa.Date, nullable=False),
        sa.Column("guest_count", sa.Integer, nullable=False),
        sa.Column("table_count", sa.Integer, nullable=False),
        sa.Column("contracted_total_fen", sa.BigInteger, nullable=False),
        sa.Column("deposit_rate", sa.Float, nullable=False),
        sa.Column("deposit_required_fen", sa.BigInteger, nullable=False),
        sa.Column("deposit_paid_fen", sa.BigInteger, server_default="0"),
        sa.Column("deposit_paid", sa.Boolean, server_default="false"),
        sa.Column("terms", JSON, nullable=False, comment="合同条款"),
        sa.Column("menu_items", JSON, nullable=True),
        sa.Column("final_menu_items", JSON, nullable=True),
        sa.Column("menu_confirmed", sa.Boolean, server_default="false"),
        sa.Column("hall_locked", sa.Boolean, server_default="false"),
        sa.Column("settlement", JSON, nullable=True, comment="结算明细"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active", comment="active/settled/cancelled"),
        sa.Column("stage", sa.String(32), nullable=False, server_default="contract"),
        sa.Column("execution_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feedback_id", UUID(as_uuid=True), nullable=True),
        sa.Column("case_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_banquet_contracts_store", "banquet_contracts", ["store_id"])
    op.create_index("ix_banquet_contracts_event_date", "banquet_contracts", ["event_date"])
    op.create_index("ix_banquet_contracts_no", "banquet_contracts", ["contract_no"], unique=True)

    # ---------------------------------------------------------------
    # 7. menu_packages — 宴会菜单套餐
    # ---------------------------------------------------------------
    op.create_table(
        "menu_packages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("package_name", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False, comment="economy/standard/premium"),
        sa.Column("pricing_mode", sa.String(20), nullable=False, comment="per_table/per_person"),
        sa.Column("price_per_unit_fen", sa.BigInteger, nullable=False),
        sa.Column("course_count", sa.Integer, nullable=False),
        sa.Column("items", JSON, nullable=False, comment="菜品列表"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("min_tables", sa.Integer, server_default="1"),
        sa.Column("max_tables", sa.Integer, server_default="100"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_menu_packages_store_type", "menu_packages", ["store_id", "event_type"])

    # ---------------------------------------------------------------
    # 8. banquet_checklists — 宴会筹备检查清单
    # ---------------------------------------------------------------
    op.create_table(
        "banquet_checklists",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("contract_id", UUID(as_uuid=True), nullable=False),
        sa.Column("phase", sa.String(8), nullable=False, comment="T-7/T-3/T-1/T-0/T+1"),
        sa.Column("phase_name", sa.String(32), nullable=False),
        sa.Column("due_offset_days", sa.Integer, nullable=False, comment="相对宴会日偏移天数"),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("task", sa.Text, nullable=False),
        sa.Column("responsible", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
            comment="pending/in_progress/completed/skipped",
        ),
        sa.Column("required", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_banquet_checklists_contract", "banquet_checklists", ["contract_id"])
    op.create_index("ix_banquet_checklists_contract_phase", "banquet_checklists", ["contract_id", "phase"])

    # ---------------------------------------------------------------
    # Enable RLS on all new tables
    # ---------------------------------------------------------------
    for table in NEW_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        _disable_rls(table)
        op.drop_table(table)
