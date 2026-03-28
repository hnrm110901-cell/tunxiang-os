"""v007: 补全缺失的核心业务表

从 zhilian-os 迁移分析中识别的缺失表（HIGH 优先级）:
- bom_templates / bom_items — 菜品BOM配方（成本真相引擎核心）
- waste_events — 损耗事件追踪（食材损耗=利润）
- supply_orders — 供应链采购单
- member_transactions — 会员交易记录（CDP核心）
- notifications — 多渠道通知（企微/飞书/短信）

所有表包含:
- tenant_id UUID NOT NULL + RLS 四策略
- FORCE ROW LEVEL SECURITY
- NOT NULL + 非空守卫（与 v006 修复一致）
- created_at / updated_at / is_deleted 标准字段

Revision ID: v007
Revises: v006
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision: str = "v007"
down_revision: Union[str, None] = "v006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_TABLES = [
    "bom_templates", "bom_items", "waste_events",
    "supply_orders", "member_transactions", "notifications",
]


def _safe_rls(table_name: str) -> None:
    """为表启用安全的 RLS 策略（v006 修复模式）"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")

    guard = (
        f"tenant_id = current_setting('app.tenant_id')::UUID "
        f"AND current_setting('app.tenant_id', TRUE) IS NOT NULL "
        f"AND current_setting('app.tenant_id', TRUE) <> ''"
    )
    for action, clause in [
        ("SELECT", f"USING ({guard})"),
        ("INSERT", f"WITH CHECK ({guard})"),
        ("UPDATE", f"USING ({guard}) WITH CHECK ({guard})"),
        ("DELETE", f"USING ({guard})"),
    ]:
        op.execute(
            f"CREATE POLICY {table_name}_{action.lower()}_tenant "
            f"ON {table_name} FOR {action} {clause}"
        )


def upgrade() -> None:
    # ── bom_templates: 菜品BOM配方模板 ──
    op.create_table(
        "bom_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("dish_id", UUID(as_uuid=True), sa.ForeignKey("dishes.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("yield_ratio", sa.Numeric(5, 2), nullable=True, comment="出成率(%)"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # ── bom_items: BOM配方明细行 ──
    op.create_table(
        "bom_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("template_id", UUID(as_uuid=True), sa.ForeignKey("bom_templates.id"), nullable=False),
        sa.Column("ingredient_id", UUID(as_uuid=True), sa.ForeignKey("ingredient_masters.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 3), nullable=False, comment="用量"),
        sa.Column("unit", sa.String(20), nullable=False, comment="单位(g/ml/个)"),
        sa.Column("waste_rate", sa.Numeric(5, 2), nullable=True, comment="预估损耗率(%)"),
        sa.Column("is_optional", sa.Boolean, server_default="false", comment="是否可选配料"),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # ── waste_events: 损耗事件追踪 ──
    op.create_table(
        "waste_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("ingredient_id", UUID(as_uuid=True), sa.ForeignKey("ingredient_masters.id"), nullable=True),
        sa.Column("dish_id", UUID(as_uuid=True), sa.ForeignKey("dishes.id"), nullable=True),
        sa.Column("waste_type", sa.String(30), nullable=False, comment="expired/damaged/overproduction/other"),
        sa.Column("quantity", sa.Numeric(10, 3), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("cost_fen", sa.BigInteger, nullable=False, comment="损耗金额(分)"),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # ── supply_orders: 供应链采购单 ──
    op.create_table(
        "supply_orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("supplier_name", sa.String(100), nullable=False),
        sa.Column("order_no", sa.String(50), nullable=True, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="'draft'", comment="draft/submitted/confirmed/received/cancelled"),
        sa.Column("total_amount_fen", sa.BigInteger, nullable=False, server_default="0", comment="采购总金额(分)"),
        sa.Column("item_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("expected_date", sa.Date, nullable=True, comment="预计到货日"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # ── member_transactions: 会员交易记录 ──
    op.create_table(
        "member_transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("txn_type", sa.String(30), nullable=False, comment="consume/recharge/refund/points_earn/points_redeem"),
        sa.Column("amount_fen", sa.BigInteger, nullable=False, comment="交易金额(分)"),
        sa.Column("points_delta", sa.Integer, nullable=True, comment="积分变动(正为增,负为减)"),
        sa.Column("balance_after_fen", sa.BigInteger, nullable=True, comment="交易后余额(分)"),
        sa.Column("channel", sa.String(30), nullable=True, comment="pos/miniapp/wechat/manual"),
        sa.Column("remark", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # ── notifications: 多渠道通知 ──
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=True),
        sa.Column("recipient_id", UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("channel", sa.String(20), nullable=False, comment="wecom/feishu/sms/push/email"),
        sa.Column("category", sa.String(30), nullable=False, comment="alert/report/reminder/approval"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("priority", sa.String(10), server_default="'normal'", comment="low/normal/high/urgent"),
        sa.Column("status", sa.String(20), server_default="'pending'", comment="pending/sent/delivered/failed"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", JSON, nullable=True, comment="渠道特定参数"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # ── 为所有新表启用安全 RLS ──
    for table in NEW_TABLES:
        _safe_rls(table)


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
