"""v439 — certificate_types 字典表（PRD-12 资质证件类型字典 / Phase 3 W13 / Tier 1 邻接）

业务背景：
  PRD-01 supplier_certificates.cert_type 是 VARCHAR(48) 自由文本，缺乏统一字典管控。
  本次新建 certificate_types 字典表（租户级），为 web-admin 提供证件类型 CRUD UI，
  使证件录入从自由文本升级为受控下拉选择（允许 fallback 自定义输入）。

  松耦合设计：不加 FK 约束（supplier_certificates.cert_type 继续存字符串），
  字典仅辅助标准化，符合 feedback_graceful_degradation_pattern.md 原则。

设计要点：
  - 软删除：is_deleted BOOLEAN（list 默认过滤）
  - 唯一约束（partial index）：同租户同名（未软删除）不可重复；软删除后允许新建同名
  - RLS 四联（ENABLE + FORCE + POLICY + WITH CHECK），与 v435/v438 同模式
  - applicable_supplier_kinds JSONB array（无 CHECK 约束，允许业务自定义值）
  - validity_period_days NULL = 长期有效
  - inspector-and-skip 模式（与 v421+ 一致，idempotent 防 dry-run 重跑）

Migration 链：
  v438_cost_attribution_summary → v439_certificate_types (本 PR)
  v440 预留给 PRD-16（Lane B.2，尚未启动）

Revision ID: v439_certificate_types
Revises: v438_cost_attribution_summary
Create Date: 2026-05-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v439_certificate_types"
down_revision: Union[str, Sequence[str], None] = "v438_cost_attribution_summary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ─────────────────────────────────────────────────────────────────────────
    # 1. certificate_types 字典表
    # ─────────────────────────────────────────────────────────────────────────
    if "certificate_types" not in existing:
        op.execute(
            """
            CREATE TABLE certificate_types (
                id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id                   UUID NOT NULL,
                name                        VARCHAR(100) NOT NULL,
                applicable_supplier_kinds   JSONB NOT NULL DEFAULT '["all"]'::jsonb,
                validity_period_days        INTEGER,
                is_required                 BOOLEAN NOT NULL DEFAULT TRUE,
                is_deleted                  BOOLEAN NOT NULL DEFAULT FALSE,
                created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        op.execute("ALTER TABLE certificate_types ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE certificate_types FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY certificate_types_tenant_isolation
            ON certificate_types
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        # 同租户同名（未软删除）唯一约束：软删除后允许新建同名
        op.execute(
            """
            CREATE UNIQUE INDEX uq_cert_types_name
            ON certificate_types (tenant_id, name)
            WHERE is_deleted = FALSE
            """
        )
        # 主查询入口：租户 + 名称（list endpoint 主路径）
        op.execute(
            """
            CREATE INDEX idx_cert_types_tenant_name
            ON certificate_types (tenant_id, name)
            WHERE is_deleted = FALSE
            """
        )
        # 时序索引：创建时间倒序（新建后列表第一）
        op.execute(
            """
            CREATE INDEX idx_cert_types_tenant_created_at
            ON certificate_types (tenant_id, created_at DESC)
            WHERE is_deleted = FALSE
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS certificate_types")
