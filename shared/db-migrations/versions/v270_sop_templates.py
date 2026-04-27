"""v270 — sop_templates + sop_time_slots（Phase S1: SOP时间轴引擎）

新建两张表：
  - sop_templates: SOP模板（品牌级定义，按业态区分）
  - sop_time_slots: 时段定义（每个模板的时间段划分）

Revision ID: v270_sop_templates
Revises: v269_mem_history
Create Date: 2026-04-23
"""
from alembic import op

revision = "v270_sop_templates"
down_revision = "v269_mem_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── sop_templates ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS sop_templates (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            template_name   TEXT NOT NULL,
            store_format    TEXT NOT NULL,
            is_default      BOOLEAN DEFAULT FALSE,
            version         INT DEFAULT 1,
            description     TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        )
    """)

    # 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sop_templates_tenant_format
            ON sop_templates (tenant_id, store_format)
    """)

    # 唯一约束（软删除友好）
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_sop_templates_tenant_name_ver
            ON sop_templates (tenant_id, template_name, version)
            WHERE NOT is_deleted
    """)

    # RLS
    op.execute("ALTER TABLE sop_templates ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sop_templates_tenant ON sop_templates")
    op.execute("""
        CREATE POLICY sop_templates_tenant ON sop_templates
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE sop_templates IS
            'Phase S1: SOP模板 — 品牌级定义，按业态(full_service/qsr/hotpot/bakery)区分';
        COMMENT ON COLUMN sop_templates.store_format IS
            '业态：full_service / qsr / hotpot / bakery';
    """)

    # ── sop_time_slots ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS sop_time_slots (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            template_id     UUID NOT NULL REFERENCES sop_templates(id),
            slot_code       TEXT NOT NULL,
            slot_name       TEXT NOT NULL,
            start_time      TIME WITHOUT TIME ZONE NOT NULL,
            end_time        TIME WITHOUT TIME ZONE NOT NULL,
            sort_order      INT NOT NULL,
            is_active       BOOLEAN DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        )
    """)

    # 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sop_time_slots_template_sort
            ON sop_time_slots (template_id, sort_order)
    """)

    # 唯一约束（软删除友好）
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_sop_time_slots_tenant_tpl_code
            ON sop_time_slots (tenant_id, template_id, slot_code)
            WHERE NOT is_deleted
    """)

    # RLS
    op.execute("ALTER TABLE sop_time_slots ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sop_time_slots_tenant ON sop_time_slots")
    op.execute("""
        CREATE POLICY sop_time_slots_tenant ON sop_time_slots
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE sop_time_slots IS
            'Phase S1: SOP时段定义 — 模板级时间段划分';
        COMMENT ON COLUMN sop_time_slots.slot_code IS
            '时段代码：morning_prep / morning_brief / lunch_buildup / lunch_peak / afternoon_lull / dinner_buildup / dinner_peak / closing';
    """)


def downgrade() -> None:
    # sop_time_slots
    op.execute("DROP POLICY IF EXISTS sop_time_slots_tenant ON sop_time_slots")
    op.execute("ALTER TABLE IF EXISTS sop_time_slots DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS uq_sop_time_slots_tenant_tpl_code")
    op.execute("DROP INDEX IF EXISTS idx_sop_time_slots_template_sort")
    op.execute("DROP TABLE IF EXISTS sop_time_slots")

    # sop_templates
    op.execute("DROP POLICY IF EXISTS sop_templates_tenant ON sop_templates")
    op.execute("ALTER TABLE IF EXISTS sop_templates DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS uq_sop_templates_tenant_name_ver")
    op.execute("DROP INDEX IF EXISTS idx_sop_templates_tenant_format")
    op.execute("DROP TABLE IF EXISTS sop_templates")
