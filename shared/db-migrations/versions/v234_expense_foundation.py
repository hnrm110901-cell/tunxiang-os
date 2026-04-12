"""v234 — 费控基础：费用科目树 + 申请场景预置

费控系统 P0-S1 基础层：
  - expense_categories  费用科目表（支持多级树形结构，含系统预置科目保护）
  - expense_scenarios   申请场景表（差旅/餐饮/采购等，预置默认科目和必填字段）

Tables: expense_categories, expense_scenarios
Sprint: P0-S1

RLS 采用 NULLIF 安全格式，防止 app.tenant_id 为空时发生跨租户数据泄露。

Revision ID: v234
Revises: v233
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa

revision = "v234b"
down_revision = "v234"
branch_labels = None
depends_on = None

# 标准安全 RLS 条件（NULLIF 保护，与 v231 规范一致）
_RLS_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def upgrade() -> None:
    # ──────────────────────────────────────────────────────────────────
    # expense_categories — 费用科目树
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS expense_categories (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            parent_id       UUID        REFERENCES expense_categories(id) ON DELETE SET NULL,
            name            VARCHAR(50)  NOT NULL,
            code            VARCHAR(20)  NOT NULL,
            description     TEXT,
            sort_order      INTEGER      NOT NULL DEFAULT 0,
            is_system       BOOLEAN      NOT NULL DEFAULT FALSE,
            is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE expense_categories IS
            '费用科目树：支持多级父子树形结构，系统预置科目（is_system=true）不可删除';
        COMMENT ON COLUMN expense_categories.parent_id IS
            '父科目 ID，NULL 表示顶级科目；ON DELETE SET NULL 保障树结构完整性';
        COMMENT ON COLUMN expense_categories.code IS
            '科目代码，同一租户下唯一（UNIQUE），建议使用行业通用科目编码';
        COMMENT ON COLUMN expense_categories.sort_order IS
            '显示排序权重，数值越小越靠前，同级科目按此字段升序排列';
        COMMENT ON COLUMN expense_categories.is_system IS
            '是否系统预置科目：TRUE=系统内置不可删除，FALSE=租户自定义可删除';
        COMMENT ON COLUMN expense_categories.is_active IS
            '是否启用：FALSE 时科目对申请人不可见，但历史数据保留';

        CREATE UNIQUE INDEX IF NOT EXISTS uq_expense_categories_tenant_code
            ON expense_categories (tenant_id, code);

        CREATE INDEX IF NOT EXISTS ix_expense_categories_tenant_parent
            ON expense_categories (tenant_id, parent_id);

        CREATE INDEX IF NOT EXISTS ix_expense_categories_tenant_active
            ON expense_categories (tenant_id, is_active);
    """)

    # RLS 多租户隔离
    op.execute("ALTER TABLE expense_categories ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE expense_categories FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY expense_categories_rls ON expense_categories
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)

    # ──────────────────────────────────────────────────────────────────
    # expense_scenarios — 申请场景预置
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS expense_scenarios (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,
            code                    VARCHAR(30)  NOT NULL,
            name                    VARCHAR(50)  NOT NULL,
            description             TEXT,
            icon                    VARCHAR(10),
            default_category_id     UUID        REFERENCES expense_categories(id),
            required_fields         JSONB        NOT NULL DEFAULT '[]'::jsonb,
            approval_routing_hint   VARCHAR(20)  NOT NULL DEFAULT 'amount_based',
            sort_order              INTEGER      NOT NULL DEFAULT 0,
            is_active               BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE expense_scenarios IS
            '申请场景预置表：差旅/餐饮/采购/备用金等场景，每个场景预设默认科目和必填字段';
        COMMENT ON COLUMN expense_scenarios.code IS
            '场景代码，同一租户下唯一（UNIQUE），如 travel/meal/purchase/petty_cash';
        COMMENT ON COLUMN expense_scenarios.icon IS
            '场景图标（emoji，如 ✈️ 🍽️ 🛒），用于移动端申请入口展示';
        COMMENT ON COLUMN expense_scenarios.default_category_id IS
            '该场景的默认费用科目，申请人可在提交时手动更改';
        COMMENT ON COLUMN expense_scenarios.required_fields IS
            '该场景必填字段列表（JSONB 数组），如 ["invoice_no","expense_date","purpose"]';
        COMMENT ON COLUMN expense_scenarios.approval_routing_hint IS
            '审批路由提示：amount_based=按金额分级 / scenario_fixed=场景固定审批链 / escalated=升级审批';
        COMMENT ON COLUMN expense_scenarios.sort_order IS
            '显示排序权重，数值越小越靠前';

        CREATE UNIQUE INDEX IF NOT EXISTS uq_expense_scenarios_tenant_code
            ON expense_scenarios (tenant_id, code);

        CREATE INDEX IF NOT EXISTS ix_expense_scenarios_tenant_active
            ON expense_scenarios (tenant_id, is_active);
    """)

    # RLS 多租户隔离
    op.execute("ALTER TABLE expense_scenarios ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE expense_scenarios FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY expense_scenarios_rls ON expense_scenarios
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)


def downgrade() -> None:
    # expense_scenarios（先删，因为引用 expense_categories）
    op.execute("DROP POLICY IF EXISTS expense_scenarios_rls ON expense_scenarios;")
    op.execute("DROP TABLE IF EXISTS expense_scenarios CASCADE;")

    # expense_categories（后删）
    op.execute("DROP POLICY IF EXISTS expense_categories_rls ON expense_categories;")
    op.execute("DROP TABLE IF EXISTS expense_categories CASCADE;")
