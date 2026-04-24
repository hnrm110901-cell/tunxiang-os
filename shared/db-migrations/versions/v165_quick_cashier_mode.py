"""v165 — 快餐模式配置与叫号管理

新增三张表：
  quick_cashier_configs  — 门店快餐模式配置（取餐模式/叫号方式/并发台数等）
  quick_orders           — 快餐订单扩展（取餐号、叫号状态、取餐时间）
  call_number_sequences  — 取餐号流水（每日重置、前缀配置）

RLS 策略：NULLIF(current_setting('app.tenant_id', true), '')::uuid 标准安全模式。

Revision ID: v165
Revises: v164
Create Date: 2026-04-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v165"
down_revision= "v164"
branch_labels= None
depends_on= None

_SAFE_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"
# call_number_sequences 不含 tenant_id，用 store_id 隔离（无 RLS，通过应用层控制）


def _apply_rls(table_name: str) -> None:
    """标准三段式 RLS：ENABLE → FORCE → 四条策略"""
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


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── quick_cashier_configs 快餐模式门店配置 ──────────────────────────────
    if "quick_cashier_configs" not in _existing:
        op.create_table(
            "quick_cashier_configs",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "is_enabled",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("FALSE"),
                comment="是否启用快餐模式",
            ),
            sa.Column(
                "call_mode",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'number'"),
                comment="叫号方式：number=数字叫号 / voice=语音叫号 / both=两者都用",
            ),
            sa.Column(
                "prefix",
                sa.String(10),
                nullable=False,
                server_default=sa.text("''"),
                comment="取餐号前缀，如 'A' 则号码为 A001",
            ),
            sa.Column(
                "daily_reset",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("TRUE"),
                comment="是否每天重置取餐号流水",
            ),
            sa.Column(
                "max_number",
                sa.Integer,
                nullable=False,
                server_default=sa.text("999"),
                comment="每日最大取餐号，达到后从 1 循环",
            ),
            sa.Column(
                "auto_print_receipt",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("TRUE"),
                comment="结账后自动打印小票",
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
            sa.CheckConstraint(
                "call_mode IN ('number', 'voice', 'both')",
                name="ck_quick_cashier_configs_call_mode",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "store_id",
                name="uq_quick_cashier_configs_tenant_store",
            ),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_quick_cashier_configs_tenant_store "
        "ON quick_cashier_configs (tenant_id, store_id)"
    )
    _apply_rls("quick_cashier_configs")

    # ── quick_orders 快餐订单扩展 ─────────────────────────────────────────
    if "quick_orders" not in _existing:
        op.create_table(
            "quick_orders",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "order_id",
                UUID(as_uuid=True),
                nullable=True,
                comment="关联主订单 ID（orders 表）",
            ),
            sa.Column(
                "call_number",
                sa.String(20),
                nullable=False,
                comment="取餐号，如 A001",
            ),
            sa.Column(
                "order_type",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'dine_in'"),
                comment="订单类型：dine_in=堂食 / takeaway=外带 / pack=打包",
            ),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'pending'"),
                comment="状态：pending=待叫号 / calling=叫号中 / completed=已取餐 / cancelled=已取消",
            ),
            sa.Column(
                "called_at",
                sa.TIMESTAMP(timezone=True),
                nullable=True,
                comment="叫号时间",
            ),
            sa.Column(
                "completed_at",
                sa.TIMESTAMP(timezone=True),
                nullable=True,
                comment="取餐完成时间",
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint(
                "order_type IN ('dine_in', 'takeaway', 'pack')",
                name="ck_quick_orders_order_type",
            ),
            sa.CheckConstraint(
                "status IN ('pending', 'calling', 'completed', 'cancelled')",
                name="ck_quick_orders_status",
            ),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_quick_orders_tenant_store "
        "ON quick_orders (tenant_id, store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_quick_orders_tenant_store_status "
        "ON quick_orders (tenant_id, store_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_quick_orders_order_id "
        "ON quick_orders (order_id) WHERE order_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_quick_orders_created_at "
        "ON quick_orders (store_id, created_at DESC)"
    )
    _apply_rls("quick_orders")

    # ── call_number_sequences 取餐号流水 ──────────────────────────────────
    # 不含 tenant_id（每日流水不跨租户，通过 store_id 唯一确定）
    # 不启用 RLS，由应用层保证只操作自己的 store_id
    if "call_number_sequences" not in _existing:
        op.create_table(
            "call_number_sequences",
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "biz_date",
                sa.Date,
                nullable=False,
                comment="业务日期（YYYY-MM-DD），每天重置",
            ),
            sa.Column(
                "current_seq",
                sa.Integer,
                nullable=False,
                server_default=sa.text("0"),
                comment="当前已分配的最大流水号（0 表示今日尚未分配）",
            ),
            sa.Column(
                "prefix",
                sa.String(10),
                nullable=False,
                server_default=sa.text("''"),
                comment="取餐号前缀，冗余存储方便查询",
            ),
            sa.PrimaryKeyConstraint("store_id", "biz_date", name="pk_call_number_sequences"),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_call_number_sequences_store_date "
        "ON call_number_sequences (store_id, biz_date DESC)"
    )


def downgrade() -> None:
    # 取餐号流水（无 RLS，直接删表）
    op.execute("DROP TABLE IF EXISTS call_number_sequences")

    # 带 RLS 的三张表
    for table in ["quick_orders", "quick_cashier_configs"]:
        for policy in ["rls_delete", "rls_update", "rls_insert", "rls_select"]:
            op.execute(f"DROP POLICY IF EXISTS {table}_{policy} ON {table}")
        op.drop_table(table)
