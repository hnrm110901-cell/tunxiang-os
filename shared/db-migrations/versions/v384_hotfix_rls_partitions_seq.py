"""v371: hotfix — 补 v368 / v370 遗漏的 RLS

post-merge review 发现 P0 PR 5 个合并到 main 后两处 RLS 遗漏，存在跨租户信息
泄露风险，必须 hotfix：

  A. v370 的 stocktake_loss_case_no_seq （案件号序列表，含 tenant_id）只
     建表 + 索引，没有调用 _apply_safe_rls，导致跨租户能 SELECT 对方今日
     案件计数。

  B. v368 的 delivery_temperature_logs 是 PARTITION BY RANGE 父表，对父表
     启用 RLS 不会自动应用到 PARTITION OF 子表。
     delivery_temperature_logs_default 子表当前完全没有 RLS，跨租户可读。
     （PG 行为：分区表 RLS 必须在每个子表单独启用 + 创建 policy）

修复策略：
  - 直接对两张漏掉的表启用 RLS + 4 操作 policy（NULLIF NULL-guard）
  - 同时遍历 delivery_temperature_logs 父表的所有 PARTITION OF 子表，
    给每张子表都启用 RLS（防止未来按月预创建的新分区也漏）

下一步（不在本迁移内）：
  - shared/db-migrations/versions/_helpers.py 抽公共
    enable_rls_for_table_and_partitions() 工具函数
  - 未来按月预创建 partition 时，必须用该工具函数代替手工 ENABLE

依赖：v370_stocktake_loss（提供 stocktake_loss_case_no_seq）
      v368_delivery_temperature（提供 delivery_temperature_logs_default）

Revision ID: v371_hotfix_rls_partitions_seq
Revises: v370_stocktake_loss, v368_delivery_temperature
Create Date: 2026-04-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v371_hotfix_rls_partitions_seq"
# 多 down_revision：本迁移同时依赖 v368 与 v370 的表存在
down_revision: Union[str, Sequence[str], None] = (
    "v370_stocktake_loss",
    "v368_delivery_temperature",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ─────────────────────────────────────────────────────────────────────────────
# RLS 安全条件：与 v368/v370 已采用的写法保持一致（NULLIF NULL-guard）
# ─────────────────────────────────────────────────────────────────────────────
_SAFE_CONDITION = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def _apply_safe_rls(table: str) -> None:
    """启用表的 RLS 并为 4 类操作创建 PERMISSIVE policy（NULLIF NULL-guard）。

    幂等：DROP POLICY IF EXISTS 后重建，可重复执行不报错。
    """
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_select ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_select ON {table} "
        f"FOR SELECT USING ({_SAFE_CONDITION})"
    )
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_insert ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_insert ON {table} "
        f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_update ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_update ON {table} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_delete ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_delete ON {table} "
        f"FOR DELETE USING ({_SAFE_CONDITION})"
    )


def _drop_safe_rls(table: str) -> None:
    """移除 _apply_safe_rls 创建的 4 个 policy + 关闭 RLS（用于 downgrade）。

    DROP POLICY IF EXISTS 与 DISABLE RLS 都是幂等操作。
    """
    for suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {table}_rls_{suffix} ON {table}")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # ───────────────────────────────────────────────────────────────────
    # A. stocktake_loss_case_no_seq （v370 遗漏）
    #    该表存放每租户每天的案件序号，含 tenant_id 列但 v370 创建后
    #    未调用 _apply_safe_rls。跨租户能读到对方当日的 last_seq。
    #
    #    该表同时被 fn_next_loss_case_no(uuid, date) 函数 INSERT/UPDATE。
    #    服务层 _generate_case_no 在调用前总是先 _set_tenant 设置
    #    app.tenant_id，函数以 INVOKER 身份运行 → 自动继承会话设置 →
    #    RLS policy 通过。无需把函数改 SECURITY DEFINER。
    # ───────────────────────────────────────────────────────────────────
    _apply_safe_rls("stocktake_loss_case_no_seq")

    # ───────────────────────────────────────────────────────────────────
    # B. delivery_temperature_logs_default 分区子表（v368 遗漏）
    #    PG 中分区表的 RLS policy 不会自动下推到 PARTITION OF 子表，必须
    #    在每张子表单独 ENABLE + CREATE POLICY。
    #
    #    此处直接对当前已知的 default 子表启用，再用 DO 块自动覆盖父表
    #    下其它已存在的分区子表（防生产已经手工预创建按月分区）。
    # ───────────────────────────────────────────────────────────────────
    _apply_safe_rls("delivery_temperature_logs_default")

    # 自动覆盖父表下所有其它子分区（生产可能已手工建按月分区）
    op.execute("""
        DO $$
        DECLARE
            child_oid OID;
            child_name TEXT;
        BEGIN
            FOR child_oid IN
                SELECT inhrelid
                FROM pg_inherits
                WHERE inhparent = 'delivery_temperature_logs'::regclass
            LOOP
                child_name := child_oid::regclass::text;
                -- default 子表已显式处理过，跳过避免重复
                IF child_name = 'delivery_temperature_logs_default' THEN
                    CONTINUE;
                END IF;

                EXECUTE format(
                    'ALTER TABLE %s ENABLE ROW LEVEL SECURITY', child_name);
                EXECUTE format(
                    'ALTER TABLE %s FORCE ROW LEVEL SECURITY', child_name);

                EXECUTE format(
                    'DROP POLICY IF EXISTS %I ON %s',
                    child_name || '_rls_select', child_name);
                EXECUTE format(
                    'CREATE POLICY %I ON %s FOR SELECT USING '
                    '(tenant_id = NULLIF(current_setting(''app.tenant_id'', TRUE), '''')::UUID)',
                    child_name || '_rls_select', child_name);

                EXECUTE format(
                    'DROP POLICY IF EXISTS %I ON %s',
                    child_name || '_rls_insert', child_name);
                EXECUTE format(
                    'CREATE POLICY %I ON %s FOR INSERT WITH CHECK '
                    '(tenant_id = NULLIF(current_setting(''app.tenant_id'', TRUE), '''')::UUID)',
                    child_name || '_rls_insert', child_name);

                EXECUTE format(
                    'DROP POLICY IF EXISTS %I ON %s',
                    child_name || '_rls_update', child_name);
                EXECUTE format(
                    'CREATE POLICY %I ON %s FOR UPDATE USING '
                    '(tenant_id = NULLIF(current_setting(''app.tenant_id'', TRUE), '''')::UUID) '
                    'WITH CHECK '
                    '(tenant_id = NULLIF(current_setting(''app.tenant_id'', TRUE), '''')::UUID)',
                    child_name || '_rls_update', child_name);

                EXECUTE format(
                    'DROP POLICY IF EXISTS %I ON %s',
                    child_name || '_rls_delete', child_name);
                EXECUTE format(
                    'CREATE POLICY %I ON %s FOR DELETE USING '
                    '(tenant_id = NULLIF(current_setting(''app.tenant_id'', TRUE), '''')::UUID)',
                    child_name || '_rls_delete', child_name);
            END LOOP;
        END $$;
    """)


def downgrade() -> None:
    # 反向：先移除遍历创建的子分区 policy，再移除 default 子表与序列表的 policy
    op.execute("""
        DO $$
        DECLARE
            child_oid OID;
            child_name TEXT;
        BEGIN
            FOR child_oid IN
                SELECT inhrelid
                FROM pg_inherits
                WHERE inhparent = 'delivery_temperature_logs'::regclass
            LOOP
                child_name := child_oid::regclass::text;
                IF child_name = 'delivery_temperature_logs_default' THEN
                    CONTINUE;
                END IF;
                EXECUTE format(
                    'DROP POLICY IF EXISTS %I ON %s',
                    child_name || '_rls_select', child_name);
                EXECUTE format(
                    'DROP POLICY IF EXISTS %I ON %s',
                    child_name || '_rls_insert', child_name);
                EXECUTE format(
                    'DROP POLICY IF EXISTS %I ON %s',
                    child_name || '_rls_update', child_name);
                EXECUTE format(
                    'DROP POLICY IF EXISTS %I ON %s',
                    child_name || '_rls_delete', child_name);
                EXECUTE format(
                    'ALTER TABLE %s DISABLE ROW LEVEL SECURITY', child_name);
            END LOOP;
        END $$;
    """)

    _drop_safe_rls("delivery_temperature_logs_default")
    _drop_safe_rls("stocktake_loss_case_no_seq")
