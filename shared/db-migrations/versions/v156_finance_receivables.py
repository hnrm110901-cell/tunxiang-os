"""v156 — 财务应收管理三表：押金/存酒/企业挂账

新增六张表：
  biz_deposits            — 押金台账（包间押金/宴会定金/VIP保证金）
  biz_wine_storage        — 存酒台账（存酒寄存、取用全生命周期）
  biz_wine_storage_logs   — 存酒操作日志（追踪每次存取动作）
  biz_credit_agreements   — 企业挂账协议（品牌级信用额度）
  biz_credit_charges      — 挂账消费记录（每笔挂账明细）
  biz_credit_bills        — 挂账账单（月度/周度结算账单）

RLS 策略：NULLIF(current_setting('app.tenant_id', true), '')::uuid 标准安全模式。
金额字段全部用整数（分），字段名以 _fen 结尾。

Revision ID: v156
Revises: v155
Create Date: 2026-04-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v156"
down_revision: Union[str, None] = "v155"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SAFE_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def _create_rls(table: str) -> None:
    """为指定表开启 RLS 并创建四条标准策略（SELECT/INSERT/UPDATE/DELETE）。"""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_rls_select ON {table} "
        f"FOR SELECT USING ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table}_rls_insert ON {table} "
        f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table}_rls_update ON {table} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table}_rls_delete ON {table} "
        f"FOR DELETE USING ({_SAFE_CONDITION})"
    )


def _drop_rls(table: str) -> None:
    """删除指定表的 RLS 策略（downgrade 用）。"""
    for suffix in ("rls_delete", "rls_update", "rls_insert", "rls_select"):
        op.execute(f"DROP POLICY IF EXISTS {table}_{suffix} ON {table}")


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── biz_deposits 押金表 ──────────────────────────────────────────────────
    if "biz_deposits" not in _existing:
        op.create_table(
            "biz_deposits",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False,
                      comment="ref: sys_stores.id"),
            sa.Column("customer_id", UUID(as_uuid=True), nullable=True,
                      comment="nullable，匿名押金"),
            sa.Column("reservation_id", UUID(as_uuid=True), nullable=True,
                      comment="ref: biz_reservations.id"),
            sa.Column("order_id", UUID(as_uuid=True), nullable=True,
                      comment="ref: biz_orders.id"),
            sa.Column("amount_fen", sa.BigInteger, nullable=False,
                      comment="押金金额（分）"),
            sa.Column("applied_amount_fen", sa.BigInteger, nullable=False,
                      server_default="0", comment="已抵扣金额（分）"),
            sa.Column("refunded_amount_fen", sa.BigInteger, nullable=False,
                      server_default="0", comment="已退还金额（分）"),
            sa.Column("status", sa.Text, nullable=False,
                      server_default="collected",
                      comment="collected/partially_applied/fully_applied/refunded/converted/written_off"),
            sa.Column("payment_method", sa.Text, nullable=False,
                      comment="wechat/alipay/cash/card"),
            sa.Column("payment_ref", sa.Text, nullable=True,
                      comment="支付流水号"),
            sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("operator_id", UUID(as_uuid=True), nullable=False,
                      comment="ref: sys_staff.id"),
            sa.Column("remark", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_deposits_tenant "
        "ON biz_deposits (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_deposits_store "
        "ON biz_deposits (tenant_id, store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_deposits_customer "
        "ON biz_deposits (tenant_id, customer_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_deposits_status "
        "ON biz_deposits (tenant_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_deposits_expires_at "
        "ON biz_deposits (tenant_id, expires_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_deposits_reservation "
        "ON biz_deposits (tenant_id, reservation_id) WHERE reservation_id IS NOT NULL"
    )

    _create_rls("biz_deposits")

    # ── biz_wine_storage 存酒表 ──────────────────────────────────────────────
    if "biz_wine_storage" not in _existing:
        op.create_table(
            "biz_wine_storage",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("customer_id", UUID(as_uuid=True), nullable=False,
                      comment="存酒必须绑定会员"),
            sa.Column("source_order_id", UUID(as_uuid=True), nullable=False,
                      comment="来源订单 ref: biz_orders.id"),
            sa.Column("wine_name", sa.Text, nullable=False),
            sa.Column("wine_category", sa.Text, nullable=False,
                      comment="白酒/红酒/啤酒/洋酒/其他"),
            sa.Column("quantity", sa.Numeric(10, 2), nullable=False,
                      comment="当前剩余数量（支持小数瓶）"),
            sa.Column("original_qty", sa.Numeric(10, 2), nullable=False,
                      comment="初始寄存数量"),
            sa.Column("unit", sa.Text, nullable=False, server_default="瓶"),
            sa.Column("estimated_value_fen", sa.BigInteger, nullable=True,
                      comment="酒水估值（分），可空"),
            sa.Column("cabinet_position", sa.Text, nullable=True,
                      comment="酒柜位置编号"),
            sa.Column("status", sa.Text, nullable=False,
                      server_default="stored",
                      comment="stored/partially_retrieved/fully_retrieved/expired/transferred/written_off"),
            sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("operator_id", UUID(as_uuid=True), nullable=False,
                      comment="ref: sys_staff.id"),
            sa.Column("photo_url", sa.Text, nullable=True,
                      comment="酒瓶拍照存档"),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_wine_storage_tenant "
        "ON biz_wine_storage (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_wine_storage_store "
        "ON biz_wine_storage (tenant_id, store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_wine_storage_customer "
        "ON biz_wine_storage (tenant_id, customer_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_wine_storage_status "
        "ON biz_wine_storage (tenant_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_wine_storage_expires_at "
        "ON biz_wine_storage (tenant_id, expires_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_wine_storage_source_order "
        "ON biz_wine_storage (tenant_id, source_order_id)"
    )

    _create_rls("biz_wine_storage")

    # ── biz_wine_storage_logs 存酒操作日志 ───────────────────────────────────
    if "biz_wine_storage_logs" not in _existing:
        op.create_table(
            "biz_wine_storage_logs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("storage_id", UUID(as_uuid=True), nullable=False,
                      comment="ref: biz_wine_storage.id"),
            sa.Column("action", sa.Text, nullable=False,
                      comment="store/retrieve/extend/transfer_out/transfer_in/expire/write_off"),
            sa.Column("quantity_change", sa.Numeric(10, 2), nullable=False,
                      comment="负数=取出，正数=存入"),
            sa.Column("related_order_id", UUID(as_uuid=True), nullable=True,
                      comment="关联订单（取酒时填写）"),
            sa.Column("operator_id", UUID(as_uuid=True), nullable=False,
                      comment="ref: sys_staff.id"),
            sa.Column("remark", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_wine_storage_logs_tenant "
        "ON biz_wine_storage_logs (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_wine_storage_logs_storage "
        "ON biz_wine_storage_logs (tenant_id, storage_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_wine_storage_logs_created_at "
        "ON biz_wine_storage_logs (tenant_id, created_at DESC)"
    )

    _create_rls("biz_wine_storage_logs")

    # ── biz_credit_agreements 企业挂账协议 ───────────────────────────────────
    if "biz_credit_agreements" not in _existing:
        op.create_table(
            "biz_credit_agreements",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("brand_id", UUID(as_uuid=True), nullable=False,
                      comment="品牌级协议"),
            sa.Column("company_name", sa.Text, nullable=False,
                      comment="企业名称"),
            sa.Column("company_tax_no", sa.Text, nullable=True,
                      comment="税号（开票用，可空）"),
            sa.Column("credit_limit_fen", sa.BigInteger, nullable=False,
                      comment="信用额度（分）"),
            sa.Column("used_amount_fen", sa.BigInteger, nullable=False,
                      server_default="0", comment="已使用额度（分）"),
            sa.Column("billing_cycle", sa.Text, nullable=False,
                      server_default="monthly",
                      comment="monthly/weekly/biweekly"),
            sa.Column("due_day", sa.Integer, nullable=False,
                      server_default="15",
                      comment="账单日（每月第N天，1-28）"),
            sa.Column("status", sa.Text, nullable=False,
                      server_default="active",
                      comment="active/suspended/terminated"),
            sa.Column("created_by", UUID(as_uuid=True), nullable=False,
                      comment="ref: sys_staff.id"),
            sa.Column("approved_by", UUID(as_uuid=True), nullable=True,
                      comment="审批人，可空"),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("remark", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_credit_agreements_tenant "
        "ON biz_credit_agreements (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_credit_agreements_brand "
        "ON biz_credit_agreements (tenant_id, brand_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_credit_agreements_status "
        "ON biz_credit_agreements (tenant_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_credit_agreements_company "
        "ON biz_credit_agreements (tenant_id, company_name)"
    )

    _create_rls("biz_credit_agreements")

    # ── biz_credit_charges 挂账消费记录 ─────────────────────────────────────
    if "biz_credit_charges" not in _existing:
        op.create_table(
            "biz_credit_charges",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("agreement_id", UUID(as_uuid=True), nullable=False,
                      comment="ref: biz_credit_agreements.id"),
            sa.Column("order_id", UUID(as_uuid=True), nullable=False,
                      comment="ref: biz_orders.id"),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("charged_amount_fen", sa.BigInteger, nullable=False,
                      comment="本次挂账金额（分）"),
            sa.Column("charged_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")),
            sa.Column("operator_id", UUID(as_uuid=True), nullable=False,
                      comment="ref: sys_staff.id"),
            sa.Column("remark", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_credit_charges_tenant "
        "ON biz_credit_charges (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_credit_charges_agreement "
        "ON biz_credit_charges (tenant_id, agreement_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_credit_charges_store "
        "ON biz_credit_charges (tenant_id, store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_credit_charges_charged_at "
        "ON biz_credit_charges (tenant_id, charged_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_credit_charges_order "
        "ON biz_credit_charges (tenant_id, order_id)"
    )

    _create_rls("biz_credit_charges")

    # ── biz_credit_bills 挂账账单 ────────────────────────────────────────────
    if "biz_credit_bills" not in _existing:
        op.create_table(
            "biz_credit_bills",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("agreement_id", UUID(as_uuid=True), nullable=False,
                      comment="ref: biz_credit_agreements.id"),
            sa.Column("bill_no", sa.Text, nullable=False,
                      comment="账单编号，格式：BILL-YYYYMM-XXXX"),
            sa.Column("period_start", sa.Date, nullable=False),
            sa.Column("period_end", sa.Date, nullable=False),
            sa.Column("total_amount_fen", sa.BigInteger, nullable=False,
                      comment="账单总额（分）"),
            sa.Column("paid_amount_fen", sa.BigInteger, nullable=False,
                      server_default="0", comment="已还款金额（分）"),
            sa.Column("status", sa.Text, nullable=False,
                      server_default="pending",
                      comment="pending/partial_paid/paid/overdue"),
            sa.Column("due_date", sa.Date, nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_credit_bills_tenant "
        "ON biz_credit_bills (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_credit_bills_agreement "
        "ON biz_credit_bills (tenant_id, agreement_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_credit_bills_status "
        "ON biz_credit_bills (tenant_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_biz_credit_bills_due_date "
        "ON biz_credit_bills (tenant_id, due_date)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_biz_credit_bills_bill_no "
        "ON biz_credit_bills (tenant_id, bill_no)"
    )

    _create_rls("biz_credit_bills")


def downgrade() -> None:
    # 逆序删除（先删依赖方，再删被依赖方）
    for table in (
        "biz_credit_bills",
        "biz_credit_charges",
        "biz_credit_agreements",
        "biz_wine_storage_logs",
        "biz_wine_storage",
        "biz_deposits",
    ):
        _drop_rls(table)
        op.drop_table(table)
