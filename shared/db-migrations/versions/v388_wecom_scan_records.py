"""v388 — 扫码记录表（WC-1 扫码事件持久化）

扫码记录用于追踪每次渠道活码的扫码事件，支持：
- 扫码量统计（日/周/月）
- 唯一用户去重统计
- 动作执行记录（打标签/回复/拉群）

表: wecom_scan_records
  字段: id / tenant_id / channel_id / external_userid
        / tagged / replied / invited
        / created_at / updated_at

RLS: 4 条 PERMISSIVE + FORCE

Revision ID: v388_wecom_scan_records
Revises: v387_channels_ec_sync
Create Date: 2026-05-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v388_wecom_scan_records"
down_revision: Union[str, None] = "v387_channels_ec_sync"
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
        CREATE TABLE IF NOT EXISTS wecom_scan_records (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            channel_id      UUID NOT NULL,
            external_userid VARCHAR(128) NOT NULL,
            tagged          BOOLEAN NOT NULL DEFAULT FALSE,
            replied         BOOLEAN NOT NULL DEFAULT FALSE,
            invited         BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wecom_scan_records_tenant "
        "ON wecom_scan_records (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wecom_scan_records_channel "
        "ON wecom_scan_records (channel_id, tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wecom_scan_records_created "
        "ON wecom_scan_records (tenant_id, created_at DESC)"
    )
    _enable_rls("wecom_scan_records")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wecom_scan_records CASCADE")
