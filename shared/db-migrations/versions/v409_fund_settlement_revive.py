"""v409: 资金分账表 revive — split_rules / split_ledgers / settlement_batches

PR #357 ORM↔migration drift 检测捕获 fund_settlement.py 三张 ORM (split_rules /
split_ledgers / settlement_batches) 在 main chain 中均无 CREATE TABLE。

LIVE 影响（runtime 必坏）：
  - services/tx-finance/src/services/fund_settlement_service.py 大量 raw SQL
    INSERT/SELECT split_rules / split_ledgers — API 调用时表不存在即 500
  - services/tx-finance/src/api/fund_settlement_routes.py 暴露
    list_split_rules / list_settlement_batches 端点
  - services/tx-finance/src/api/split_routes.py / split_payment_routes.py 共用

历史背景：原 v071_fund_settlement_tables 在 PR #128 chain rescue (a566102d) 中
被改名 v071b 并 disabled (.py.disabled 后缀)。同名 v071_model_call_logs.py 后续
独立 enabled，但本文件未 revive。enabled chain 中 v100_profit_split_engine 建的
是 profit_split_rules / profit_split_records（**前缀不同**）；v346_stored_value_settlement
建的是 stored_value_split_* / sv_settlement_batches（**前缀不同**）—— 三张 ORM 表名
在 enabled chain 中无任何痕迹，本 PR 完整 revive。

──────── 列对齐验证（v071 SQL ↔ ORM ↔ 现行 raw SQL）────────
- settlement_batches: 13 列全对齐（NOT NULL / 类型 / DEFAULT 三方一致）
- split_ledgers:      16 列全对齐 + raw SQL INSERT 子集（10 列）全在
- split_rules:        12 列全对齐 + raw SQL INSERT 子集（8 列）全在
索引命名漂移（ORM 与 v071 SQL 命名不一致，drift 检测目前不覆盖）属次重点，
本 PR 仅采用 v071 SQL 索引名（保持单源真相），ORM 引用是 SQLAlchemy 内部对象
不依赖物理索引名。

──────── 修复 v071 原文件 SECURITY bug (Class F2) ────────
原 _apply_rls 4 个 action 全用 USING；PG 不接受 INSERT POLICY USING。
按 PR #361 / #362 同模式修：
  SELECT/DELETE: USING only
  INSERT:        WITH CHECK only
  UPDATE:        USING + WITH CHECK (PG.7 防 tenant_id 行漂移)

Revision ID: v409_fund_settlement_revive
Revises: v408_distribution_trips_items_revive
Create Date: 2026-05-10
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v409_fund_settlement_revive"
down_revision: Union[str, Sequence[str], None] = "v408_distribution_trips_items_revive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TENANT_PREDICATE = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def _apply_rls(table_name: str) -> None:
    """ENABLE+FORCE RLS + 4 条 RESTRICTIVE 策略（INSERT WITH CHECK / UPDATE 双子句）。"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;")

    # SELECT — USING only
    op.execute(f"""
        CREATE POLICY {table_name}_select_tenant ON {table_name}
        AS RESTRICTIVE FOR SELECT
        USING ({_TENANT_PREDICATE});
    """)

    # INSERT — WITH CHECK only (PG: USING invalid for INSERT)
    op.execute(f"""
        CREATE POLICY {table_name}_insert_tenant ON {table_name}
        AS RESTRICTIVE FOR INSERT
        WITH CHECK ({_TENANT_PREDICATE});
    """)

    # UPDATE — USING + WITH CHECK (PG.7 防 tenant_id 行漂移)
    op.execute(f"""
        CREATE POLICY {table_name}_update_tenant ON {table_name}
        AS RESTRICTIVE FOR UPDATE
        USING ({_TENANT_PREDICATE})
        WITH CHECK ({_TENANT_PREDICATE});
    """)

    # DELETE — USING only
    op.execute(f"""
        CREATE POLICY {table_name}_delete_tenant ON {table_name}
        AS RESTRICTIVE FOR DELETE
        USING ({_TENANT_PREDICATE});
    """)


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # split_rules — 分账规则
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS split_rules (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID        NOT NULL,
            store_id          UUID        NOT NULL,
            rule_type         VARCHAR(30) NOT NULL,
            rate_permil       INTEGER     NOT NULL DEFAULT 0,
            fixed_fee_fen     INTEGER     NOT NULL DEFAULT 0,
            effective_from    DATE        NOT NULL,
            effective_to      DATE,
            is_active         BOOLEAN     NOT NULL DEFAULT TRUE,
            is_deleted        BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    _apply_rls("split_rules")

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_rules_tenant
            ON split_rules (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_rules_tenant_store
            ON split_rules (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_rules_tenant_type
            ON split_rules (tenant_id, rule_type);
    """)

    # ─────────────────────────────────────────────────────────────────
    # split_ledgers — 分账流水
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS split_ledgers (
            id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID        NOT NULL,
            order_id             UUID        NOT NULL,
            payment_id           UUID,
            store_id             UUID        NOT NULL,
            total_amount_fen     INTEGER     NOT NULL,
            platform_fee_fen     INTEGER     NOT NULL DEFAULT 0,
            brand_royalty_fen    INTEGER     NOT NULL DEFAULT 0,
            franchise_share_fen  INTEGER     NOT NULL DEFAULT 0,
            net_settlement_fen   INTEGER     NOT NULL DEFAULT 0,
            status               VARCHAR(20) NOT NULL DEFAULT 'pending',
            settled_at           TIMESTAMPTZ,
            batch_id             UUID,
            is_deleted           BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    _apply_rls("split_ledgers")

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_ledgers_tenant
            ON split_ledgers (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_ledgers_tenant_order
            ON split_ledgers (tenant_id, order_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_ledgers_tenant_store
            ON split_ledgers (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_ledgers_tenant_status
            ON split_ledgers (tenant_id, status);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_ledgers_tenant_batch
            ON split_ledgers (tenant_id, batch_id);
    """)

    # ─────────────────────────────────────────────────────────────────
    # settlement_batches — 结算批次
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS settlement_batches (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID        NOT NULL,
            batch_no          VARCHAR(50) NOT NULL UNIQUE,
            period_start      DATE        NOT NULL,
            period_end        DATE        NOT NULL,
            store_id          UUID        NOT NULL,
            total_orders      INTEGER     NOT NULL DEFAULT 0,
            total_amount_fen  INTEGER     NOT NULL DEFAULT 0,
            total_split_fen   INTEGER     NOT NULL DEFAULT 0,
            status            VARCHAR(20) NOT NULL DEFAULT 'draft',
            is_deleted        BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    _apply_rls("settlement_batches")

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_settlement_batches_tenant
            ON settlement_batches (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_settlement_batches_tenant_store
            ON settlement_batches (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_settlement_batches_tenant_status
            ON settlement_batches (tenant_id, status);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_settlement_batches_tenant_batch_no
            ON settlement_batches (tenant_id, batch_no);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS split_ledgers CASCADE;")
    op.execute("DROP TABLE IF EXISTS settlement_batches CASCADE;")
    op.execute("DROP TABLE IF EXISTS split_rules CASCADE;")
