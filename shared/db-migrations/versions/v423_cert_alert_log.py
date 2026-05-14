"""v423 — cert_alert_log：证件临期推送记录表（PR-01B sub-PR B / PRD-01）

业务背景：
  PR-01A 建立 supplier_certificates 证件表（v421）。
  本 migration 建立推送记录表，用于证件临期/过期 alerter 去重查询。
  UNIQUE (cert_id, alert_threshold, channel) 保证同一证件同一阈值同一通道
  每轮 scan 只推一次（D-30/D-15/D-7 各一次 + D+0 起每天一次）。

设计要点：
  1. cert_alert_log — 每次推送落一行，含通道、阈值、成功/失败
  2. UNIQUE 约束 (cert_id, alert_threshold, channel) — alerter 幂等去重
  3. RLS：tenant_id::text = current_setting('app.tenant_id', true)（标准模式）
  4. inspector-and-skip 防重运行（参考 v421 / v422 模式）

Revision ID: v423_cert_alert_log
Revises: v422_doc_number_wave2_backfill
Create Date: 2026-05-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v423_cert_alert_log"
down_revision: Union[str, Sequence[str], None] = "v422_doc_number_wave2_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "cert_alert_log" not in existing:
        op.execute(
            """
            CREATE TABLE cert_alert_log (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id       UUID NOT NULL,
                cert_id         UUID NOT NULL REFERENCES supplier_certificates(id),
                alert_threshold VARCHAR(16) NOT NULL,
                channel         VARCHAR(32) NOT NULL,
                sent_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                success         BOOLEAN NOT NULL,
                error_msg       TEXT,
                CONSTRAINT uq_cert_alert_log_cert_threshold_channel
                    UNIQUE (cert_id, alert_threshold, channel)
            )
            """
        )

        op.execute("ALTER TABLE cert_alert_log ENABLE ROW LEVEL SECURITY")

        op.execute(
            """
            CREATE POLICY cert_alert_log_tenant_isolation
            ON cert_alert_log
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )

        # 索引：推送历史按时间查（食安总监查询近期告警记录）
        op.execute(
            """
            CREATE INDEX idx_cert_alert_log_tenant_sent_at
            ON cert_alert_log (tenant_id, sent_at DESC)
            """
        )

        # 索引：幂等检查路径（alerter 每次 scan 主查询）
        op.execute(
            """
            CREATE INDEX idx_cert_alert_log_cert_threshold
            ON cert_alert_log (cert_id, alert_threshold)
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "cert_alert_log" in existing:
        op.execute("DROP TABLE cert_alert_log CASCADE")
