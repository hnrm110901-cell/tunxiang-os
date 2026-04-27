"""v313 — 加购推荐话术表: upsell_prompts

AI生成的加购推荐话术，关联触发菜品和推荐菜品：
prompt_text(推荐话术)、prompt_type(场景类型)、conversion/impression统计。
支持A/B测试不同话术效果。

Revision ID: v313_upsell_prompts
Revises: v312_dish_affinity_matrix
Create Date: 2026-04-25
"""
from alembic import op

revision = "v313_upsell_prompts"
down_revision = "v312_dish_affinity_matrix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS upsell_prompts (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID,
            trigger_dish_id     UUID NOT NULL,
            suggest_dish_id     UUID NOT NULL,
            prompt_text         TEXT NOT NULL,
            prompt_type         VARCHAR(30) NOT NULL DEFAULT 'add_on'
                                CHECK (prompt_type IN (
                                    'add_on', 'upgrade', 'combo', 'seasonal', 'popular'
                                )),
            is_enabled          BOOLEAN NOT NULL DEFAULT TRUE,
            conversion_count    INT NOT NULL DEFAULT 0,
            impression_count    INT NOT NULL DEFAULT 0,
            priority            INT NOT NULL DEFAULT 0,
            metadata            JSONB DEFAULT '{}',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_upsell_prompts_trigger
            ON upsell_prompts(tenant_id, trigger_dish_id)
            WHERE is_deleted = false AND is_enabled = true
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_upsell_prompts_suggest
            ON upsell_prompts(tenant_id, suggest_dish_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_upsell_prompts_type
            ON upsell_prompts(tenant_id, prompt_type)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_upsell_prompts_conversion
            ON upsell_prompts(tenant_id, impression_count DESC)
            WHERE is_deleted = false AND impression_count > 0
    """)

    op.execute("ALTER TABLE upsell_prompts ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS upsell_prompts_tenant_isolation ON upsell_prompts;
        CREATE POLICY upsell_prompts_tenant_isolation ON upsell_prompts
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE upsell_prompts FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS upsell_prompts CASCADE")
