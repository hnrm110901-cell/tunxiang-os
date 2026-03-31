"""储值卡系统补充迁移 — sv_transactions / sv_charge_rules

背景：
  v015/v022 已建立 stored_value_cards / stored_value_transactions /
  stored_value_recharge_plans 体系（以"卡号"为维度）。
  本迁移补充以"会员维度"为中心的轻量辅助表，供新版路由
  /api/v1/members/{member_id}/sv/* 使用，两套表并存不冲突。

新增表：
  sv_transactions  — 轻量版流水（balance_before/balance_after 快照、整型分）
  sv_charge_rules  — 充值赠送活动规则（store 维度、时间范围）

RLS：标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v057
Revises: v047
Create Date: 2026-03-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v057"
down_revision: Union[str, None] = "v047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_TABLES = ["sv_transactions", "sv_charge_rules"]

# v006+ 安全模式：NULL guard + FORCE
_RLS_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"
)


def _enable_safe_rls(table_name: str) -> None:
    """启用 RLS：4 操作 PERMISSIVE 策略 + NULL guard + FORCE"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    for action, clause in [
        ("select", f"FOR SELECT USING ({_RLS_CONDITION})"),
        ("insert", f"FOR INSERT WITH CHECK ({_RLS_CONDITION})"),
        (
            "update",
            f"FOR UPDATE USING ({_RLS_CONDITION}) WITH CHECK ({_RLS_CONDITION})",
        ),
        ("delete", f"FOR DELETE USING ({_RLS_CONDITION})"),
    ]:
        op.execute(
            f"CREATE POLICY {table_name}_rls_{action} ON {table_name} "
            f"AS PERMISSIVE {clause}"
        )


def upgrade() -> None:
    # ── sv_transactions ────────────────────────────────────────────
    # 轻量版储值流水，以 card_id 关联 stored_value_cards（v015 主表）。
    # 相比 stored_value_transactions 增加 balance_before 快照，便于对账。
    op.create_table(
        "sv_transactions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # card_id 关联 stored_value_cards.id（v015 主表）
        sa.Column(
            "card_id",
            UUID(as_uuid=True),
            sa.ForeignKey("stored_value_cards.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("order_id", UUID(as_uuid=True), nullable=True),
        # 类型：charge / consume / refund / adjust / bonus
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column(
            "amount_fen",
            sa.Integer,
            nullable=False,
            comment="变动金额（分，正=增加，负=减少）",
        ),
        sa.Column(
            "balance_before",
            sa.Integer,
            nullable=False,
            comment="操作前余额快照（分）",
        ),
        sa.Column(
            "balance_after",
            sa.Integer,
            nullable=False,
            comment="操作后余额快照（分）",
        ),
        sa.Column("operator_id", UUID(as_uuid=True), nullable=True),
        sa.Column("remark", sa.String(255), nullable=True),
        comment="储值卡流水（member 维度新版，balance_before/after 快照）",
    )
    op.create_index(
        "idx_sv_txn_card_created",
        "sv_transactions",
        ["card_id", "created_at"],
    )
    op.create_index(
        "idx_sv_txn_order",
        "sv_transactions",
        ["order_id"],
        postgresql_where=sa.text("order_id IS NOT NULL"),
    )

    # ── sv_charge_rules ────────────────────────────────────────────
    # 充值赠送活动规则（与 stored_value_recharge_plans 并存，以 store 维度为主）。
    op.create_table(
        "sv_charge_rules",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean,
            server_default="false",
            nullable=False,
        ),
        # 适用门店（NULL = 全租户通用）
        sa.Column("store_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "charge_amount",
            sa.Integer,
            nullable=False,
            comment="触发充值金额（分），充满此金额时赠送",
        ),
        sa.Column(
            "bonus_amount",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="赠送金额（分）",
        ),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="活动开始时间，NULL=即刻生效",
        ),
        sa.Column(
            "valid_to",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="活动结束时间，NULL=永久有效",
        ),
        comment="储值充值赠送活动规则（store 维度）",
    )
    op.create_index(
        "idx_sv_charge_rules_tenant_active",
        "sv_charge_rules",
        ["tenant_id", "is_active"],
    )

    # 启用 RLS
    for table in _NEW_TABLES:
        _enable_safe_rls(table)


def downgrade() -> None:
    for table in reversed(_NEW_TABLES):
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(
                f"DROP POLICY IF EXISTS {table}_rls_{suffix} ON {table}"
            )
        op.drop_table(table)
