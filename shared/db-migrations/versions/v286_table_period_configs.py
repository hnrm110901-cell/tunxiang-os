"""v286 — 桌台×时段配置矩阵（TablePeriodConfig）

同一张桌台在不同市别可以有不同属性：
- 午市大厅2人桌保持原样（快翻台），晚市改为4人桌配置（拼桌后）
- 午市包间关闭（节省人力），晚市开放且最低消费3000元
- 早茶时段露台开放下午茶菜单，其他时段关闭

配置优先级：table_id 级 > zone_id 级 > 门店默认

Revision ID: v286
Revises: v285
Create Date: 2026-04-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "v286b"
down_revision: Union[str, None] = "v285"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "table_period_configs"


def _enable_rls(table_name: str) -> None:
    """启用 RLS + 租户隔离策略（与 v149 保持一致）"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table_name} ON {table_name} "
        f"USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)"
    )
    op.execute(
        f"CREATE POLICY tenant_insert_{table_name} ON {table_name} "
        f"FOR INSERT WITH CHECK "
        f"(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)"
    )


def _disable_rls(table_name: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_insert_{table_name} ON {table_name}")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table_name} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # ── table_period_configs — 桌台×时段配置矩阵 ─────────────────────────
    op.create_table(
        TABLE,
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "table_id", UUID(as_uuid=True),
            sa.ForeignKey("tables.id"), nullable=True,
            comment="单桌配置（优先级高于 zone_id）",
        ),
        sa.Column(
            "zone_id", UUID(as_uuid=True),
            sa.ForeignKey("table_zones.id"), nullable=True,
            comment="区域配置（批量设置）",
        ),
        sa.Column(
            "market_session_id", UUID(as_uuid=True), nullable=False,
            comment="关联市别",
        ),
        sa.Column(
            "is_available", sa.Boolean, nullable=False, server_default="true",
            comment="该时段是否开放",
        ),
        sa.Column(
            "effective_seats", sa.Integer, nullable=True,
            comment="该时段可用座位数（覆盖物理座位数）",
        ),
        sa.Column(
            "time_limit_min", sa.Integer, nullable=True,
            comment="该时段用餐时限（分钟，覆盖区域/门店默认值）",
        ),
        sa.Column(
            "service_mode_override", sa.String(20), nullable=True,
            comment="覆盖区域服务模式（如午市大厅=scan_and_pay，晚市=dine_first）",
        ),
        sa.Column(
            "pricing_override", JSONB, server_default="'{}'",
            comment="时段定价覆盖：{min_consumption_fen, room_fee_fen, surcharge_rate}",
        ),
        sa.Column(
            "target_metrics", JSONB, server_default="'{}'",
            comment="时段经营目标：{target_turnover_rate, target_avg_spend_fen, target_duration_min}",
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),

        # CHECK: 至少指定一个配置范围
        sa.CheckConstraint(
            "table_id IS NOT NULL OR zone_id IS NOT NULL",
            name="chk_tpc_scope_required",
        ),
    )

    # ── 索引 ────────────────────────────────────────────────────────────
    op.execute("""
        CREATE INDEX idx_tpc_store_market
        ON table_period_configs (store_id, market_session_id)
        WHERE is_active = TRUE AND is_deleted = FALSE
    """)
    op.execute("""
        CREATE INDEX idx_tpc_table
        ON table_period_configs (table_id, market_session_id)
        WHERE table_id IS NOT NULL AND is_active = TRUE AND is_deleted = FALSE
    """)
    op.execute("""
        CREATE INDEX idx_tpc_zone
        ON table_period_configs (zone_id, market_session_id)
        WHERE zone_id IS NOT NULL AND is_active = TRUE AND is_deleted = FALSE
    """)

    # ── RLS ──────────────────────────────────────────────────────────────
    _enable_rls(TABLE)


def downgrade() -> None:
    _disable_rls(TABLE)
    op.drop_table(TABLE)
