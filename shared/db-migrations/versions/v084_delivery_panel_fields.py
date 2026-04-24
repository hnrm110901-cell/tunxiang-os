"""v032: 外卖聚合接单面板字段补充 + delivery_auto_accept_rules 表

在 delivery_orders 表添加接单面板所需字段：
  - platform_order_no: 平台展示给用户的订单号
  - special_request: 特殊备注
  - estimated_prep_time: 预计备餐分钟数
  - auto_accepted: 是否自动接单
  - accepted_at: 接单时间
  - rejected_at: 拒单时间
  - rejected_reason: 拒单原因
  - customer_name: 顾客姓名（v009已有customer_phone，补充name）
  - actual_revenue_fen: 实际到账金额（分）

状态值补充说明（status 字段新增 'pending_accept'）：
  原有: confirmed/preparing/ready/delivering/completed/cancelled/refunded
  新增: 'pending_accept' 作为接单前的等待状态

新增表 delivery_auto_accept_rules：
  自动接单规则配置（每门店）

Revision ID: v032
Revises: v031
Create Date: 2026-03-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v084"
down_revision= "v083"
branch_labels= None
depends_on= None

_DELIVERY_TABLE = "delivery_orders"
_AUTO_ACCEPT_TABLE = "delivery_auto_accept_rules"

_SAFE_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def _enable_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table_name}_rls_select ON {table_name} "
        f"FOR SELECT USING ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table_name}_rls_insert ON {table_name} "
        f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table_name}_rls_update ON {table_name} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table_name}_rls_delete ON {table_name} "
        f"FOR DELETE USING ({_SAFE_CONDITION})"
    )


def _disable_rls(table_name: str) -> None:
    for suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {table_name}_rls_{suffix} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # ── 1. 在 delivery_orders 补充接单面板所需字段 ──────────────────────────
    op.add_column(
        _DELIVERY_TABLE,
        sa.Column("platform_order_no", sa.String(100), nullable=True,
                  comment="平台展示给用户的订单号"),
    )
    op.add_column(
        _DELIVERY_TABLE,
        sa.Column("customer_name", sa.String(50), nullable=True,
                  comment="顾客姓名"),
    )
    op.add_column(
        _DELIVERY_TABLE,
        sa.Column("special_request", sa.Text(), nullable=True,
                  comment="顾客特殊备注"),
    )
    op.add_column(
        _DELIVERY_TABLE,
        sa.Column("estimated_prep_time", sa.Integer(), nullable=True,
                  comment="预计备餐分钟数"),
    )
    op.add_column(
        _DELIVERY_TABLE,
        sa.Column("actual_revenue_fen", sa.Integer(), nullable=True,
                  comment="实际到账金额（分），= total_fen - commission_fen"),
    )
    op.add_column(
        _DELIVERY_TABLE,
        sa.Column(
            "auto_accepted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="是否由自动接单规则接单",
        ),
    )
    op.add_column(
        _DELIVERY_TABLE,
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True,
                  comment="接单时间"),
    )
    op.add_column(
        _DELIVERY_TABLE,
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True,
                  comment="拒单时间"),
    )
    op.add_column(
        _DELIVERY_TABLE,
        sa.Column("rejected_reason", sa.String(500), nullable=True,
                  comment="拒单原因"),
    )

    # ── 2. 新建 delivery_auto_accept_rules 表 ────────────────────────────────
    op.create_table(
        _AUTO_ACCEPT_TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="是否启用自动接单",
        ),
        sa.Column("business_hours_start", sa.Time(), nullable=True,
                  comment="自动接单营业开始时间"),
        sa.Column("business_hours_end", sa.Time(), nullable=True,
                  comment="自动接单营业结束时间"),
        sa.Column(
            "max_concurrent_orders",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("10"),
            comment="同时最多自动接多少单（活跃中的 accepted/preparing 订单）",
        ),
        sa.Column(
            "excluded_platforms",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="不自动接单的平台列表，如 [\"meituan\"]",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "store_id", name="uq_auto_accept_rule_store"),
        comment="外卖自动接单规则（每门店一条）",
    )

    _enable_rls(_AUTO_ACCEPT_TABLE)


def downgrade() -> None:
    # 删除新表
    _disable_rls(_AUTO_ACCEPT_TABLE)
    op.drop_table(_AUTO_ACCEPT_TABLE)

    # 移除新增字段
    for col in (
        "platform_order_no",
        "customer_name",
        "special_request",
        "estimated_prep_time",
        "actual_revenue_fen",
        "auto_accepted",
        "accepted_at",
        "rejected_at",
        "rejected_reason",
    ):
        op.drop_column(_DELIVERY_TABLE, col)
