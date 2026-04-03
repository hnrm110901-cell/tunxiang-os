"""v052 — 过敏原管理

新增表：
  dish_allergens  — 菜品过敏原标签（关联菜品与14种中国餐饮常见过敏原）

修改表：
  members         — 新增 allergens JSONB + diet_notes TEXT

支持的过敏原代码（中国餐饮场景）：
  peanut(花生), shellfish(贝壳海鲜), fish(鱼), egg(鸡蛋), milk(牛奶),
  soy(大豆), wheat(小麦/面筋), sesame(芝麻), tree_nut(坚果),
  pork(猪肉), beef(牛肉), spicy(辣), msg(味精), sulfite(亚硫酸盐)

RLS 策略：
  标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v052
Revises: v047
Create Date: 2026-03-31
"""

from alembic import op

revision = "v052"
down_revision = "v047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. members 表：新增 allergens + diet_notes 字段
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE members
            ADD COLUMN IF NOT EXISTS allergens  JSONB NOT NULL DEFAULT '[]',
            ADD COLUMN IF NOT EXISTS diet_notes TEXT  DEFAULT NULL;

        COMMENT ON COLUMN members.allergens   IS '过敏原代码列表，格式：["peanut","shellfish","spicy"]';
        COMMENT ON COLUMN members.diet_notes  IS '自由文字忌口备注，如：少盐、不加香菜';
    """)

    # ─────────────────────────────────────────────────────────────────
    # 2. dish_allergens — 菜品过敏原标签表
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS dish_allergens (
            id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID        NOT NULL,
            dish_id        UUID        NOT NULL,
            allergen_code  VARCHAR(50) NOT NULL,
            allergen_label VARCHAR(100) NOT NULL,
            is_deleted     BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT uq_dish_allergen UNIQUE (tenant_id, dish_id, allergen_code)
        );

        COMMENT ON TABLE  dish_allergens               IS '菜品过敏原标签，多对多关系';
        COMMENT ON COLUMN dish_allergens.allergen_code  IS '过敏原代码，见迁移文件头部说明';
        COMMENT ON COLUMN dish_allergens.allergen_label IS '中文显示名，如：花生、贝壳海鲜';

        CREATE INDEX IF NOT EXISTS idx_dish_allergens_tenant_dish
            ON dish_allergens (tenant_id, dish_id)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS idx_dish_allergens_tenant_code
            ON dish_allergens (tenant_id, allergen_code)
            WHERE is_deleted = FALSE;
    """)

    # ─────────────────────────────────────────────────────────────────
    # 3. dish_allergens RLS — 标准安全模式
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE dish_allergens ENABLE ROW LEVEL SECURITY;
        ALTER TABLE dish_allergens FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS dish_allergens_select ON dish_allergens;
        DROP POLICY IF EXISTS dish_allergens_insert ON dish_allergens;
        DROP POLICY IF EXISTS dish_allergens_update ON dish_allergens;
        DROP POLICY IF EXISTS dish_allergens_delete ON dish_allergens;

        CREATE POLICY dish_allergens_select ON dish_allergens
            FOR SELECT
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            );

        CREATE POLICY dish_allergens_insert ON dish_allergens
            FOR INSERT
            WITH CHECK (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            );

        CREATE POLICY dish_allergens_update ON dish_allergens
            FOR UPDATE
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            );

        CREATE POLICY dish_allergens_delete ON dish_allergens
            FOR DELETE
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            );
    """)


def downgrade() -> None:
    op.execute("""
        DROP POLICY IF EXISTS dish_allergens_delete ON dish_allergens;
        DROP POLICY IF EXISTS dish_allergens_update ON dish_allergens;
        DROP POLICY IF EXISTS dish_allergens_insert ON dish_allergens;
        DROP POLICY IF EXISTS dish_allergens_select ON dish_allergens;
        DROP TABLE IF EXISTS dish_allergens;

        ALTER TABLE members
            DROP COLUMN IF EXISTS allergens,
            DROP COLUMN IF EXISTS diet_notes;
    """)
