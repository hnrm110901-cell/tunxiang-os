"""v162 — 增长营销策略表

新增四张表：
  brand_strategies    — 品牌策略（定位/调性/价格带/招牌菜等）
  banners             — 营销横幅（展示计数/点击计数内建）
  journeys            — 营销旅程定义
  journey_executions  — 旅程执行日志

RLS 策略：NULLIF(current_setting('app.tenant_id', true), '')::uuid 标准安全模式。

Revision ID: v162
Revises: v161
Create Date: 2026-04-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v162"
down_revision = "v161"
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

    # ── brand_strategies 品牌策略 ────────────────────────────────────────
    if "brand_strategies" not in _existing:
        op.create_table(
            "brand_strategies",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("brand_id", sa.String(100), nullable=False),
            sa.Column("positioning", sa.Text, nullable=True),
            sa.Column("tone", sa.String(200), nullable=True),
            sa.Column(
                "target_audience",
                JSONB,
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
                comment="目标客群列表",
            ),
            sa.Column(
                "price_range",
                JSONB,
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
                comment="{min_fen, max_fen, avg_fen}",
            ),
            sa.Column(
                "signature_dishes",
                JSONB,
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
                comment="招牌菜列表",
            ),
            sa.Column(
                "seasonal_plans",
                JSONB,
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
                comment="季节计划列表",
            ),
            sa.Column(
                "promo_boundaries",
                JSONB,
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
                comment="促销边界 {max_discount_pct, margin_floor_pct}",
            ),
            sa.Column(
                "forbidden_expressions",
                JSONB,
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
                comment="禁用表达列表",
            ),
            sa.Column(
                "is_deleted",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("FALSE"),
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint("tenant_id", "brand_id", name="uq_brand_strategies_tenant_brand"),
        )

    op.execute("CREATE INDEX IF NOT EXISTS ix_brand_strategies_tenant ON brand_strategies (tenant_id)")
    _apply_rls("brand_strategies")

    # ── banners 营销横幅 ─────────────────────────────────────────────────
    if "banners" not in _existing:
        op.create_table(
            "banners",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column(
                "banner_type",
                sa.String(50),
                nullable=False,
                comment="hero/promotion/announcement/campaign",
            ),
            sa.Column("image_url", sa.Text, nullable=True),
            sa.Column("link_url", sa.Text, nullable=True),
            sa.Column(
                "target_segment",
                JSONB,
                nullable=True,
                comment="目标客群条件",
            ),
            sa.Column(
                "display_order",
                sa.Integer,
                nullable=False,
                server_default="0",
            ),
            sa.Column("start_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("end_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column(
                "is_active",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("TRUE"),
            ),
            sa.Column(
                "impression_count",
                sa.Integer,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "click_count",
                sa.Integer,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "is_deleted",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("FALSE"),
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    op.execute("CREATE INDEX IF NOT EXISTS ix_banners_tenant_active ON banners (tenant_id, is_active, display_order)")
    _apply_rls("banners")

    # ── journeys 营销旅程定义 ─────────────────────────────────────────────
    if "journeys" not in _existing:
        op.create_table(
            "journeys",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column(
                "journey_type",
                sa.String(50),
                nullable=False,
                comment="retention/activation/conversion/reactivation",
            ),
            sa.Column(
                "trigger",
                JSONB,
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
                comment="触发条件 {type, params}",
            ),
            sa.Column(
                "nodes",
                JSONB,
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
                comment="节点列表",
            ),
            sa.Column("target_segment_id", sa.String(100), nullable=True),
            sa.Column(
                "status",
                sa.String(30),
                nullable=False,
                server_default="draft",
                comment="draft/active/paused/archived",
            ),
            sa.Column(
                "stats",
                JSONB,
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
                comment="activated/converted/revenue 等统计",
            ),
            sa.Column(
                "is_deleted",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("FALSE"),
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    op.execute("CREATE INDEX IF NOT EXISTS ix_journeys_tenant_status ON journeys (tenant_id, status)")
    _apply_rls("journeys")

    # ── journey_executions 旅程执行日志 ──────────────────────────────────
    if "journey_executions" not in _existing:
        op.create_table(
            "journey_executions",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "journey_id",
                UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column("member_id", sa.String(100), nullable=False),
            sa.Column("trigger_event", sa.String(100), nullable=True),
            sa.Column("current_node_id", sa.String(100), nullable=True),
            sa.Column(
                "status",
                sa.String(30),
                nullable=False,
                server_default="running",
                comment="running/completed/failed",
            ),
            sa.Column(
                "started_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("result", JSONB, nullable=True),
            sa.Column(
                "is_deleted",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("FALSE"),
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["journey_id"],
                ["journeys.id"],
                name="fk_journey_executions_journey_id",
            ),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_journey_executions_tenant_journey ON journey_executions (tenant_id, journey_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_journey_executions_tenant_member ON journey_executions (tenant_id, member_id)"
    )
    _apply_rls("journey_executions")


def downgrade() -> None:
    # 按依赖顺序逆向删除
    for table in [
        "journey_executions",
        "journeys",
        "banners",
        "brand_strategies",
    ]:
        for policy in ["rls_delete", "rls_update", "rls_insert", "rls_select"]:
            op.execute(f"DROP POLICY IF EXISTS {table}_{policy} ON {table}")
        op.drop_table(table)
