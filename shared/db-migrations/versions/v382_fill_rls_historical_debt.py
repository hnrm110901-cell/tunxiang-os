"""v382 — 补齐历史 RLS 技术债（14 张表）

CLAUDE.md § 13 禁止事项：禁止跳过 RLS — 所有 DB 操作必须带 tenant_id。
CLAUDE.md § 17 Tier 1：RLS 多租户隔离是硬约束。

tests/tier1/test_rls_all_tables_tier1.py 静态扫描发现 14 张业务表历史遗留
缺 RLS。全部含 tenant_id 列，可安全补启用。

修复清单（按原 migration 来源）：

  v053_supply_chain_mobile.py
    · receiving_items                 进货明细（供应链移动）
    · stocktake_items                 盘点明细
  v062_central_kitchen.py
    · distribution_orders             中央厨房配送单
    · production_orders               生产订单
    · store_receiving_confirmations   门店收货确认
  v064_wms_persistence.py
    · stocktakes                      库存盘点主表
    · warehouse_transfers             仓库调拨
    · warehouse_transfer_items        调拨明细
  v067_three_way_match.py
    · purchase_invoices               采购发票
    · purchase_match_records          三单匹配记录
  v090_pilot_tracking.py
    · pilot_items                     试点项
    · pilot_metrics                   试点指标
    · pilot_programs                  试点项目
    · pilot_reviews                   试点评审

均按"CLAUDE.md RLS 标准模板"应用：
  · ENABLE ROW LEVEL SECURITY
  · FORCE ROW LEVEL SECURITY（防表 owner 绕过）
  · 单 POLICY 覆盖 4 操作（SELECT/INSERT/UPDATE/DELETE）
  · USING + WITH CHECK 子句用 current_setting('app.tenant_id', true) 对比

关于 FORCE：屯象OS 所有业务表都应 FORCE RLS；但为避免 downgrade 风险，
FORCE 前检查表是否已启用 ENABLE（避免对未建表执行）。

Revision ID: v382_fill_rls_historical_debt
Revises: v381_delivery_disputes
Create Date: 2026-04-24
"""
from alembic import op

revision = "v382_fill_rls_historical_debt"
down_revision = "v381_delivery_disputes"
branch_labels = None
depends_on = None


# 14 张待补表（以 CLAUDE.md § 13 要求为准）
TABLES_TO_FIX: tuple[str, ...] = (
    # supply chain mobile
    "receiving_items",
    "stocktake_items",
    # central kitchen
    "distribution_orders",
    "production_orders",
    "store_receiving_confirmations",
    # WMS
    "stocktakes",
    "warehouse_transfers",
    "warehouse_transfer_items",
    # three-way match
    "purchase_invoices",
    "purchase_match_records",
    # pilot tracking
    "pilot_items",
    "pilot_metrics",
    "pilot_programs",
    "pilot_reviews",
)


# 兼容旧 migration 已手工改过（升级时表不存在则跳过）
def _table_exists(table: str) -> str:
    """DO 块：表存在才执行（避免 legacy 环境 / 降级后未重建）

    注：f-string 内拼接 {table}；table 来自硬编码 TABLES_TO_FIX，非用户输入。
    """
    return f"""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = '{table}'
        ) THEN
            RAISE NOTICE '跳过 {table}（表不存在）';
            RETURN;
        END IF;

        -- 启用 RLS（幂等：已启用不报错）
        EXECUTE 'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE {table} FORCE ROW LEVEL SECURITY';

        -- 防重建：先 DROP 再 CREATE
        EXECUTE 'DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}';
        EXECUTE $POLICY$
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (tenant_id::text = current_setting('app.tenant_id', true))
                WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
        $POLICY$;
    END $$;
    """  # noqa: S608 — table from hardcoded TABLES_TO_FIX, not user input


def upgrade() -> None:
    for table in TABLES_TO_FIX:
        op.execute(_table_exists(table))

    # 注释：记录历史债还清
    op.execute("""
        COMMENT ON POLICY receiving_items_tenant_isolation ON receiving_items
            IS 'v382 补齐历史 RLS 技术债（原 v053 migration 漏）';
    """)
    op.execute("""
        COMMENT ON POLICY production_orders_tenant_isolation ON production_orders
            IS 'v382 补齐历史 RLS 技术债（原 v062 migration 漏）';
    """)
    op.execute("""
        COMMENT ON POLICY stocktakes_tenant_isolation ON stocktakes
            IS 'v382 补齐历史 RLS 技术债（原 v064 migration 漏）';
    """)
    op.execute("""
        COMMENT ON POLICY purchase_invoices_tenant_isolation ON purchase_invoices
            IS 'v382 补齐历史 RLS 技术债（原 v067 migration 漏）';
    """)
    op.execute("""
        COMMENT ON POLICY pilot_programs_tenant_isolation ON pilot_programs
            IS 'v382 补齐历史 RLS 技术债（原 v090 migration 漏）';
    """)


def downgrade() -> None:
    """仅 DROP POLICY + DISABLE RLS；不 DROP TABLE（业务数据还在）

    注意：downgrade 后表会重新变成"无 RLS"状态，这是原历史状态。
    """
    for table in TABLES_TO_FIX:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = '{table}'
                ) THEN
                    EXECUTE 'DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}';
                    EXECUTE 'ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY';
                    EXECUTE 'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY';
                END IF;
            END $$;
        """)  # noqa: S608 — table from hardcoded TABLES_TO_FIX, not user input
