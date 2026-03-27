"""v003: Payment & Settlement tables for Sprint 1-2

New tables:
- payment_records: 第三方渠道账单导入(微信/支付宝/美团/银联CSV)
- reconciliation_batches: 对账批次
- reconciliation_diffs: 对账差异明细
- tri_reconciliation_records: 三角对账(订单↔支付↔银行↔发票)
- store_daily_settlements: 门店日结单
- payment_fees: 支付手续费记录

Also:
- Add index on payments.trade_no
- Add index on orders.biz_date

Revision ID: v003
Revises: v002
Create Date: 2026-03-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision: str = "v003"
down_revision: Union[str, None] = "v002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_TABLES = [
    "payment_records",
    "reconciliation_batches",
    "reconciliation_diffs",
    "tri_reconciliation_records",
    "store_daily_settlements",
    "payment_fees",
]


def _enable_rls(table_name: str) -> None:
    """为表启用 RLS + 创建租户隔离策略"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table_name} ON {table_name} "
        f"USING (tenant_id = current_setting('app.tenant_id')::UUID)"
    )
    op.execute(
        f"CREATE POLICY tenant_insert_{table_name} ON {table_name} "
        f"FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID)"
    )


def _disable_rls(table_name: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_insert_{table_name} ON {table_name}")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table_name} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # ---------------------------------------------------------------
    # 0. Add indexes on existing tables
    # ---------------------------------------------------------------
    op.create_index("idx_payments_trade_no", "payments", ["trade_no"])
    op.add_column("orders", sa.Column("biz_date", sa.Date, comment="营业日期"))
    op.create_index("idx_orders_biz_date", "orders", ["store_id", "biz_date"])

    # ---------------------------------------------------------------
    # 1. payment_records — 第三方渠道账单导入
    # ---------------------------------------------------------------
    op.create_table(
        "payment_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("channel", sa.String(30), nullable=False, index=True,
                  comment="wechat/alipay/meituan/unionpay/douyin"),
        sa.Column("trade_no", sa.String(128), nullable=False, index=True, comment="第三方交易流水号"),
        sa.Column("merchant_no", sa.String(64), comment="商户号"),
        sa.Column("trade_type", sa.String(30), nullable=False, server_default="payment",
                  comment="payment/refund/transfer"),
        sa.Column("amount_fen", sa.Integer, nullable=False, comment="交易金额(分)"),
        sa.Column("fee_fen", sa.Integer, server_default="0", comment="手续费(分)"),
        sa.Column("net_amount_fen", sa.Integer, comment="到账金额(分)"),
        sa.Column("trade_time", sa.DateTime(timezone=True), nullable=False, comment="第三方交易时间"),
        sa.Column("settle_date", sa.Date, comment="结算日期"),
        sa.Column("counterpart", sa.String(100), comment="交易对手(买家标识)"),
        sa.Column("description", sa.String(500), comment="交易描述/备注"),
        sa.Column("raw_data", JSON, comment="原始CSV行数据"),
        sa.Column("import_batch_id", sa.String(64), index=True, comment="导入批次号"),
        sa.Column("matched_payment_id", UUID(as_uuid=True), comment="匹配的本地支付记录ID"),
        sa.Column("match_status", sa.String(20), server_default="unmatched",
                  comment="unmatched/matched/conflict/manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_payment_records_channel_date", "payment_records", ["channel", "settle_date"])

    # ---------------------------------------------------------------
    # 2. reconciliation_batches — 对账批次
    # ---------------------------------------------------------------
    op.create_table(
        "reconciliation_batches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("batch_no", sa.String(64), unique=True, nullable=False, comment="对账批次号"),
        sa.Column("channel", sa.String(30), nullable=False, comment="对账渠道"),
        sa.Column("recon_date", sa.Date, nullable=False, index=True, comment="对账日期"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending",
                  comment="pending/processing/completed/failed"),
        # 统计
        sa.Column("total_local_count", sa.Integer, server_default="0", comment="本地交易笔数"),
        sa.Column("total_remote_count", sa.Integer, server_default="0", comment="渠道交易笔数"),
        sa.Column("matched_count", sa.Integer, server_default="0", comment="匹配笔数"),
        sa.Column("diff_count", sa.Integer, server_default="0", comment="差异笔数"),
        sa.Column("local_only_count", sa.Integer, server_default="0", comment="本地多出笔数(长款)"),
        sa.Column("remote_only_count", sa.Integer, server_default="0", comment="渠道多出笔数(短款)"),
        sa.Column("amount_diff_count", sa.Integer, server_default="0", comment="金额不一致笔数"),
        # 金额汇总
        sa.Column("total_local_amount_fen", sa.Integer, server_default="0", comment="本地总金额(分)"),
        sa.Column("total_remote_amount_fen", sa.Integer, server_default="0", comment="渠道总金额(分)"),
        sa.Column("total_diff_fen", sa.Integer, server_default="0", comment="总差异金额(分)"),
        sa.Column("operator_id", sa.String(50), comment="操作员"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_recon_batch_store_date", "reconciliation_batches", ["store_id", "recon_date"])

    # ---------------------------------------------------------------
    # 3. reconciliation_diffs — 对账差异明细
    # ---------------------------------------------------------------
    op.create_table(
        "reconciliation_diffs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("batch_id", UUID(as_uuid=True), sa.ForeignKey("reconciliation_batches.id"),
                  nullable=False, index=True),
        sa.Column("diff_type", sa.String(30), nullable=False,
                  comment="local_only/remote_only/amount_mismatch/time_mismatch"),
        sa.Column("local_payment_id", UUID(as_uuid=True), comment="本地支付记录ID"),
        sa.Column("local_payment_no", sa.String(64), comment="本地支付流水号"),
        sa.Column("remote_trade_no", sa.String(128), comment="渠道交易流水号"),
        sa.Column("local_amount_fen", sa.Integer, comment="本地金额(分)"),
        sa.Column("remote_amount_fen", sa.Integer, comment="渠道金额(分)"),
        sa.Column("diff_amount_fen", sa.Integer, comment="差异金额(分)"),
        sa.Column("local_time", sa.DateTime(timezone=True), comment="本地交易时间"),
        sa.Column("remote_time", sa.DateTime(timezone=True), comment="渠道交易时间"),
        sa.Column("resolution_status", sa.String(20), server_default="pending",
                  comment="pending/resolved/written_off/escalated"),
        sa.Column("resolution_action", sa.String(100), comment="处理动作"),
        sa.Column("resolved_by", sa.String(50), comment="处理人"),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # ---------------------------------------------------------------
    # 4. tri_reconciliation_records — 三角对账
    # ---------------------------------------------------------------
    op.create_table(
        "tri_reconciliation_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("recon_date", sa.Date, nullable=False, index=True, comment="对账日期"),
        # 订单侧
        sa.Column("order_id", UUID(as_uuid=True), comment="订单ID"),
        sa.Column("order_no", sa.String(64), comment="订单号"),
        sa.Column("order_amount_fen", sa.Integer, comment="订单金额(分)"),
        # 支付侧
        sa.Column("payment_id", UUID(as_uuid=True), comment="支付记录ID"),
        sa.Column("payment_no", sa.String(64), comment="支付流水号"),
        sa.Column("payment_amount_fen", sa.Integer, comment="支付金额(分)"),
        sa.Column("payment_channel", sa.String(30), comment="支付渠道"),
        # 银行侧
        sa.Column("bank_trade_no", sa.String(128), comment="银行流水号"),
        sa.Column("bank_amount_fen", sa.Integer, comment="银行到账金额(分)"),
        sa.Column("bank_settle_date", sa.Date, comment="银行结算日期"),
        # 发票侧
        sa.Column("invoice_id", UUID(as_uuid=True), comment="发票ID"),
        sa.Column("invoice_no", sa.String(64), comment="发票号码"),
        sa.Column("invoice_amount_fen", sa.Integer, comment="发票金额(分)"),
        # 三角对账结果
        sa.Column("match_status", sa.String(20), nullable=False, server_default="pending",
                  comment="pending/full_match/partial_match/mismatch"),
        sa.Column("order_payment_match", sa.Boolean, comment="订单↔支付是否匹配"),
        sa.Column("payment_bank_match", sa.Boolean, comment="支付↔银行是否匹配"),
        sa.Column("bank_invoice_match", sa.Boolean, comment="银行↔发票是否匹配"),
        sa.Column("diff_detail", JSON, comment="差异详情"),
        sa.Column("resolution_status", sa.String(20), server_default="pending"),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_tri_recon_store_date", "tri_reconciliation_records", ["store_id", "recon_date"])

    # ---------------------------------------------------------------
    # 5. store_daily_settlements — 门店日结单
    # ---------------------------------------------------------------
    op.create_table(
        "store_daily_settlements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("biz_date", sa.Date, nullable=False, index=True, comment="营业日期"),
        sa.Column("settlement_no", sa.String(64), unique=True, nullable=False, comment="日结单号"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft",
                  comment="draft/submitted/approved/rejected"),
        # 订单统计
        sa.Column("total_orders", sa.Integer, server_default="0"),
        sa.Column("completed_orders", sa.Integer, server_default="0"),
        sa.Column("cancelled_orders", sa.Integer, server_default="0"),
        sa.Column("total_guests", sa.Integer, server_default="0"),
        sa.Column("avg_per_guest_fen", sa.Integer, server_default="0", comment="客单价(分)"),
        # 营收
        sa.Column("gross_revenue_fen", sa.Integer, server_default="0", comment="总营收(分)"),
        sa.Column("total_discount_fen", sa.Integer, server_default="0", comment="总折扣(分)"),
        sa.Column("total_refund_fen", sa.Integer, server_default="0", comment="总退款(分)"),
        sa.Column("net_revenue_fen", sa.Integer, server_default="0", comment="净营收(分)"),
        # 按支付方式
        sa.Column("cash_fen", sa.Integer, server_default="0"),
        sa.Column("wechat_fen", sa.Integer, server_default="0"),
        sa.Column("alipay_fen", sa.Integer, server_default="0"),
        sa.Column("unionpay_fen", sa.Integer, server_default="0"),
        sa.Column("meituan_fen", sa.Integer, server_default="0", comment="美团(分)"),
        sa.Column("eleme_fen", sa.Integer, server_default="0", comment="饿了么(分)"),
        sa.Column("douyin_fen", sa.Integer, server_default="0", comment="抖音(分)"),
        sa.Column("member_balance_fen", sa.Integer, server_default="0", comment="会员余额(分)"),
        sa.Column("credit_fen", sa.Integer, server_default="0", comment="挂账(分)"),
        sa.Column("coupon_fen", sa.Integer, server_default="0", comment="优惠券(分)"),
        # 成本
        sa.Column("food_cost_fen", sa.Integer, server_default="0", comment="食材成本(分)"),
        sa.Column("labor_cost_fen", sa.Integer, server_default="0", comment="人工成本(分)"),
        sa.Column("platform_fee_fen", sa.Integer, server_default="0", comment="平台佣金(分)"),
        sa.Column("payment_fee_fen", sa.Integer, server_default="0", comment="支付手续费(分)"),
        # 毛利
        sa.Column("gross_profit_fen", sa.Integer, server_default="0", comment="毛利(分)"),
        sa.Column("gross_margin_rate", sa.Numeric(6, 4), comment="毛利率"),
        # 现金盘点
        sa.Column("cash_expected_fen", sa.Integer, server_default="0", comment="应有现金(分)"),
        sa.Column("cash_actual_fen", sa.Integer, comment="实际现金(分)"),
        sa.Column("cash_diff_fen", sa.Integer, comment="现金差异(分)"),
        sa.Column("cash_diff_reason", sa.String(500), comment="现金差异说明"),
        # 按渠道统计
        sa.Column("channel_summary", JSON, comment="[{channel, orders, revenue_fen, margin_rate}]"),
        # 折扣明细
        sa.Column("discount_summary", JSON, comment="[{type, count, amount_fen}]"),
        # 审核
        sa.Column("operator_id", sa.String(50), comment="日结操作员"),
        sa.Column("operator_name", sa.String(50)),
        sa.Column("reviewer_id", sa.String(50), comment="审核人"),
        sa.Column("reviewer_name", sa.String(50)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_daily_settlement_store_date", "store_daily_settlements",
                    ["store_id", "biz_date"], unique=True)

    # ---------------------------------------------------------------
    # 6. payment_fees — 支付手续费记录
    # ---------------------------------------------------------------
    op.create_table(
        "payment_fees",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("payment_id", UUID(as_uuid=True), sa.ForeignKey("payments.id"), index=True,
                  comment="关联支付记录"),
        sa.Column("channel", sa.String(30), nullable=False, comment="支付渠道"),
        sa.Column("payment_amount_fen", sa.Integer, nullable=False, comment="交易金额(分)"),
        sa.Column("fee_rate", sa.Numeric(6, 4), nullable=False, comment="费率"),
        sa.Column("fee_fen", sa.Integer, nullable=False, comment="手续费(分)"),
        sa.Column("fee_type", sa.String(30), server_default="transaction",
                  comment="transaction/monthly/setup"),
        sa.Column("biz_date", sa.Date, nullable=False, index=True, comment="营业日期"),
        sa.Column("settle_date", sa.Date, comment="结算日期"),
        sa.Column("notes", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_payment_fees_store_date", "payment_fees", ["store_id", "biz_date"])

    # ---------------------------------------------------------------
    # Enable RLS on all new tables
    # ---------------------------------------------------------------
    for table in NEW_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        _disable_rls(table)

    op.drop_table("payment_fees")
    op.drop_table("store_daily_settlements")
    op.drop_table("tri_reconciliation_records")
    op.drop_table("reconciliation_diffs")
    op.drop_table("reconciliation_batches")
    op.drop_table("payment_records")

    op.drop_index("idx_orders_biz_date", table_name="orders")
    op.drop_column("orders", "biz_date")
    op.drop_index("idx_payments_trade_no", table_name="payments")
