"""v441 — PRD-09: dish_boms 分解型 BOM 支持

新增 assembly_type 字段 ('assembly'/'disassembly') 至 dish_boms 表。
带 DEFAULT 'assembly'，保证现有 BOM 行零破坏（cashier_engine 无感知）。

业务背景：
  海鲜店 10kg 整鱼 → 鱼柳 5kg + 鱼骨 2kg + 内脏 3kg（分解型 BOM）。
  cashier consume-stock 只读 is_active=true，不读 assembly_type，零影响。
  分解型 BOM 创建后默认 is_active=false，与 cashier 路径天然隔离。

设计要点：
  - ALTER TABLE 加列（不新建表），现有 cashier 扣料路径零改动
  - DEFAULT 'assembly' NOT NULL CHECK IN ('assembly','disassembly')
  - 附带索引 (tenant_id, assembly_type) WHERE is_deleted = false 加速类型过滤
  - RLS：dish_boms 已由 v139_fix_v119_dish_boms_rls 覆盖，新列无需额外策略
  - inspector-and-skip 幂等模式（IF NOT EXISTS）

Migration 链：
  v440_certificate_types → v441_dish_boms_assembly_type

Revision ID: v441_dish_boms_assembly_type
Revises: v440_certificate_types
Create Date: 2026-05-17
"""

from alembic import op

revision = "v441_dish_boms_assembly_type"
down_revision = "v440_certificate_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'dish_boms'
                  AND column_name = 'assembly_type'
            ) THEN
                ALTER TABLE dish_boms
                ADD COLUMN assembly_type VARCHAR(20)
                    NOT NULL DEFAULT 'assembly'
                    CHECK (assembly_type IN ('assembly', 'disassembly'));

                COMMENT ON COLUMN dish_boms.assembly_type IS
                    'BOM类型: assembly=组装型(食材→成品), disassembly=分解型(整件→零件)';
            END IF;
        END $$;
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dish_boms_assembly_type
        ON dish_boms (tenant_id, assembly_type)
        WHERE is_deleted = false;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_dish_boms_assembly_type;")
    op.execute("""
        ALTER TABLE dish_boms DROP COLUMN IF EXISTS assembly_type;
    """)
