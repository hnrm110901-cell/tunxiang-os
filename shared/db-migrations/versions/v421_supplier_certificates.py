"""v421 — supplier_certificates：供应商证件管理（PRD-01 食安合规）

业务背景：
  食品经营许可证 / 检验报告 / 健康证过期不发现 → 食药监突击检查 → 一店关停 + 全连锁停业整顿。
  徐记 200+ 供应商，证件 5+ 类，人工台账必漏。
  本表建立独立证件管理表（创始人 Q2 决策 2026-05-14 授权）。

设计要点：
  1. supplier_certificates — 存储每张证件：cert_type / expire_date / auto_block_on_expire
  2. 过期校验逻辑：is_supplier_blocked() 在收货入口阻断，续证后自动恢复（无需手动解锁）
  3. warning_days JSONB 支持多级预警（30/15/7 天），为 PR-01B alerter 预留
  4. RLS：tenant_id::text = current_setting('app.tenant_id', true)（标准 RLS 模式）
  5. inspector-and-skip 模式：已存在时跳过，幂等安全

Revision ID: v421_supplier_certificates
Revises: v418_doc_number_rules
Create Date: 2026-05-14

⚠ down_revision 说明：
  本 PR 使用 v418_doc_number_rules 作为 down_revision，避开与 PR-03B (v419) 的 alembic 链竞争。
  PR-03B merge 后本 PR rebase 时改为 v419_doc_number_wave1_backfill。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v421_supplier_certificates"
down_revision: Union[str, Sequence[str], None] = "v418_doc_number_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "supplier_certificates" not in existing:
        op.execute(
            """
            CREATE TABLE supplier_certificates (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id       UUID NOT NULL,
                supplier_id     UUID NOT NULL,
                cert_type       VARCHAR(48) NOT NULL,
                cert_number     VARCHAR(128) NOT NULL,
                issuer          VARCHAR(128),
                expire_date     DATE NOT NULL,
                warning_days    JSONB NOT NULL DEFAULT '[30, 15, 7]'::jsonb,
                auto_block_on_expire BOOLEAN NOT NULL DEFAULT TRUE,
                last_alert_sent_at   TIMESTAMPTZ,
                attachment_url  TEXT,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted      BOOLEAN NOT NULL DEFAULT FALSE
            )
            """
        )

        op.execute("ALTER TABLE supplier_certificates ENABLE ROW LEVEL SECURITY")

        # 租户隔离 RLS（参考 v296 模式）
        op.execute(
            """
            CREATE POLICY supplier_certificates_tenant_isolation
            ON supplier_certificates
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )

        # 索引：收货阻断主查询路径（supplier_id + cert_type + expire_date）
        op.execute(
            """
            CREATE INDEX idx_supplier_certs_supplier
            ON supplier_certificates (tenant_id, supplier_id, cert_type)
            """
        )

        # 索引：即将过期预警查询路径（expire_date 范围扫描，只看未删除记录）
        op.execute(
            """
            CREATE INDEX idx_supplier_certs_expire
            ON supplier_certificates (tenant_id, expire_date)
            WHERE is_deleted = FALSE
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "supplier_certificates" in existing:
        op.execute("DROP TABLE supplier_certificates CASCADE")
