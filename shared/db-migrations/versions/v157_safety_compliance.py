"""v157 — 食安巡检专项表（结构化巡检记录）

新增三张表：
  biz_food_safety_inspections  — 食安巡检记录（每次巡检的元信息）
  biz_food_safety_items        — 巡检项目明细（每项打分/整改）
  biz_food_safety_templates    — 巡检模板（门店/品牌可配置）

RLS 策略：NULLIF(current_setting('app.tenant_id', true), '')::uuid 标准安全模式。

Revision ID: v157
Revises: v156
  （注意：v156 由 Team B 创建 finance_receivables 表；如 v156 不存在，
   请将 down_revision 改为 "v155"）
Create Date: 2026-04-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v157"
down_revision = "v156"
branch_labels = None
depends_on = None

_SAFE_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def _apply_rls(table_name: str) -> None:
    """标准三段式 RLS：ENABLE → FORCE → 四条策略"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table_name}_rls_select ON {table_name} FOR SELECT USING ({_SAFE_CONDITION})")
    op.execute(f"CREATE POLICY {table_name}_rls_insert ON {table_name} FOR INSERT WITH CHECK ({_SAFE_CONDITION})")
    op.execute(
        f"CREATE POLICY {table_name}_rls_update ON {table_name} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(f"CREATE POLICY {table_name}_rls_delete ON {table_name} FOR DELETE USING ({_SAFE_CONDITION})")


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── biz_food_safety_inspections 巡检记录 ──────────────────────────────
    if "biz_food_safety_inspections" not in _existing:
        op.create_table(
            "biz_food_safety_inspections",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("inspector_id", UUID(as_uuid=True), nullable=False, comment="巡检员（sys_staff）"),
            sa.Column(
                "inspection_type", sa.Text, nullable=False, comment="daily_open/daily_close/weekly/surprise/government"
            ),
            sa.Column("inspection_date", sa.Date, nullable=False),
            sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("overall_score", sa.Numeric(5, 2), nullable=True, comment="综合评分（0-100）"),
            sa.Column(
                "status",
                sa.Text,
                nullable=False,
                server_default="pending",
                comment="pending/in_progress/completed/failed",
            ),
            sa.Column("pass_threshold", sa.Numeric(5, 2), nullable=False, server_default="80.0"),
            sa.Column("is_passed", sa.Boolean, nullable=True, comment="NULL=未完成，true=合格，false=不合格"),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        )

    op.execute("CREATE INDEX IF NOT EXISTS ix_fsi_tenant_store ON biz_food_safety_inspections (tenant_id, store_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fsi_tenant_date ON biz_food_safety_inspections (tenant_id, inspection_date)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_fsi_tenant_status ON biz_food_safety_inspections (tenant_id, status)")
    _apply_rls("biz_food_safety_inspections")

    # ── biz_food_safety_items 巡检项目明细 ───────────────────────────────
    if "biz_food_safety_items" not in _existing:
        op.create_table(
            "biz_food_safety_items",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "inspection_id", UUID(as_uuid=True), nullable=False, comment="ref: biz_food_safety_inspections.id"
            ),
            sa.Column("item_code", sa.Text, nullable=False, comment="巡检项目编号，如 FS001-FS030"),
            sa.Column("item_name", sa.Text, nullable=False, comment="巡检项目名称"),
            sa.Column("category", sa.Text, nullable=False, comment="食材管理/烹饪操作/设备卫生/人员卫生/储存管理"),
            sa.Column("weight", sa.Numeric(5, 2), nullable=False, server_default="1.0", comment="权重"),
            sa.Column("score", sa.Numeric(5, 2), nullable=True, comment="得分（NULL=未检查）"),
            sa.Column(
                "is_critical",
                sa.Boolean,
                nullable=False,
                server_default="false",
                comment="是否关键项（不合格直接不通过）",
            ),
            sa.Column("result", sa.Text, nullable=True, comment="pass/fail/na（不适用）"),
            sa.Column("photo_url", sa.Text, nullable=True, comment="问题照片"),
            sa.Column("issue_description", sa.Text, nullable=True, comment="问题描述"),
            sa.Column("corrective_action", sa.Text, nullable=True, comment="整改措施"),
            sa.Column("corrected_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="整改完成时间"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fsitems_tenant_inspection ON biz_food_safety_items (tenant_id, inspection_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fsitems_critical "
        "ON biz_food_safety_items (tenant_id, inspection_id, is_critical)"
    )
    _apply_rls("biz_food_safety_items")

    # ── biz_food_safety_templates 巡检模板 ──────────────────────────────
    if "biz_food_safety_templates" not in _existing:
        op.create_table(
            "biz_food_safety_templates",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("brand_id", UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.Text, nullable=False, comment="模板名称，如：标准日检模板"),
            sa.Column("inspection_type", sa.Text, nullable=False),
            sa.Column("items", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb"), comment="巡检项目列表"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        )

    op.execute("CREATE INDEX IF NOT EXISTS ix_fst_tenant_brand ON biz_food_safety_templates (tenant_id, brand_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fst_tenant_type ON biz_food_safety_templates (tenant_id, inspection_type)"
    )
    _apply_rls("biz_food_safety_templates")


def downgrade() -> None:
    for table in [
        "biz_food_safety_templates",
        "biz_food_safety_items",
        "biz_food_safety_inspections",
    ]:
        for policy in ["rls_delete", "rls_update", "rls_insert", "rls_select"]:
            op.execute(f"DROP POLICY IF EXISTS {table}_{policy} ON {table}")
        op.drop_table(table)
