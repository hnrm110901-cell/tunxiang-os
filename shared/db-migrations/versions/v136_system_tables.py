"""v136 — 系统数据字典 + 操作审计日志 + 功能开关 + 灰度发布

新增六张表：
  sys_dictionaries       — 数据字典（系统级配置、枚举值管理）
  sys_dictionary_items   — 数据字典项
  audit_logs             — 操作审计日志（不可删除）
  feature_flags          — 功能开关
  gray_release_rules     — 灰度发布规则

Revision ID: v136
Revises: v135
Create Date: 2026-04-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v136"
down_revision = "v135"
branch_labels = None
depends_on = None

RLS_TEMPLATE = """
CREATE POLICY tenant_isolation ON {table}
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
"""

TABLES_WITH_RLS = [
    "sys_dictionaries",
    "sys_dictionary_items",
    "audit_logs",
    "feature_flags",
    "gray_release_rules",
]


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── A. sys_dictionaries 数据字典 ────────────────────────────
    if "sys_dictionaries" not in _existing:
        op.create_table(
            "sys_dictionaries",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("dict_code", sa.String(50), nullable=False),
            sa.Column("dict_name", sa.String(100), nullable=False),
            sa.Column("description", sa.Text),
            sa.Column("is_system", sa.Boolean, server_default=sa.text("false"), nullable=False),
            sa.Column("sort_order", sa.Integer, server_default=sa.text("0"), nullable=False),
            sa.Column("is_active", sa.Boolean, server_default=sa.text("true"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='sys_dictionaries' AND (column_name = 'tenant_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_sys_dictionaries_tenant ON sys_dictionaries (tenant_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='sys_dictionaries' AND column_name IN ('tenant_id', 'dict_code')) = 2 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS ix_sys_dictionaries_tenant_code ON sys_dictionaries (tenant_id, dict_code)';
            END IF;
        END $$;
    """)

    # ── A. sys_dictionary_items 数据字典项 ──────────────────────
    if "sys_dictionary_items" not in _existing:
        op.create_table(
            "sys_dictionary_items",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("dict_id", UUID(as_uuid=True), nullable=False),
            sa.Column("item_code", sa.String(50), nullable=False),
            sa.Column("item_name", sa.String(100), nullable=False),
            sa.Column("item_value", sa.String(200)),
            sa.Column("color", sa.String(20)),
            sa.Column("icon", sa.String(50)),
            sa.Column("sort_order", sa.Integer, server_default=sa.text("0"), nullable=False),
            sa.Column("is_active", sa.Boolean, server_default=sa.text("true"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["dict_id"], ["sys_dictionaries.id"], ondelete="CASCADE"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='sys_dictionary_items' AND (column_name = 'tenant_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_sys_dictionary_items_tenant ON sys_dictionary_items (tenant_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='sys_dictionary_items' AND (column_name = 'dict_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_sys_dictionary_items_dict ON sys_dictionary_items (dict_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='sys_dictionary_items' AND column_name IN ('dict_id', 'item_code')) = 2 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS ix_sys_dictionary_items_dict_code ON sys_dictionary_items (dict_id, item_code)';
            END IF;
        END $$;
    """)

    # ── B. audit_logs 操作审计日志 ──────────────────────────────
    if "audit_logs" not in _existing:
        op.create_table(
            "audit_logs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", UUID(as_uuid=True)),
            sa.Column("user_name", sa.String(100)),
            sa.Column("action", sa.String(50), nullable=False),
            sa.Column("resource_type", sa.String(50)),
            sa.Column("resource_id", sa.String(100)),
            sa.Column("changes", JSONB),
            sa.Column("ip_address", sa.String(45)),
            sa.Column("user_agent", sa.Text),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='audit_logs' AND (column_name = 'tenant_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant ON audit_logs (tenant_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='audit_logs' AND column_name IN ('tenant_id', 'action')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_action ON audit_logs (tenant_id, action)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='audit_logs' AND column_name IN ('tenant_id', 'resource_type', 'resource_id')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_resource ON audit_logs (tenant_id, resource_type, resource_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='audit_logs' AND column_name IN ('tenant_id', 'user_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_user ON audit_logs (tenant_id, user_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='audit_logs' AND (column_name = 'created_at')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs (created_at)';
            END IF;
        END $$;
    """)

    # ── C. feature_flags 功能开关 ──────────────────────────────
    if "feature_flags" not in _existing:
        op.create_table(
            "feature_flags",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("flag_code", sa.String(50), nullable=False),
            sa.Column("flag_name", sa.String(100), nullable=False),
            sa.Column("description", sa.Text),
            sa.Column("is_enabled", sa.Boolean, server_default=sa.text("false"), nullable=False),
            sa.Column("scope", sa.String(20), server_default="all", nullable=False),
            sa.Column("scope_config", JSONB),
            sa.Column("tag", sa.String(20)),
            sa.Column("updated_by", sa.String(100)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='feature_flags' AND (column_name = 'tenant_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_feature_flags_tenant ON feature_flags (tenant_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='feature_flags' AND column_name IN ('tenant_id', 'flag_code')) = 2 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS ix_feature_flags_tenant_code ON feature_flags (tenant_id, flag_code)';
            END IF;
        END $$;
    """)

    # ── C. gray_release_rules 灰度发布规则 ─────────────────────
    if "gray_release_rules" not in _existing:
        op.create_table(
            "gray_release_rules",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("flag_id", UUID(as_uuid=True), nullable=False),
            sa.Column("strategy", sa.String(20), nullable=False),
            sa.Column("strategy_config", JSONB),
            sa.Column("progress_pct", sa.Integer, server_default=sa.text("0"), nullable=False),
            sa.Column("status", sa.String(20), server_default="draft", nullable=False),
            sa.Column("start_at", sa.DateTime(timezone=True)),
            sa.Column("end_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["flag_id"], ["feature_flags.id"], ondelete="CASCADE"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='gray_release_rules' AND (column_name = 'tenant_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_gray_release_rules_tenant ON gray_release_rules (tenant_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='gray_release_rules' AND (column_name = 'flag_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_gray_release_rules_flag ON gray_release_rules (flag_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='gray_release_rules' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_gray_release_rules_status ON gray_release_rules (tenant_id, status)';
            END IF;
        END $$;
    """)

    # ── RLS: 所有表启用行级安全 ─────────────────────────────────
    for table in TABLES_WITH_RLS:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(RLS_TEMPLATE.format(table=table))


def downgrade() -> None:
    # ── 先移除 RLS ──────────────────────────────────────────────
    for table in reversed(TABLES_WITH_RLS):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # ── 按依赖反序删表 ─────────────────────────────────────────
    op.drop_table("gray_release_rules")
    op.drop_table("feature_flags")
    op.drop_table("audit_logs")
    op.drop_table("sys_dictionary_items")
    op.drop_table("sys_dictionaries")
