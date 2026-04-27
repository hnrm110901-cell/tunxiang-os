"""v274 — sop_quick_actions（Phase S2: IM全闭环升级）

新建表：
  - sop_quick_actions: IM快捷操作定义（一键确认/拍照上传/标记异常/呼叫支援等）

含种子数据：5条通用快捷操作（不依赖tenant_id）

Revision ID: v274_sop_quick_actions
Revises: v273_sop_im_interactions
Create Date: 2026-04-23
"""
from alembic import op

revision = "v274_sop_quick_actions"
down_revision = "v273_sop_im_interactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── sop_quick_actions ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS sop_quick_actions (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            action_code         TEXT NOT NULL,
            action_name         TEXT NOT NULL,
            action_type         TEXT NOT NULL,
            target_service      TEXT,
            target_endpoint     TEXT,
            payload_template    JSONB,
            requires_photo      BOOLEAN DEFAULT FALSE,
            requires_note       BOOLEAN DEFAULT FALSE,
            is_active           BOOLEAN DEFAULT TRUE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN DEFAULT FALSE
        )
    """)

    # 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sop_quick_actions_tenant_code
            ON sop_quick_actions (tenant_id, action_code)
    """)

    # 唯一约束（软删除友好）
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_sop_quick_actions_tenant_code
            ON sop_quick_actions (tenant_id, action_code)
            WHERE NOT is_deleted
    """)

    # RLS
    op.execute("ALTER TABLE sop_quick_actions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS sop_quick_actions_tenant ON sop_quick_actions"
    )
    op.execute("""
        CREATE POLICY sop_quick_actions_tenant ON sop_quick_actions
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE sop_quick_actions IS
            'Phase S2: IM快捷操作定义 — 卡片上的一键操作按钮配置';
        COMMENT ON COLUMN sop_quick_actions.action_type IS
            '操作类型：confirm / photo / flag / escalate / data_entry';
        COMMENT ON COLUMN sop_quick_actions.target_service IS
            '关联微服务名（如tx-agent、tx-ops等）';
        COMMENT ON COLUMN sop_quick_actions.payload_template IS
            '请求模板 JSON，可包含 {instance_id} 等占位符';
    """)

    # ── 种子数据：通用快捷操作 ──
    # 使用固定UUID作为系统级tenant_id（00000000-0000-0000-0000-000000000000）
    op.execute("""
        INSERT INTO sop_quick_actions
            (tenant_id, action_code, action_name, action_type,
             requires_photo, requires_note)
        VALUES
            ('00000000-0000-0000-0000-000000000000',
             'confirm_task', '一键确认', 'confirm',
             FALSE, FALSE),
            ('00000000-0000-0000-0000-000000000000',
             'photo_check', '拍照确认', 'photo',
             TRUE, FALSE),
            ('00000000-0000-0000-0000-000000000000',
             'flag_issue', '标记异常', 'flag',
             FALSE, TRUE),
            ('00000000-0000-0000-0000-000000000000',
             'call_support', '呼叫支援', 'escalate',
             FALSE, FALSE),
            ('00000000-0000-0000-0000-000000000000',
             'quick_note', '快速备注', 'data_entry',
             FALSE, TRUE)
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS sop_quick_actions_tenant ON sop_quick_actions"
    )
    op.execute(
        "ALTER TABLE IF EXISTS sop_quick_actions DISABLE ROW LEVEL SECURITY"
    )
    op.execute("DROP INDEX IF EXISTS uq_sop_quick_actions_tenant_code")
    op.execute("DROP INDEX IF EXISTS idx_sop_quick_actions_tenant_code")
    op.execute("DROP TABLE IF EXISTS sop_quick_actions")
