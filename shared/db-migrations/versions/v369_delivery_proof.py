"""v369: 配送电子签收 + 损坏拍照取证（TASK-4）

新增三张表 + 1 列扩展：

  delivery_receipts             — 电子签收单（一个配送单仅一份）
  delivery_damage_records       — 配送损坏记录（多条）
  delivery_attachments          — 附件（照片/视频，关联 RECEIPT 或 DAMAGE）

  + ALTER store_receiving_confirmations ADD COLUMN receipt_id UUID
    （把签收单ID 反写到 v062 已有的收货确认表，便于追溯）

RLS：每张新表启用 + FORCE，使用 SAFE 策略 NULLIF(current_setting,'')::uuid。
updated_at：通过 server_default + onupdate trigger 自动维护。

Revision ID: v369_delivery_proof
Revises: v365_forge_ecosystem_metrics
Create Date: 2026-04-27
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "v369_delivery_proof"
down_revision: Union[str, None] = "v365_forge_ecosystem_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"

_NEW_TABLES = (
    "delivery_receipts",
    "delivery_damage_records",
    "delivery_attachments",
)


def _enable_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    for action, clause in [
        ("select", f"FOR SELECT USING ({_RLS_CONDITION})"),
        ("insert", f"FOR INSERT WITH CHECK ({_RLS_CONDITION})"),
        ("update", f"FOR UPDATE USING ({_RLS_CONDITION}) WITH CHECK ({_RLS_CONDITION})"),
        ("delete", f"FOR DELETE USING ({_RLS_CONDITION})"),
    ]:
        op.execute(
            f"CREATE POLICY {table_name}_rls_{action} ON {table_name} "
            f"AS PERMISSIVE {clause}"
        )


def _disable_rls(table_name: str) -> None:
    for suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {table_name}_rls_{suffix} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def _create_updated_at_trigger(table_name: str) -> None:
    """为表创建 updated_at 自动维护 trigger。

    依赖共享函数 set_updated_at()；若不存在则就地创建。
    """
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
          NEW.updated_at = NOW();
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute(
        f"CREATE TRIGGER trg_{table_name}_updated_at "
        f"BEFORE UPDATE ON {table_name} "
        f"FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def _drop_updated_at_trigger(table_name: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_updated_at ON {table_name}")


def upgrade() -> None:
    # ─── 1. delivery_receipts ──────────────────────────────────────────
    op.create_table(
        "delivery_receipts",
        sa.Column(
            "id", UUID(as_uuid=True),
            primary_key=True, server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_id", UUID(as_uuid=True), nullable=False,
                  comment="关联 distribution_orders.id"),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False),
        sa.Column("signer_name", sa.String(64), nullable=False),
        sa.Column("signer_role", sa.String(32), nullable=True,
                  comment="STORE_MANAGER|RECEIVER|OTHER"),
        sa.Column("signer_phone", sa.String(32), nullable=True),
        sa.Column(
            "signed_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.Column("signature_image_url", sa.Text, nullable=False,
                  comment="对象存储 URL（s3://bucket/path）"),
        sa.Column("signature_location_lat", sa.Numeric(10, 7), nullable=True),
        sa.Column("signature_location_lng", sa.Numeric(10, 7), nullable=True),
        sa.Column("device_info", JSONB, nullable=True,
                  server_default=sa.text("'{}'::jsonb"),
                  comment="{model, os, app_version}"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "delivery_id",
            name="uq_delivery_receipts_tenant_delivery",
        ),
    )
    op.create_index(
        "ix_delivery_receipts_tenant_store",
        "delivery_receipts",
        ["tenant_id", "store_id"],
    )
    op.create_index(
        "ix_delivery_receipts_tenant_signed_at",
        "delivery_receipts",
        ["tenant_id", sa.text("signed_at DESC")],
    )
    _enable_rls("delivery_receipts")
    _create_updated_at_trigger("delivery_receipts")

    # ─── 2. delivery_damage_records ────────────────────────────────────
    op.create_table(
        "delivery_damage_records",
        sa.Column(
            "id", UUID(as_uuid=True),
            primary_key=True, server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_id", UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", UUID(as_uuid=True), nullable=True,
                  comment="配送单中的具体 SKU 行ID（业务侧自定义）"),
        sa.Column("ingredient_id", UUID(as_uuid=True), nullable=True),
        sa.Column("batch_no", sa.String(64), nullable=True),
        sa.Column("damage_type", sa.String(24), nullable=False,
                  comment="BROKEN|SPOILED|WRONG_SPEC|WRONG_QTY|EXPIRED|OTHER"),
        sa.Column("damaged_qty", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit_cost_fen", sa.BigInteger, nullable=True,
                  comment="单价（分），用于计算损失金额"),
        sa.Column(
            "damage_amount_fen",
            sa.BigInteger,
            sa.Computed(
                "CASE WHEN unit_cost_fen IS NULL THEN NULL "
                "ELSE (damaged_qty * unit_cost_fen)::BIGINT END",
                persisted=True,
            ),
            nullable=True,
            comment="损失金额（分）= damaged_qty * unit_cost_fen",
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "severity", sa.String(16),
            nullable=False, server_default=sa.text("'MINOR'"),
            comment="MINOR|MAJOR|CRITICAL",
        ),
        sa.Column("reported_by", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "reported_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"), nullable=False,
        ),
        sa.Column(
            "resolution_status", sa.String(16),
            nullable=False, server_default=sa.text("'PENDING'"),
            comment="PENDING|RETURNED|COMPENSATED|ACCEPTED",
        ),
        sa.Column("resolved_by", UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("resolve_action", sa.String(32), nullable=True),
        sa.Column("resolve_comment", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "is_deleted", sa.Boolean,
            server_default=sa.text("false"), nullable=False,
        ),
    )
    op.create_index(
        "ix_delivery_damage_tenant_delivery",
        "delivery_damage_records",
        ["tenant_id", "delivery_id"],
    )
    op.create_index(
        "ix_delivery_damage_tenant_status",
        "delivery_damage_records",
        ["tenant_id", "resolution_status"],
    )
    op.create_index(
        "ix_delivery_damage_tenant_severity",
        "delivery_damage_records",
        ["tenant_id", "severity"],
    )
    _enable_rls("delivery_damage_records")
    _create_updated_at_trigger("delivery_damage_records")

    # ─── 3. delivery_attachments ───────────────────────────────────────
    op.create_table(
        "delivery_attachments",
        sa.Column(
            "id", UUID(as_uuid=True),
            primary_key=True, server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "entity_type", sa.String(16), nullable=False,
            comment="RECEIPT|DAMAGE",
        ),
        sa.Column(
            "entity_id", UUID(as_uuid=True), nullable=False,
            comment="对应 delivery_receipts.id 或 delivery_damage_records.id",
        ),
        sa.Column("file_url", sa.Text, nullable=False),
        sa.Column("file_type", sa.String(32), nullable=True,
                  comment="image/jpeg|image/png|video/mp4"),
        sa.Column("file_size", sa.BigInteger, nullable=True),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("thumbnail_url", sa.Text, nullable=True),
        sa.Column("captured_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("gps_lat", sa.Numeric(10, 7), nullable=True),
        sa.Column("gps_lng", sa.Numeric(10, 7), nullable=True),
        sa.Column("uploaded_by", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "uploaded_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_delivery_attachments_tenant_entity",
        "delivery_attachments",
        ["tenant_id", "entity_type", "entity_id"],
    )
    _enable_rls("delivery_attachments")
    _create_updated_at_trigger("delivery_attachments")

    # ─── 4. 反写：在 store_receiving_confirmations 上加 receipt_id 列 ──
    # 仅当 v062 表已存在时执行（保持迁移在缺表场景下不炸）
    op.execute("""
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'store_receiving_confirmations'
          ) THEN
            ALTER TABLE store_receiving_confirmations
              ADD COLUMN IF NOT EXISTS receipt_id UUID NULL;
            CREATE INDEX IF NOT EXISTS ix_src_receipt_id
              ON store_receiving_confirmations (tenant_id, receipt_id);
          END IF;
        END $$;
    """)


def downgrade() -> None:
    # 1. 反写列下线
    op.execute("""
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'store_receiving_confirmations'
          ) THEN
            DROP INDEX IF EXISTS ix_src_receipt_id;
            ALTER TABLE store_receiving_confirmations
              DROP COLUMN IF EXISTS receipt_id;
          END IF;
        END $$;
    """)

    # 2. 删表（含 trigger / RLS）
    for table in reversed(_NEW_TABLES):
        _drop_updated_at_trigger(table)
        _disable_rls(table)
        op.drop_table(table)
