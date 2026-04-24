"""v007: Add missing tables from old project gap analysis

Adds 12 core tables identified in docs/migration-analysis.md Section 2.3:

Domain: Menu/BOM (cost truth engine)
  - bom_templates: BOM version master with effective dating
  - bom_items: BOM ingredient line items

Domain: Inventory/Loss (loss prevention Agent)
  - waste_events: Food waste event tracking and root-cause analysis

Domain: Supply Chain
  - suppliers: Supplier master data
  - supply_orders: Purchase orders for ingredient procurement

Domain: CRM/Membership
  - member_transactions: Membership point/credit transaction ledger

Domain: System
  - notifications: Multi-channel notification delivery
  - notification_preferences: Per-user notification channel settings

Domain: HR/Training
  - training_courses: Training course catalog
  - training_enrollments: Employee training enrollment + progress

Domain: Service Quality
  - service_feedbacks: Customer service feedback records
  - complaints: Customer complaint tracking and resolution

Domain: Operations
  - tasks: Operational task management (open/close checklist, etc.)

All tables include:
  - UUID primary key (id)
  - tenant_id UUID NOT NULL + index
  - created_at / updated_at / is_deleted standard fields
  - RLS: ENABLE + FORCE ROW LEVEL SECURITY
  - 4 policies (SELECT/INSERT/UPDATE/DELETE) with IS NOT NULL guard
  - Uses app.tenant_id (consistent with v001-v006)

Revision ID: v007
Revises: v006
Create Date: 2026-03-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSON

revision = "v007"
down_revision= "v006"
branch_labels= None
depends_on= None

# All new tables in this migration
NEW_TABLES = [
    "bom_templates", "bom_items",
    "waste_events",
    "suppliers", "supply_orders",
    "member_transactions",
    "notifications", "notification_preferences",
    "training_courses", "training_enrollments",
    "service_feedbacks", "complaints",
    "tasks",
]

# Safe RLS condition (same as v006)
_SAFE_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def _enable_rls_v7(table_name: str) -> None:
    """Enable RLS with FORCE + 4 safe policies (v006 pattern)."""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")

    op.execute(
        f"CREATE POLICY {table_name}_rls_select ON {table_name} "
        f"FOR SELECT USING ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table_name}_rls_insert ON {table_name} "
        f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table_name}_rls_update ON {table_name} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table_name}_rls_delete ON {table_name} "
        f"FOR DELETE USING ({_SAFE_CONDITION})"
    )


def _disable_rls_v7(table_name: str) -> None:
    """Drop RLS policies and disable RLS (for downgrade)."""
    for op_suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {table_name}_rls_{op_suffix} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # =========================================================================
    # Domain A: Menu/BOM  (cost truth engine)
    # =========================================================================

    # --- bom_templates ---
    op.create_table(
        "bom_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("dish_id", UUID(as_uuid=True), sa.ForeignKey("dishes.id"), nullable=False, index=True),
        sa.Column("version", sa.String(20), nullable=False),
        # Effective dating for time-travel queries
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expiry_date", sa.DateTime(timezone=True), nullable=True),
        # Recipe attributes
        sa.Column("yield_rate", sa.Numeric(5, 4), nullable=False, server_default="1.0"),
        sa.Column("standard_portion", sa.Numeric(8, 3), comment="Standard portion weight (grams)"),
        sa.Column("prep_time_minutes", sa.Integer),
        # Status
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_approved", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("approved_by", sa.String(100)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        # Scope / channel / inheritance
        sa.Column("scope", sa.String(20), nullable=False, server_default="store",
                  comment="store/region/brand/group"),
        sa.Column("scope_id", sa.String(100)),
        sa.Column("channel", sa.String(30), comment="NULL = all channels"),
        sa.Column("parent_bom_id", UUID(as_uuid=True),
                  sa.ForeignKey("bom_templates.id", ondelete="SET NULL")),
        sa.Column("is_delta", sa.Boolean, nullable=False, server_default="false",
                  comment="True=delta BOM, False=full BOM"),
        # Metadata
        sa.Column("notes", sa.Text),
        sa.Column("created_by", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
        sa.UniqueConstraint("dish_id", "version", name="uq_bom_dish_version"),
    )
    op.create_index("idx_bom_active", "bom_templates", ["dish_id", "is_active"])
    op.create_index("idx_bom_effective_date", "bom_templates", ["effective_date"])
    op.create_index("idx_bom_scope", "bom_templates", ["scope"])

    # --- bom_items ---
    op.create_table(
        "bom_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("bom_id", UUID(as_uuid=True),
                  sa.ForeignKey("bom_templates.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        # Ingredient reference (UUID FK to ingredients table)
        sa.Column("ingredient_id", UUID(as_uuid=True), sa.ForeignKey("ingredients.id"), nullable=False, index=True),
        sa.Column("ingredient_master_id", UUID(as_uuid=True), comment="Soft ref to ingredient_masters"),
        # Quantities
        sa.Column("standard_qty", sa.Numeric(10, 4), nullable=False, comment="Standard usage (post-yield)"),
        sa.Column("raw_qty", sa.Numeric(10, 4), comment="Raw material qty (pre-processing)"),
        sa.Column("unit", sa.String(20), nullable=False),
        # Cost snapshot
        sa.Column("unit_cost_fen", sa.Integer, comment="Cost per unit (fen)"),
        # Attributes
        sa.Column("is_key_ingredient", sa.Boolean, server_default="false"),
        sa.Column("is_optional", sa.Boolean, server_default="false"),
        sa.Column("waste_factor", sa.Numeric(5, 4), server_default="0"),
        sa.Column("prep_notes", sa.Text),
        # Delta BOM action
        sa.Column("item_action", sa.String(20), nullable=False, server_default="ADD",
                  comment="ADD/OVERRIDE/REMOVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
        sa.UniqueConstraint("bom_id", "ingredient_id", name="uq_bom_item_ingredient"),
    )

    # =========================================================================
    # Domain B: Inventory / Loss Prevention
    # =========================================================================

    # --- waste_events ---
    op.create_table(
        "waste_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("event_id", sa.String(50), unique=True, nullable=False,
                  comment="WE-XXXXXXXX business ID for cross-system ref"),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        # Event classification
        sa.Column("event_type", sa.String(30), nullable=False, server_default="unknown",
                  comment="cooking_loss/spoilage/over_prep/drop_damage/quality_reject/transfer_loss/unknown"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True,
                  comment="pending/analyzing/analyzed/verified/closed"),
        # Food references
        sa.Column("dish_id", UUID(as_uuid=True), sa.ForeignKey("dishes.id"), index=True),
        sa.Column("ingredient_id", UUID(as_uuid=True), sa.ForeignKey("ingredients.id"), nullable=False, index=True),
        # Quantities
        sa.Column("quantity", sa.Numeric(10, 4), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("theoretical_qty", sa.Numeric(10, 4), comment="BOM theoretical consumption"),
        sa.Column("variance_qty", sa.Numeric(10, 4), comment="actual - theoretical"),
        sa.Column("variance_pct", sa.Float, comment="variance / theoretical"),
        # Timeline
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), index=True),
        # Personnel
        sa.Column("reported_by", sa.String(100)),
        sa.Column("assigned_staff_id", sa.String(100)),
        # AI reasoning output
        sa.Column("root_cause", sa.String(50), comment="staff_error/food_quality/process/equipment/..."),
        sa.Column("confidence", sa.Float),
        sa.Column("evidence", JSON, comment="Reasoning evidence chain snapshot"),
        sa.Column("scores", JSON, comment="Per-dimension scores"),
        # Disposition
        sa.Column("action_taken", sa.Text),
        sa.Column("photo_urls", JSON),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_waste_store_date", "waste_events", ["store_id", "occurred_at"])
    op.create_index("idx_waste_type_status", "waste_events", ["event_type", "status"])

    # =========================================================================
    # Domain C: Supply Chain
    # =========================================================================

    # --- suppliers ---
    op.create_table(
        "suppliers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(50), unique=True, index=True),
        sa.Column("category", sa.String(50), nullable=False, server_default="food",
                  comment="food/beverage/equipment/packaging/other"),
        sa.Column("contact_person", sa.String(100)),
        sa.Column("phone", sa.String(20)),
        sa.Column("email", sa.String(100)),
        sa.Column("address", sa.Text),
        sa.Column("status", sa.String(20), nullable=False, server_default="active",
                  comment="active/inactive/suspended"),
        sa.Column("rating", sa.Float, server_default="5.0", comment="1-5 supplier rating"),
        sa.Column("payment_terms", sa.String(50), server_default="net30",
                  comment="net30/net60/cod"),
        sa.Column("delivery_days", sa.Integer, server_default="3", comment="Average delivery time"),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # --- supply_orders (purchase orders) ---
    op.create_table(
        "supply_orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("order_number", sa.String(50), unique=True, nullable=False, index=True),
        sa.Column("supplier_id", UUID(as_uuid=True), sa.ForeignKey("suppliers.id"), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending",
                  comment="pending/approved/ordered/shipped/delivered/completed/cancelled"),
        sa.Column("total_amount_fen", sa.Integer, server_default="0", comment="Total amount (fen)"),
        sa.Column("items", JSON, server_default="[]",
                  comment='[{"ingredient_id","qty","unit","unit_price_fen"}]'),
        sa.Column("expected_delivery", sa.DateTime(timezone=True)),
        sa.Column("actual_delivery", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text),
        sa.Column("created_by", sa.String(100)),
        sa.Column("approved_by", sa.String(100)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_supply_order_store_status", "supply_orders", ["store_id", "status"])

    # =========================================================================
    # Domain D: CRM / Membership
    # =========================================================================

    # --- member_transactions ---
    op.create_table(
        "member_transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("transaction_type", sa.String(30), nullable=False,
                  comment="earn/redeem/expire/adjust/refund/gift"),
        sa.Column("points", sa.Integer, nullable=False, server_default="0", comment="Points delta (+/-)"),
        sa.Column("balance_after", sa.Integer, comment="Points balance after transaction"),
        sa.Column("amount_fen", sa.Integer, server_default="0",
                  comment="Associated monetary amount (fen)"),
        sa.Column("reference_type", sa.String(30), comment="order/campaign/manual/system"),
        sa.Column("reference_id", sa.String(100), comment="Related order_id / campaign_id"),
        sa.Column("description", sa.String(500)),
        sa.Column("operator_id", sa.String(100), comment="Employee who processed"),
        sa.Column("expired_at", sa.DateTime(timezone=True), comment="Point expiry date"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_member_tx_customer_type", "member_transactions",
                    ["customer_id", "transaction_type"])

    # =========================================================================
    # Domain E: System (Notifications)
    # =========================================================================

    # --- notifications ---
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        # Content
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("type", sa.String(20), nullable=False, server_default="info",
                  comment="info/warning/error/success/alert"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="normal",
                  comment="low/normal/high/urgent"),
        # Recipient targeting
        sa.Column("employee_id", UUID(as_uuid=True), sa.ForeignKey("employees.id"), index=True,
                  comment="Specific employee (NULL=broadcast)"),
        sa.Column("role", sa.String(50), comment="Target role filter"),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), index=True),
        # Status
        sa.Column("is_read", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        # Metadata
        sa.Column("extra_data", JSON, comment="Links, actions, deep-link URLs"),
        sa.Column("source", sa.String(50), comment="Agent name or service that generated"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_notification_employee_read", "notifications", ["employee_id", "is_read"])

    # --- notification_preferences ---
    op.create_table(
        "notification_preferences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("employee_id", UUID(as_uuid=True), sa.ForeignKey("employees.id"),
                  nullable=False, index=True),
        sa.Column("notification_type", sa.String(20), comment="NULL = global default"),
        sa.Column("channels", JSON, nullable=False, server_default="[]",
                  comment='["system","wechat","sms","email"]'),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("quiet_hours_start", sa.String(5), comment="HH:MM e.g. 22:00"),
        sa.Column("quiet_hours_end", sa.String(5), comment="HH:MM e.g. 08:00"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # =========================================================================
    # Domain F: HR / Training
    # =========================================================================

    # --- training_courses ---
    op.create_table(
        "training_courses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("brand_id", sa.String(50), index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), index=True,
                  comment="NULL = brand-wide course"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("category", sa.String(50), nullable=False,
                  comment="safety/service/cooking/management/culture"),
        sa.Column("course_type", sa.String(30), nullable=False, server_default="online",
                  comment="online/offline/practice"),
        sa.Column("applicable_positions", JSON, comment='["waiter","chef","cashier"]'),
        sa.Column("duration_minutes", sa.Integer, nullable=False, server_default="60"),
        sa.Column("content_url", sa.String(500)),
        sa.Column("pass_score", sa.Integer, server_default="60"),
        sa.Column("credits", sa.Integer, server_default="1"),
        sa.Column("is_mandatory", sa.Boolean, server_default="false"),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # --- training_enrollments ---
    op.create_table(
        "training_enrollments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("employee_id", UUID(as_uuid=True), sa.ForeignKey("employees.id"),
                  nullable=False, index=True),
        sa.Column("course_id", UUID(as_uuid=True), sa.ForeignKey("training_courses.id"),
                  nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="enrolled",
                  comment="enrolled/in_progress/completed/failed"),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("progress_pct", sa.Integer, server_default="0", comment="0-100"),
        sa.Column("score", sa.Integer),
        sa.Column("certificate_no", sa.String(50)),
        sa.Column("certified_at", sa.Date),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
        sa.UniqueConstraint("employee_id", "course_id", name="uq_training_enrollment"),
    )

    # =========================================================================
    # Domain G: Service Quality
    # =========================================================================

    # --- service_feedbacks ---
    op.create_table(
        "service_feedbacks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customers.id"), index=True),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), index=True),
        # Ratings
        sa.Column("overall_rating", sa.Integer, nullable=False, comment="1-5 stars"),
        sa.Column("food_rating", sa.Integer, comment="1-5"),
        sa.Column("service_rating", sa.Integer, comment="1-5"),
        sa.Column("environment_rating", sa.Integer, comment="1-5"),
        sa.Column("value_rating", sa.Integer, comment="1-5 price/value"),
        # Content
        sa.Column("comment", sa.Text),
        sa.Column("tags", JSON, comment='["fast_service","delicious","noisy"]'),
        sa.Column("photo_urls", JSON),
        # Source
        sa.Column("source", sa.String(30), nullable=False, server_default="in_store",
                  comment="in_store/wechat/meituan/dianping/douyin"),
        # Processing
        sa.Column("status", sa.String(20), nullable=False, server_default="pending",
                  comment="pending/reviewed/responded/closed"),
        sa.Column("response", sa.Text),
        sa.Column("responded_by", sa.String(100)),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_feedback_store_rating", "service_feedbacks", ["store_id", "overall_rating"])

    # --- complaints ---
    op.create_table(
        "complaints",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customers.id"), index=True),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), index=True),
        # Complaint details
        sa.Column("complaint_no", sa.String(50), unique=True, nullable=False),
        sa.Column("category", sa.String(50), nullable=False,
                  comment="food_quality/service/hygiene/wait_time/billing/other"),
        sa.Column("severity", sa.String(20), nullable=False, server_default="normal",
                  comment="low/normal/high/critical"),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("photo_urls", JSON),
        # Resolution
        sa.Column("status", sa.String(20), nullable=False, server_default="open",
                  comment="open/investigating/resolved/closed/escalated"),
        sa.Column("assigned_to", UUID(as_uuid=True), sa.ForeignKey("employees.id"), index=True),
        sa.Column("resolution", sa.Text),
        sa.Column("compensation_fen", sa.Integer, server_default="0",
                  comment="Compensation amount (fen)"),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", sa.String(100)),
        # Source
        sa.Column("source", sa.String(30), server_default="in_store",
                  comment="in_store/phone/wechat/meituan/12315"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_complaint_store_status", "complaints", ["store_id", "status"])

    # =========================================================================
    # Domain H: Operations (Tasks)
    # =========================================================================

    # --- tasks ---
    op.create_table(
        "tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        # Task info
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.Text),
        sa.Column("category", sa.String(50),
                  comment="opening/closing/hygiene/equipment/inspection/custom"),
        # Status
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True,
                  comment="pending/in_progress/completed/cancelled/overdue"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="normal",
                  comment="low/normal/high/urgent"),
        # People
        sa.Column("creator_id", UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("assignee_id", UUID(as_uuid=True), sa.ForeignKey("employees.id"), index=True),
        # Timeline
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        # Result
        sa.Column("result", sa.Text),
        sa.Column("attachments", JSON, comment="Attachment URL list"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_task_store_status", "tasks", ["store_id", "status"])
    op.create_index("idx_task_assignee", "tasks", ["assignee_id", "status"])

    # =========================================================================
    # Enable RLS on all new tables
    # =========================================================================
    for table in NEW_TABLES:
        _enable_rls_v7(table)


def downgrade() -> None:
    """Drop all v007 tables (reverse order for FK deps)."""
    for table in reversed(NEW_TABLES):
        _disable_rls_v7(table)

    # Drop in reverse dependency order
    op.drop_table("tasks")
    op.drop_table("complaints")
    op.drop_table("service_feedbacks")
    op.drop_table("training_enrollments")
    op.drop_table("training_courses")
    op.drop_table("notification_preferences")
    op.drop_table("notifications")
    op.drop_table("member_transactions")
    op.drop_table("supply_orders")
    op.drop_table("suppliers")
    op.drop_table("waste_events")
    op.drop_table("bom_items")
    op.drop_table("bom_templates")
