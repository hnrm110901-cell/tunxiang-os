"""v384 — 企业微信渠道活码表（WC-1 数据持久化）

渠道活码用于追踪不同渠道来源的扫码客户，支持：
- 渠道来源追踪（scan_count）
- 自动打标签（auto_tags, JSONB）
- 自动回复文案（auto_reply）
- 自动拉群（group_id）

表: wecom_channel_codes
  字段: id / tenant_id / merchant_code / channel_name / qrcode_url
        / auto_tags(JSONB) / auto_reply / group_id / scan_count
        / is_active / created_at / updated_at

RLS: 4条 PERMISSIVE + FORCE

Revision ID: v384_wecom_channel_codes
Revises: v383_chain_consolidation
Create Date: 2026-05-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v384_wecom_channel_codes"
down_revision: Union[str, None] = "v383_chain_consolidation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        policy = f"rls_{table}_{action.lower()}"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(
            f"CREATE POLICY {policy} ON {table} "
            f"AS PERMISSIVE FOR {action} TO PUBLIC "
            f"USING (tenant_id = {_RLS_EXPR})"
        )


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS wecom_channel_codes (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            merchant_code   VARCHAR(50) NOT NULL,
            channel_name    VARCHAR(200) NOT NULL,
            qrcode_url      TEXT NOT NULL,
            auto_tags       JSONB DEFAULT '[]'::jsonb,
            auto_reply      TEXT DEFAULT '',
            group_id        VARCHAR(50),
            scan_count      INT NOT NULL DEFAULT 0,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wecom_channel_codes_tenant "
        "ON wecom_channel_codes (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wecom_channel_codes_merchant "
        "ON wecom_channel_codes (merchant_code, tenant_id)"
    )
    _enable_rls("wecom_channel_codes")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wecom_channel_codes CASCADE")
