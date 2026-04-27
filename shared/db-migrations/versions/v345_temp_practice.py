"""v345 — 菜品做法扩展：临时做法 + 做法类型 + 加料数量

在 dish_practices 表新增三个字段：
  - is_temporary   BOOLEAN DEFAULT FALSE   — 临时做法标记（有价做法，顾客自定义）
  - practice_type  VARCHAR(20) DEFAULT 'standard' — 做法类型（standard|temporary|addon）
  - max_quantity   INT DEFAULT 1            — 加料可多份（如加蛋x2）

Revision: v345_temp_practice
Revises: v344_banquet_aftercare
Create Date: 2026-04-25
"""

from alembic import op
import sqlalchemy as sa

revision = "v345_temp_practice"
down_revision = "v345_reservation_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # is_temporary — 标记临时做法（顾客自定义有价做法）
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'dish_practices' AND column_name = 'is_temporary'
            ) THEN
                ALTER TABLE dish_practices
                ADD COLUMN is_temporary BOOLEAN NOT NULL DEFAULT FALSE;
            END IF;
        END $$;
    """)

    # practice_type — 做法类型枚举（standard/temporary/addon）
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'dish_practices' AND column_name = 'practice_type'
            ) THEN
                ALTER TABLE dish_practices
                ADD COLUMN practice_type VARCHAR(20) NOT NULL DEFAULT 'standard';
            END IF;
        END $$;
    """)

    # max_quantity — 加料可选数量上限（加蛋x3）
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'dish_practices' AND column_name = 'max_quantity'
            ) THEN
                ALTER TABLE dish_practices
                ADD COLUMN max_quantity INT NOT NULL DEFAULT 1;
            END IF;
        END $$;
    """)

    # 为 practice_type 创建索引，方便按类型查询
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dish_practices_type
        ON dish_practices (tenant_id, practice_type)
        WHERE is_deleted = false;
    """)

    # 为 is_temporary 创建部分索引，加速临时做法查询
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dish_practices_temporary
        ON dish_practices (tenant_id, dish_id)
        WHERE is_temporary = true AND is_deleted = false;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_dish_practices_temporary;")
    op.execute("DROP INDEX IF EXISTS ix_dish_practices_type;")
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE dish_practices DROP COLUMN IF EXISTS max_quantity;
            ALTER TABLE dish_practices DROP COLUMN IF EXISTS practice_type;
            ALTER TABLE dish_practices DROP COLUMN IF EXISTS is_temporary;
        END $$;
    """)
