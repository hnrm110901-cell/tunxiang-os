"""v022: 储值卡 v2 字段补充 + 新建充值套餐表

背景：
  v015 创建了 stored_value_cards / stored_value_transactions / recharge_rules。
  v2 模型新增了以下字段（ORM 与 DB 存在 drift），本迁移补齐差距，并新建套餐表。

变更内容：
  stored_value_cards:
    + main_balance_fen   INTEGER NOT NULL DEFAULT 0
    + scope_type         VARCHAR(20) NOT NULL DEFAULT 'brand'
    + scope_id           UUID nullable
    + expiry_date        DATE nullable
    + remark             VARCHAR(255) nullable
    修正：card_no 扩容为 VARCHAR(40)（原 VARCHAR(32) 不够）

  stored_value_transactions:
    + main_amount_fen    INTEGER NOT NULL DEFAULT 0
    + customer_id        UUID nullable
    + recharge_plan_id   VARCHAR(50) nullable

  NEW TABLE stored_value_recharge_plans（充值套餐）
    + 索引：(tenant_id, is_active)

  新增索引：
    stored_value_cards:        (status, tenant_id)
    stored_value_transactions: (customer_id, tenant_id), (order_id)

RLS：stored_value_recharge_plans 使用 v006+ safe pattern

Revision ID: v022
Revises: v021
Create Date: 2026-03-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision = "v022b"
down_revision= "v022a"
branch_labels= None
depends_on= None

_SAFE_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def _enable_safe_rls(table_name: str) -> None:
    """v006+ safe RLS: 4 policies + NULL guard + FORCE"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    for action, clause in [
        ("select", f"FOR SELECT USING ({_SAFE_CONDITION})"),
        ("insert", f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"),
        ("update", f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"),
        ("delete", f"FOR DELETE USING ({_SAFE_CONDITION})"),
    ]:
        op.execute(f"CREATE POLICY {table_name}_rls_{action} ON {table_name} {clause}")


def upgrade() -> None:
    # ── stored_value_cards: 新增 v2 字段 ──────────────────────────

    # 扩容 card_no（VARCHAR(32) → VARCHAR(40)）以容纳 SV-YYYYMMDD-XXXXXX 格式
    op.alter_column(
        "stored_value_cards",
        "card_no",
        type_=sa.String(40),
        existing_type=sa.String(32),
        existing_nullable=False,
    )

    op.add_column(
        "stored_value_cards",
        sa.Column("main_balance_fen", sa.Integer, nullable=False, server_default="0",
                  comment="本金余额(分)"),
    )
    op.add_column(
        "stored_value_cards",
        sa.Column("scope_type", sa.String(20), nullable=False, server_default="brand",
                  comment="store|brand|group"),
    )
    op.add_column(
        "stored_value_cards",
        sa.Column("scope_id", UUID(as_uuid=True), nullable=True,
                  comment="scope_type=store 时存 store_id，brand 时存 brand_id"),
    )
    op.add_column(
        "stored_value_cards",
        sa.Column("expiry_date", sa.Date, nullable=True,
                  comment="过期日期，NULL=永不过期"),
    )
    op.add_column(
        "stored_value_cards",
        sa.Column("remark", sa.String(255), nullable=True),
    )

    # 新增复合索引
    op.create_index(
        "idx_svc_status_tenant",
        "stored_value_cards",
        ["status", "tenant_id"],
    )

    # ── stored_value_transactions: 新增 v2 字段 ───────────────────

    op.add_column(
        "stored_value_transactions",
        sa.Column("main_amount_fen", sa.Integer, nullable=False, server_default="0",
                  comment="本金变动(分)"),
    )
    op.add_column(
        "stored_value_transactions",
        sa.Column("customer_id", UUID(as_uuid=True), nullable=True,
                  comment="冗余存储便于查询"),
    )
    op.add_column(
        "stored_value_transactions",
        sa.Column("recharge_plan_id", sa.String(50), nullable=True,
                  comment="充值套餐ID"),
    )

    # 新增索引
    op.create_index(
        "idx_svt_customer_tenant",
        "stored_value_transactions",
        ["customer_id", "tenant_id"],
    )
    op.create_index(
        "idx_svt_order_id",
        "stored_value_transactions",
        ["order_id"],
    )

    # ── stored_value_recharge_plans（新表）────────────────────────

    op.create_table(
        "stored_value_recharge_plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
        sa.Column("name", sa.String(100), nullable=False, comment="套餐名称"),
        sa.Column("recharge_amount_fen", sa.Integer, nullable=False, comment="充值金额(分)"),
        sa.Column("gift_amount_fen", sa.Integer, nullable=False, server_default="0",
                  comment="赠送金额(分)"),
        sa.Column("scope_type", sa.String(20), nullable=False, server_default="brand",
                  comment="store|brand|group"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remark", sa.String(255), nullable=True),
        comment="储值卡充值套餐",
    )

    # 套餐表索引
    op.create_index(
        "idx_svrp_tenant_active",
        "stored_value_recharge_plans",
        ["tenant_id", "is_active"],
    )

    # RLS
    _enable_safe_rls("stored_value_recharge_plans")


def downgrade() -> None:
    # 删除 stored_value_recharge_plans
    for suffix in ("select", "insert", "update", "delete"):
        op.execute(
            f"DROP POLICY IF EXISTS stored_value_recharge_plans_rls_{suffix} "
            f"ON stored_value_recharge_plans"
        )
    op.drop_index("idx_svrp_tenant_active", table_name="stored_value_recharge_plans")
    op.drop_table("stored_value_recharge_plans")

    # 移除 stored_value_transactions 新增字段
    op.drop_index("idx_svt_order_id", table_name="stored_value_transactions")
    op.drop_index("idx_svt_customer_tenant", table_name="stored_value_transactions")
    op.drop_column("stored_value_transactions", "recharge_plan_id")
    op.drop_column("stored_value_transactions", "customer_id")
    op.drop_column("stored_value_transactions", "main_amount_fen")

    # 移除 stored_value_cards 新增字段
    op.drop_index("idx_svc_status_tenant", table_name="stored_value_cards")
    op.drop_column("stored_value_cards", "remark")
    op.drop_column("stored_value_cards", "expiry_date")
    op.drop_column("stored_value_cards", "scope_id")
    op.drop_column("stored_value_cards", "scope_type")
    op.drop_column("stored_value_cards", "main_balance_fen")

    # 还原 card_no 长度
    op.alter_column(
        "stored_value_cards",
        "card_no",
        type_=sa.String(32),
        existing_type=sa.String(40),
        existing_nullable=False,
    )
