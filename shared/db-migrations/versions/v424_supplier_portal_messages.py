"""v424 — supplier_portal_messages：供应商门户消息收件箱（PR-01B sub-PR B / PRD-01）

业务背景：
  供应商门户消息表（最小可用版），供 cert_expiry_alerter 在 D+0 起写入
  过期证件提醒消息。sub-PR C 读此表实现 portal inbox UI。

设计要点：
  1. supplier_portal_messages — 多类型消息（证件预警 / RFQ 邀约 / ...）
  2. message_type 字段扩展性：'cert_expiry_alert' / 'rfq_invitation' / ...
  3. metadata JSONB — 灵活附加字段（cert_id / expire_date / days_overdue 等）
  4. read_at — 已读状态，供 portal inbox 标记未读
  5. RLS：tenant_id::text = current_setting('app.tenant_id', true)（标准模式）
  6. inspector-and-skip 防重运行（参考 v421 / v423 模式）

Revision ID: v424_supplier_portal_messages
Revises: v423_cert_alert_log
Create Date: 2026-05-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v424_supplier_portal_messages"
down_revision: Union[str, Sequence[str], None] = "v423_cert_alert_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "supplier_portal_messages" not in existing:
        op.execute(
            """
            CREATE TABLE supplier_portal_messages (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id       UUID NOT NULL,
                supplier_id     UUID NOT NULL,
                message_type    VARCHAR(32) NOT NULL,
                subject         VARCHAR(256) NOT NULL,
                body            TEXT NOT NULL,
                metadata        JSONB,
                read_at         TIMESTAMPTZ,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )

        op.execute("ALTER TABLE supplier_portal_messages ENABLE ROW LEVEL SECURITY")

        op.execute(
            """
            CREATE POLICY supplier_portal_messages_tenant_isolation
            ON supplier_portal_messages
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )

        # 索引：supplier inbox 主查询路径（供应商门户按创建时间倒序）
        op.execute(
            """
            CREATE INDEX idx_supplier_portal_messages_supplier_created
            ON supplier_portal_messages (tenant_id, supplier_id, created_at DESC)
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "supplier_portal_messages" in existing:
        op.execute("DROP TABLE supplier_portal_messages CASCADE")
