"""v008: Add reservation and queue tables for persistent storage

Migrates reservation and queue modules from in-memory dict storage
to PostgreSQL persistent tables.

New tables:
  - reservations: 预订记录（7状态机，包间/定金/爽约支持）
  - no_show_records: 顾客爽约记录
  - queue_entries: 排队叫号记录（6状态机，VIP优先/美团同步）
  - queue_counters: 排队号当日计数器

All tables include:
  - UUID primary key (id)
  - tenant_id UUID NOT NULL + index
  - created_at / updated_at / is_deleted standard fields
  - RLS: ENABLE + FORCE ROW LEVEL SECURITY
  - 4 policies (SELECT/INSERT/UPDATE/DELETE) with IS NOT NULL guard
  - Uses app.tenant_id (consistent with v001-v007)

Revision ID: v008
Revises: v007
Create Date: 2026-03-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision = "v008"
down_revision = "v007"
branch_labels = None
depends_on = None

NEW_TABLES = [
    "reservations",
    "no_show_records",
    "queue_entries",
    "queue_counters",
]

# Safe RLS condition (same as v006/v007)
_SAFE_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def _enable_rls(table_name: str) -> None:
    """Enable RLS with FORCE + 4 safe policies."""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")

    op.execute(f"CREATE POLICY {table_name}_rls_select ON {table_name} FOR SELECT USING ({_SAFE_CONDITION})")
    op.execute(f"CREATE POLICY {table_name}_rls_insert ON {table_name} FOR INSERT WITH CHECK ({_SAFE_CONDITION})")
    op.execute(
        f"CREATE POLICY {table_name}_rls_update ON {table_name} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(f"CREATE POLICY {table_name}_rls_delete ON {table_name} FOR DELETE USING ({_SAFE_CONDITION})")


def _disable_rls(table_name: str) -> None:
    """Drop RLS policies and disable RLS (for downgrade)."""
    for op_suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {table_name}_rls_{op_suffix} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # =========================================================================
    # DROP v004 reservations/queues — schema redesigned for persistent storage
    # v004 used Date/Time types and different column layout;
    # v008 uses String-based dates to match in-memory dict format.
    # Must also drop v006 RLS policies that reference the old tables.
    # =========================================================================
    for old_table in ("queues", "reservations"):
        for op_suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {old_table}_rls_{op_suffix} ON {old_table}")
        op.execute(f"ALTER TABLE {old_table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {old_table} DISABLE ROW LEVEL SECURITY")
        op.drop_table(old_table)

    # =========================================================================
    # reservations — 预订记录 (redesigned)
    # =========================================================================
    op.create_table(
        "reservations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "reservation_id", sa.String(20), unique=True, nullable=False, index=True, comment="业务ID如RSV-XXXXXXXXXXXX"
        ),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("confirmation_code", sa.String(10), nullable=False, comment="6位确认码"),
        sa.Column("customer_name", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False, index=True),
        sa.Column("type", sa.String(20), nullable=False, server_default="regular"),
        sa.Column("date", sa.String(10), nullable=False, comment="YYYY-MM-DD"),
        sa.Column("time", sa.String(5), nullable=False, comment="HH:MM"),
        sa.Column("estimated_end_time", sa.String(5), comment="HH:MM"),
        sa.Column("party_size", sa.Integer, nullable=False),
        # 包间
        sa.Column("room_name", sa.String(50)),
        sa.Column("room_info", JSON, comment="包间详情"),
        # 桌台
        sa.Column("table_no", sa.String(20)),
        # 特殊需求
        sa.Column("special_requests", sa.String(500)),
        # 定金
        sa.Column("deposit_required", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("deposit_amount_fen", sa.Integer, server_default="0", comment="定金(分)"),
        sa.Column("deposit_paid", sa.Boolean, nullable=False, server_default="false"),
        # 关联
        sa.Column("consumer_id", sa.String(50), comment="会员ID"),
        sa.Column("queue_id", sa.String(20), comment="关联排队ID"),
        sa.Column("order_id", sa.String(50), comment="关联订单ID"),
        # 状态
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("confirmed_by", sa.String(100)),
        sa.Column("cancel_reason", sa.String(500)),
        sa.Column("cancel_fee_fen", sa.Integer, server_default="0", comment="取消手续费(分)"),
        sa.Column("no_show_recorded", sa.Boolean, nullable=False, server_default="false"),
        # 时间线
        sa.Column("arrived_at", sa.String(50)),
        sa.Column("seated_at", sa.String(50)),
        sa.Column("completed_at", sa.String(50)),
        sa.Column("cancelled_at", sa.String(50)),
        # 标准字段
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_reservation_store_date", "reservations", ["store_id", "date"])
    op.create_index("idx_reservation_store_status", "reservations", ["store_id", "status"])

    # =========================================================================
    # no_show_records — 爽约记录
    # =========================================================================
    op.create_table(
        "no_show_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("phone", sa.String(20), nullable=False, index=True),
        sa.Column("reservation_id", sa.String(20), nullable=False, comment="关联预订业务ID"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_no_show_phone", "no_show_records", ["phone"])

    # =========================================================================
    # queue_entries — 排队叫号记录
    # =========================================================================
    op.create_table(
        "queue_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("queue_id", sa.String(20), unique=True, nullable=False, index=True, comment="业务ID如Q-XXXXXXXXXXXX"),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("queue_number", sa.String(10), nullable=False, comment="排队号如A001"),
        sa.Column("prefix", sa.String(1), nullable=False, comment="桌型前缀A/B/C"),
        sa.Column("seq", sa.Integer, nullable=False, comment="序号"),
        sa.Column("customer_name", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False, index=True),
        sa.Column("party_size", sa.Integer, nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="walk_in"),
        sa.Column("vip_priority", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("reservation_id", sa.String(20), comment="关联预订业务ID"),
        sa.Column("status", sa.String(20), nullable=False, server_default="waiting", index=True),
        sa.Column("priority_ts", sa.String(50), nullable=False, comment="优先级时间戳(VIP前移)"),
        # 时间线
        sa.Column("taken_at", sa.String(50), nullable=False),
        sa.Column("called_at", sa.String(50)),
        sa.Column("arrived_at", sa.String(50)),
        sa.Column("seated_at", sa.String(50)),
        sa.Column("skipped_at", sa.String(50)),
        sa.Column("cancelled_at", sa.String(50)),
        # 桌台
        sa.Column("table_no", sa.String(20)),
        # 原因
        sa.Column("skip_reason", sa.String(200)),
        sa.Column("cancel_reason", sa.String(200)),
        # 通知
        sa.Column("notification_count", sa.Integer, server_default="0"),
        # 日期
        sa.Column("date", sa.String(10), nullable=False, comment="YYYY-MM-DD"),
        # 标准字段
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_queue_store_date", "queue_entries", ["store_id", "date"])
    op.create_index("idx_queue_store_status", "queue_entries", ["store_id", "status"])
    op.create_index("idx_queue_store_date_prefix", "queue_entries", ["store_id", "date", "prefix"])

    # =========================================================================
    # queue_counters — 排队号当日计数器
    # =========================================================================
    op.create_table(
        "queue_counters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("date", sa.String(10), nullable=False, comment="YYYY-MM-DD"),
        sa.Column("prefix", sa.String(1), nullable=False, comment="A/B/C"),
        sa.Column("last_number", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    # 修复: 唯一约束必须包含 tenant_id，否则不同租户的计数器会冲突
    op.create_index("uq_queue_counter", "queue_counters", ["tenant_id", "store_id", "date", "prefix"], unique=True)

    # =========================================================================
    # Enable RLS on all new tables
    # =========================================================================
    for table in NEW_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    """Drop all v008 tables and restore v004 reservations/queues."""
    for table in reversed(NEW_TABLES):
        _disable_rls(table)

    op.drop_table("queue_counters")
    op.drop_table("queue_entries")
    op.drop_table("no_show_records")
    op.drop_table("reservations")

    # Restore v004 reservations table (original schema)
    op.create_table(
        "reservations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("confirmation_code", sa.String(16), nullable=False),
        sa.Column("customer_name", sa.String(128), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("time", sa.Time, nullable=False),
        sa.Column("party_size", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # Restore v004 queues table (original schema)
    op.create_table(
        "queues",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("queue_number", sa.String(16), nullable=False),
        sa.Column("customer_name", sa.String(128), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("party_size", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="waiting"),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # Re-apply v006-style RLS on restored tables
    _safe = (
        "current_setting('app.tenant_id', TRUE) IS NOT NULL "
        "AND current_setting('app.tenant_id', TRUE) <> '' "
        "AND tenant_id = current_setting('app.tenant_id')::UUID"
    )
    for tbl in ("reservations", "queues"):
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {tbl}_rls_select ON {tbl} FOR SELECT USING ({_safe})")
        op.execute(f"CREATE POLICY {tbl}_rls_insert ON {tbl} FOR INSERT WITH CHECK ({_safe})")
        op.execute(f"CREATE POLICY {tbl}_rls_update ON {tbl} FOR UPDATE USING ({_safe}) WITH CHECK ({_safe})")
        op.execute(f"CREATE POLICY {tbl}_rls_delete ON {tbl} FOR DELETE USING ({_safe})")
