"""v024: 新增 brand_groups 集团品牌组配置表

集团跨品牌管理：一个集团主租户管理多个品牌租户。
  - tenant_id：集团主租户 ID（与普通品牌 tenant_id 格式一致，但语义不同）
  - brand_tenant_ids：JSONB 存储旗下品牌 tenant_id 数组
  - group_code：UNIQUE 索引，集团唯一标识码
  - stored_value_interop / member_data_shared：跨品牌策略开关

RLS 策略：使用 v006+ 安全标准
  current_setting('app.tenant_id', TRUE) IS NOT NULL
  AND current_setting('app.tenant_id', TRUE) <> ''
  AND tenant_id = current_setting('app.tenant_id')::UUID

Revision ID: v024
Revises: v023
Create Date: 2026-03-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v024"
down_revision = "v023"
branch_labels = None
depends_on = None

_TABLE = "brand_groups"

# v006+ 安全 RLS 条件（统一标准）
_SAFE_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def upgrade() -> None:
    op.create_table(
        _TABLE,
        # ── 基础字段（TenantBase 标准）──────────────────────────────
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        # ── 集团专属字段 ─────────────────────────────────────────────
        sa.Column("group_name", sa.String(100), nullable=False, comment="集团名称"),
        sa.Column("group_code", sa.String(50), nullable=False, comment="集团唯一标识码"),
        sa.Column(
            "brand_tenant_ids",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="旗下品牌 tenant_id 列表（UUID 字符串数组）",
        ),
        sa.Column(
            "stored_value_interop",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="储值卡是否跨品牌互通",
        ),
        sa.Column(
            "member_data_shared",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="会员数据是否集团共享",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="'active'",
            comment="active | inactive",
        ),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True, comment="创建人"),
        sa.Column("updated_by", UUID(as_uuid=True), nullable=True, comment="最后更新人"),
        comment="品牌组配置（集团跨品牌管理）",
    )

    # ── 索引 ──────────────────────────────────────────────────────
    op.create_index(
        "idx_brand_group_tenant",
        _TABLE,
        ["tenant_id", "status"],
    )
    op.create_unique_constraint(
        "uq_brand_group_code",
        _TABLE,
        ["group_code"],
    )

    # ── RLS 策略（v006+ 安全标准） ────────────────────────────────
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")

    op.execute(f"CREATE POLICY {_TABLE}_rls_select ON {_TABLE} FOR SELECT USING ({_SAFE_CONDITION})")
    op.execute(f"CREATE POLICY {_TABLE}_rls_insert ON {_TABLE} FOR INSERT WITH CHECK ({_SAFE_CONDITION})")
    op.execute(
        f"CREATE POLICY {_TABLE}_rls_update ON {_TABLE} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(f"CREATE POLICY {_TABLE}_rls_delete ON {_TABLE} FOR DELETE USING ({_SAFE_CONDITION})")


def downgrade() -> None:
    for suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {_TABLE}_rls_{suffix} ON {_TABLE}")

    op.drop_index("idx_brand_group_tenant", table_name=_TABLE)
    op.drop_constraint("uq_brand_group_code", _TABLE, type_="unique")
    op.drop_table(_TABLE)
