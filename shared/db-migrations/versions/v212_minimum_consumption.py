"""最低消费规则引擎表

变更：
  minimum_consumption_configs — 门店最低消费规则配置（含rules JSONB、waive_conditions JSONB）
  minimum_consumption_surcharges — 最低消费补齐记录（关联 dining_session）

Revision: v212
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v212"
down_revision = "v211"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── 规则配置表 ───
    op.create_table(
        "minimum_consumption_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False,
                  comment="门店ID"),
        sa.Column("rules", postgresql.JSONB, nullable=False, server_default="[]",
                  comment="规则列表 [{type, room_type, min_amount_fen, surcharge_mode, ...}]"),
        sa.Column("waive_conditions", postgresql.JSONB, nullable=False,
                  server_default="{}",
                  comment="豁免条件 {vip_level_gte, group_size_gte}"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean, nullable=False,
                  server_default="false"),
    )
    op.create_index(
        "ix_min_consume_cfg_tenant_store",
        "minimum_consumption_configs",
        ["tenant_id", "store_id"],
        unique=True,
    )

    # ─── RLS ───
    op.execute("""
        ALTER TABLE minimum_consumption_configs ENABLE ROW LEVEL SECURITY;
    """)
    op.execute("""
        CREATE POLICY minimum_consumption_configs_tenant_isolation
        ON minimum_consumption_configs
        USING (tenant_id::text = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ─── 补齐记录表 ───
    op.create_table(
        "minimum_consumption_surcharges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dining_session_id", postgresql.UUID(as_uuid=True), nullable=False,
                  comment="关联堂食会话"),
        sa.Column("rule_type", sa.VARCHAR(30), nullable=False,
                  comment="触发的规则类型: room/per_person/time_based"),
        sa.Column("min_amount_fen", sa.BigInteger, nullable=False,
                  comment="最低消费要求（分）"),
        sa.Column("actual_amount_fen", sa.BigInteger, nullable=False,
                  comment="实际消费金额（分）"),
        sa.Column("surcharge_fen", sa.BigInteger, nullable=False,
                  comment="补齐金额（分）= min - actual"),
        sa.Column("waived", sa.Boolean, nullable=False, server_default="false",
                  comment="是否被豁免"),
        sa.Column("waive_reason", sa.VARCHAR(200), nullable=True,
                  comment="豁免原因"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean, nullable=False,
                  server_default="false"),
    )
    op.create_index(
        "ix_min_consume_surcharge_tenant_store",
        "minimum_consumption_surcharges",
        ["tenant_id", "store_id"],
    )
    op.create_index(
        "ix_min_consume_surcharge_session",
        "minimum_consumption_surcharges",
        ["dining_session_id"],
    )

    # ─── RLS ───
    op.execute("""
        ALTER TABLE minimum_consumption_surcharges ENABLE ROW LEVEL SECURITY;
    """)
    op.execute("""
        CREATE POLICY minimum_consumption_surcharges_tenant_isolation
        ON minimum_consumption_surcharges
        USING (tenant_id::text = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS minimum_consumption_surcharges_tenant_isolation ON minimum_consumption_surcharges")
    op.drop_table("minimum_consumption_surcharges")
    op.execute("DROP POLICY IF EXISTS minimum_consumption_configs_tenant_isolation ON minimum_consumption_configs")
    op.drop_table("minimum_consumption_configs")
