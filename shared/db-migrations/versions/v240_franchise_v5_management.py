"""加盟商管理闭环 v5 — 档案/费用收缴/公共代码 三表扩展
Tables: franchisees（升级，补 contract_start_date/end_date）
        franchise_fees（升级，补 overdue_days 计算）
        franchise_common_codes（新建）

Revision ID: v240
Revises: v239
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v240"
down_revision = "v239"
branch_labels = None
depends_on = None

# 标准安全 RLS 条件（NULLIF 保护，与 v231 规范一致）
_RLS_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()


    # ------------------------------------------------------------------
    # 表1：franchise_common_codes（公共代码管理 — 新建）
    # ------------------------------------------------------------------

    if 'franchise_common_codes' not in existing:
        op.create_table(
            "franchise_common_codes",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("code_type", sa.String(50), nullable=False,
                      comment="编码类型：material（物料）/ dish（菜品）/ price（价格）"),
            sa.Column("code_no", sa.String(100), nullable=False,
                      comment="编码编号，在 tenant 内唯一"),
            sa.Column("name", sa.String(200), nullable=False,
                      comment="编码名称"),
            sa.Column("description", sa.Text, nullable=True,
                      comment="编码说明"),
            sa.Column("unit", sa.String(30), nullable=True,
                      comment="单位（物料/菜品用）"),
            sa.Column("price_fen", sa.Integer, nullable=True,
                      comment="参考价格（分，price类型用）"),
            sa.Column("applicable_stores", JSONB, nullable=True,
                      server_default=sa.text("'[]'::jsonb"),
                      comment="适用门店ID列表，空数组=全部门店"),
            sa.Column("is_synced", sa.Boolean, nullable=False,
                      server_default=sa.text("false"),
                      comment="是否已同步到加盟门店"),
            sa.Column("synced_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("status", sa.String(20), nullable=False,
                      server_default=sa.text("'active'"),
                      comment="active / deprecated"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                      server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                      server_default=sa.text("NOW()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False,
                      server_default=sa.text("false")),
        )
        op.create_index("ix_franchise_common_codes_tenant",
                        "franchise_common_codes", ["tenant_id"])
        op.create_index("ix_franchise_common_codes_type",
                        "franchise_common_codes", ["code_type"])
        op.create_index("ix_franchise_common_codes_no",
                        "franchise_common_codes", ["tenant_id", "code_no"],
                        unique=True,
                        postgresql_where=sa.text("is_deleted = false"))

        # RLS Policy
        op.execute("ALTER TABLE franchise_common_codes ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY franchise_common_codes_tenant_isolation
            ON franchise_common_codes
            USING ({_RLS_COND})
        """)

        # ------------------------------------------------------------------
        # 表2：franchisees — 补充合同有效期字段（如表已存在，只加列）
        # ------------------------------------------------------------------
        for col_name, col_type, nullable, default in [
            ("contract_start_date", "DATE", True, None),
            ("contract_end_date",   "DATE", True, None),
            ("contract_file_url",   "TEXT", True, None),
            ("brand_id",            "UUID", True, None),
        ]:
            try:
                kwargs: dict = {}
                if default is not None:
                    kwargs["server_default"] = sa.text(default)
                op.add_column(
                    "franchisees",
                    sa.Column(col_name, sa.text(col_type),
                              nullable=nullable, **kwargs),
                )
            except Exception:
                pass  # 列已存在，跳过

        # ------------------------------------------------------------------
        # 表3：franchise_fees — 补充 overdue_days 字段
        # ------------------------------------------------------------------
        try:
            op.add_column(
                "franchise_fees",
                sa.Column("overdue_days", sa.Integer, nullable=True,
                          comment="逾期天数，由应用层计算写入"),
            )
        except Exception:
            pass


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS franchise_common_codes_tenant_isolation ON franchise_common_codes")
    op.drop_table("franchise_common_codes")
    for col in ["contract_start_date", "contract_end_date", "contract_file_url", "brand_id"]:
        try:
            op.drop_column("franchisees", col)
        except Exception:
            pass
    try:
        op.drop_column("franchise_fees", "overdue_days")
    except Exception:
        pass
