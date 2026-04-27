"""v366 — 供应链价格台账（价格历史 + 预警规则 + 预警实例）

新增三张表：
  supplier_price_history — 价格快照核心台账（每次收货/采购单/手工录入都写入）
  price_alert_rules      — 价格预警阈值规则（绝对值/百分比涨跌幅/同比涨跌幅）
  price_alerts           — 触发的预警实例（待处理/已确认/已忽略）

业务背景：对标奥琦玮供应链。徐记海鲜替换标杆案例缺失"价格台账"功能时，
采购腐败风险无法控制。本表通过事件总线挂接到收货流程，做到价格"无形可见"。

RLS：四条策略（select/insert/update/delete），使用 NULLIF 安全模式禁止 NULL 绕过。
所有金额字段统一使用"分"（bigint）。

Revision ID: v366
Revises: v365
Create Date: 2026-04-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v366"
down_revision: Union[str, None] = "v365"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SAFE_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def _apply_rls(table_name: str) -> None:
    """三段式 RLS：ENABLE → FORCE → 四条策略（禁止 NULL 绕过）。"""
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


def _create_updated_at_trigger(table_name: str) -> None:
    """为表创建 updated_at 自动维护触发器。复用全局函数 set_updated_at()。"""
    # 全局触发器函数（多次执行幂等）
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_{table_name}_set_updated_at ON {table_name}"
    )
    op.execute(
        f"CREATE TRIGGER trg_{table_name}_set_updated_at "
        f"BEFORE UPDATE ON {table_name} "
        f"FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── supplier_price_history 价格快照台账 ───────────────────────
    if "supplier_price_history" not in _existing:
        op.create_table(
            "supplier_price_history",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("ingredient_id", UUID(as_uuid=True), nullable=False),
            sa.Column("supplier_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "unit_price_fen",
                sa.BigInteger,
                nullable=False,
                comment="单价（分），整数禁用浮点",
            ),
            sa.Column(
                "quantity_unit",
                sa.String(16),
                nullable=True,
                comment="计量单位 kg/L/包/件",
            ),
            sa.Column(
                "captured_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
                comment="价格采集时间",
            ),
            sa.Column(
                "source_doc_type",
                sa.String(32),
                nullable=True,
                comment="purchase_order|receiving|manual",
            ),
            sa.Column("source_doc_id", UUID(as_uuid=True), nullable=True),
            sa.Column("source_doc_no", sa.String(64), nullable=True),
            sa.Column(
                "store_id",
                UUID(as_uuid=True),
                nullable=True,
                comment="哪个门店收货",
            ),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
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
            sa.Column(
                "is_deleted",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    # 索引：按食材/供应商查询，时间倒序
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sph_tenant_ingredient_captured "
        "ON supplier_price_history (tenant_id, ingredient_id, captured_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sph_tenant_supplier_captured "
        "ON supplier_price_history (tenant_id, supplier_id, captured_at DESC)"
    )
    # 幂等约束：tenant + source_doc_id + ingredient_id 唯一
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_sph_tenant_source_doc_ingredient "
        "ON supplier_price_history (tenant_id, source_doc_id, ingredient_id) "
        "WHERE source_doc_id IS NOT NULL AND is_deleted = false"
    )

    _apply_rls("supplier_price_history")
    _create_updated_at_trigger("supplier_price_history")

    # ── price_alert_rules 价格预警阈值规则 ────────────────────────
    if "price_alert_rules" not in _existing:
        op.create_table(
            "price_alert_rules",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "ingredient_id",
                UUID(as_uuid=True),
                nullable=True,
                comment="NULL 表示该规则适用于全部食材",
            ),
            sa.Column(
                "rule_type",
                sa.String(16),
                nullable=False,
                comment=(
                    "ABSOLUTE_HIGH|ABSOLUTE_LOW|"
                    "PERCENT_RISE|PERCENT_FALL|"
                    "YOY_RISE|YOY_FALL"
                ),
            ),
            sa.Column(
                "threshold_value",
                sa.Numeric(12, 4),
                nullable=False,
                comment="绝对值用'分'，百分比用百分点（5.00 = 5%）",
            ),
            sa.Column(
                "baseline_window_days",
                sa.Integer,
                nullable=False,
                server_default=sa.text("30"),
                comment="同比/环比基准窗口（天）",
            ),
            sa.Column(
                "enabled",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
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
            sa.Column(
                "is_deleted",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_par_tenant_enabled "
        "ON price_alert_rules (tenant_id, enabled) "
        "WHERE is_deleted = false"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_par_tenant_ingredient "
        "ON price_alert_rules (tenant_id, ingredient_id) "
        "WHERE is_deleted = false"
    )

    _apply_rls("price_alert_rules")
    _create_updated_at_trigger("price_alert_rules")

    # ── price_alerts 触发的预警实例 ──────────────────────────────
    if "price_alerts" not in _existing:
        op.create_table(
            "price_alerts",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("rule_id", UUID(as_uuid=True), nullable=False),
            sa.Column("ingredient_id", UUID(as_uuid=True), nullable=False),
            sa.Column("supplier_id", UUID(as_uuid=True), nullable=True),
            sa.Column(
                "triggered_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("current_price_fen", sa.BigInteger, nullable=False),
            sa.Column("baseline_price_fen", sa.BigInteger, nullable=True),
            sa.Column(
                "breach_value",
                sa.Numeric(12, 4),
                nullable=True,
                comment="绝对差额（分）或百分点差",
            ),
            sa.Column(
                "severity",
                sa.String(16),
                nullable=False,
                server_default=sa.text("'WARNING'"),
                comment="INFO|WARNING|CRITICAL",
            ),
            sa.Column(
                "status",
                sa.String(16),
                nullable=False,
                server_default=sa.text("'ACTIVE'"),
                comment="ACTIVE|ACKED|IGNORED",
            ),
            sa.Column("acked_by", UUID(as_uuid=True), nullable=True),
            sa.Column("acked_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("ack_comment", sa.Text, nullable=True),
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
            sa.Column(
                "is_deleted",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pa_tenant_status_triggered "
        "ON price_alerts (tenant_id, status, triggered_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pa_tenant_ingredient_triggered "
        "ON price_alerts (tenant_id, ingredient_id, triggered_at DESC)"
    )
    # 外键：rule_id 引用规则表（删除规则时 SET NULL 不可行，因为 rule_id NOT NULL；
    # 改用 RESTRICT 防止误删历史告警关联的规则）
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE price_alerts
                ADD CONSTRAINT fk_price_alerts_rule
                FOREIGN KEY (rule_id) REFERENCES price_alert_rules(id)
                ON DELETE RESTRICT;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    _apply_rls("price_alerts")
    _create_updated_at_trigger("price_alerts")


def downgrade() -> None:
    for table in ["price_alerts", "price_alert_rules", "supplier_price_history"]:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_set_updated_at ON {table}")
        for policy in ["rls_delete", "rls_update", "rls_insert", "rls_select"]:
            op.execute(f"DROP POLICY IF EXISTS {table}_{policy} ON {table}")
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
