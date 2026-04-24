"""v139: 修复 v119 dish_boms / dish_bom_items RLS 策略安全漏洞

v119 为 dish_boms 和 dish_bom_items 两张表创建的 RLS 策略存在以下三个问题：
  1. 使用 `current_setting('app.tenant_id', true)::uuid` 直接强转，
     缺少 NULLIF 保护——当 app.tenant_id 未设置或为空字符串时会抛出异常。
  2. 策略只有 USING 子句，缺少 WITH CHECK，
     导致 INSERT / UPDATE 操作可绕过租户隔离写入任意租户数据。
  3. 未设置 FORCE ROW LEVEL SECURITY，表所有者可能绕过 RLS。

修复方案：
  - 对两张表均执行 FORCE ROW LEVEL SECURITY
  - 删除旧策略，创建带 NULLIF + WITH CHECK 的标准策略
  - 与 v097/v101/v102/v138 保持一致

Revision ID: v139
Revises: v138
Create Date: 2026-04-04
"""

from alembic import op

revision = "v139"
down_revision = "v138"
branch_labels = None
depends_on = None

# 受影响的表及旧策略名
_TABLES_TO_FIX = [
    ("dish_boms", "dish_boms_tenant_isolation"),
    ("dish_bom_items", "dish_bom_items_tenant_isolation"),
]

# 标准安全条件（NULLIF 防空串 + UUID 强转）
_SAFE_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    for table, old_policy in _TABLES_TO_FIX:
        new_policy = f"{table}_rls_v139"

        # 1. 强制表所有者也受 RLS 约束
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")

        # 2. 删除 v119 旧策略
        op.execute(f"DROP POLICY IF EXISTS {old_policy} ON {table};")

        # 3. 创建标准策略：NULLIF + WITH CHECK
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = '{table}' AND policyname = '{new_policy}'
                ) THEN
                    CREATE POLICY {new_policy} ON {table}
                        AS PERMISSIVE FOR ALL TO PUBLIC
                        USING ({_SAFE_CONDITION})
                        WITH CHECK ({_SAFE_CONDITION});
                END IF;
            END $$;
        """)


def downgrade() -> None:
    for table, old_policy in _TABLES_TO_FIX:
        new_policy = f"{table}_rls_v139"

        # 删除修复后策略
        op.execute(f"DROP POLICY IF EXISTS {new_policy} ON {table};")

        # 恢复 v119 旧策略（不含 NULLIF / WITH CHECK，仅做版本回退用）
        op.execute(f"""
            CREATE POLICY {old_policy} ON {table}
            USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
        """)

        # 取消 FORCE ROW LEVEL SECURITY
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
