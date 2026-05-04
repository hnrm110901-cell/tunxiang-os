"""Tier1: 积分系统核心三表 — member_cards + points_log + card_types

W12-1 积分系统智能体已交付完整业务逻辑（earn/spend/multiplier/growth_value/
跨店结算/FIFO 过期），但底层三张表从未在迁移中创建。本迁移补齐建表 +
RLS + 索引，使 services/tx-member/src/services/points_engine.py 与
card_engine.py 可真正落地。

字段口径严格反推自 services/tx-member/src/services/{points_engine,card_engine}.py
的所有 SQL 引用，超集去重：

  card_types:
    id, tenant_id, name, rules(JSONB), levels(JSONB),
    earn_rules(JSONB), spend_rules(JSONB),
    multiplier_config(JSONB), member_day_config(JSONB),
    created_at/updated_at/is_deleted

  member_cards:
    id, tenant_id, card_type_id, customer_id(可空，匿名卡), batch_no,
    status(inactive|active|frozen|cancelled), is_anonymous,
    level_rank(INT), balance_fen(BIGINT), points(BIGINT), growth_value(BIGINT),
    issued_at, created_at/updated_at/is_deleted

  points_log:
    id, tenant_id, card_id, direction('earn'|'spend'),
    source(消费来源/抵扣用途，自由文本),
    points(BIGINT), created_at

金额相关字段统一 BIGINT（CLAUDE.md §10：所有金额单位"分(fen)"，
积分整数；BIGINT 防止 32 位溢出）。

RLS: 4 条 PERMISSIVE policy + ENABLE FORCE，模式与 v391_delivery_dispatches
完全一致（NULLIF + cast → UUID）。

索引：
  member_cards   tenant_id+customer_id（按客户取卡）
                 tenant_id+card_type_id+level_rank（等级聚合）
                 tenant_id+batch_no（匿名卡批次定位）
  points_log     tenant_id+card_id+created_at DESC（明细分页）
                 tenant_id+direction+created_at（跨店结算扫表）
  card_types     tenant_id+name（同租户卡类型查重）

外键策略：暂不加强制 FK（card_id→member_cards.id /
card_type_id→card_types.id / customer_id→customers.id）。
理由：跨服务/跨租户写入路径较多，分批回填历史数据期间 FK 会触发约束爆雷。
应用层（services 层）已通过 tenant_id + is_deleted 过滤兜底；
后续在数据收敛后再补 FK 不迟。

Revision ID: v392_points_system_core
Revises: v391_delivery_dispatches
Create Date: 2026-05-04
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v392_points_system_core"
down_revision: Union[str, None] = "v391_delivery_dispatches"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def _enable_rls(table: str) -> None:
    """为指定表创建完整 RLS（4条 PERMISSIVE + FORCE）。"""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        policy = f"rls_{table}_{action.lower()}"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        if action == "INSERT":
            # INSERT 用 WITH CHECK 而不是 USING
            op.execute(
                f"CREATE POLICY {policy} ON {table} "
                f"AS PERMISSIVE FOR {action} TO PUBLIC "
                f"WITH CHECK (tenant_id = {_RLS_EXPR})"
            )
        else:
            op.execute(
                f"CREATE POLICY {policy} ON {table} "
                f"AS PERMISSIVE FOR {action} TO PUBLIC "
                f"USING (tenant_id = {_RLS_EXPR})"
            )


def upgrade() -> None:
    # ── 1. card_types ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS card_types (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,

            name                    VARCHAR(100) NOT NULL,
            rules                   JSONB NOT NULL DEFAULT '{}'::JSONB,
            levels                  JSONB NOT NULL DEFAULT '[]'::JSONB,

            earn_rules              JSONB NOT NULL DEFAULT '{}'::JSONB,
            spend_rules             JSONB NOT NULL DEFAULT '{}'::JSONB,
            multiplier_config       JSONB NOT NULL DEFAULT '{}'::JSONB,
            member_day_config       JSONB NOT NULL DEFAULT '{}'::JSONB,

            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_card_types_tenant_name
            ON card_types (tenant_id, name)
            WHERE is_deleted = FALSE
    """)

    _enable_rls("card_types")

    # ── 2. member_cards ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS member_cards (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,

            card_type_id            UUID NOT NULL,
            customer_id             UUID,
            batch_no                VARCHAR(64),

            status                  VARCHAR(20) NOT NULL DEFAULT 'inactive'
                                        CHECK (status IN (
                                            'inactive', 'active', 'frozen', 'cancelled'
                                        )),
            is_anonymous            BOOLEAN NOT NULL DEFAULT FALSE,

            level_rank              INT NOT NULL DEFAULT 0,
            balance_fen             BIGINT NOT NULL DEFAULT 0
                                        CHECK (balance_fen >= 0),
            points                  BIGINT NOT NULL DEFAULT 0
                                        CHECK (points >= 0),
            growth_value            BIGINT NOT NULL DEFAULT 0
                                        CHECK (growth_value >= 0),

            issued_at               TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_member_cards_tenant_customer
            ON member_cards (tenant_id, customer_id)
            WHERE is_deleted = FALSE AND customer_id IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_member_cards_tenant_type_rank
            ON member_cards (tenant_id, card_type_id, level_rank)
            WHERE is_deleted = FALSE
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_member_cards_tenant_batch
            ON member_cards (tenant_id, batch_no)
            WHERE batch_no IS NOT NULL
    """)

    _enable_rls("member_cards")

    # ── 3. points_log ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS points_log (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,

            card_id                 UUID NOT NULL,
            direction               VARCHAR(10) NOT NULL
                                        CHECK (direction IN ('earn', 'spend')),
            source                  VARCHAR(64) NOT NULL,
            points                  BIGINT NOT NULL
                                        CHECK (points > 0),

            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_points_log_tenant_card_created
            ON points_log (tenant_id, card_id, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_points_log_tenant_direction_created
            ON points_log (tenant_id, direction, created_at)
    """)

    _enable_rls("points_log")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS points_log CASCADE")
    op.execute("DROP TABLE IF EXISTS member_cards CASCADE")
    op.execute("DROP TABLE IF EXISTS card_types CASCADE")
