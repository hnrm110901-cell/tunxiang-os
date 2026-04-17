"""z63 — D8 采购审批+收货质检 & D10 多打卡+换班审批 Should-Fix P1

共 5 张新表：
  Task 1 采购审批（1）: purchase_approval_logs
  Task 2 收货质检（2）: goods_receipts, goods_receipt_items
  Task 3 多打卡（1）: attendance_punches
  Task 4 换班审批（1）: shift_swap_requests

模型来源（只读）:
  src/models/purchase_approval.py
  src/models/goods_receipt.py
  src/models/attendance_punch.py
  src/models/shift_swap.py

Revision ID: z63_d8_d10_procurement_attendance
Revises: z62_merge_mustfix_p0
Create Date: 2026-04-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID


# revision identifiers, used by Alembic.
revision = "z63_d8_d10_procurement_attendance"
down_revision = "z62_merge_mustfix_p0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────── Task 1: purchase_approval_logs ───────────
    op.create_table(
        "purchase_approval_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("po_id", sa.String(), sa.ForeignKey("purchase_orders.id"), nullable=False, index=True),
        sa.Column("level", sa.String(30), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("approver_id", sa.String(50), nullable=False, index=True),
        sa.Column("amount_snapshot_fen", sa.Integer, nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now(), index=True),
    )

    # ─────────── Task 2: goods_receipts + items ───────────
    op.create_table(
        "goods_receipts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("po_id", sa.String(), sa.ForeignKey("purchase_orders.id"), nullable=False, index=True),
        sa.Column("receipt_no", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("total_amount_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("received_by", sa.String(50), nullable=False),
        sa.Column("qc_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft", index=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("posted_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "goods_receipt_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "receipt_id",
            UUID(as_uuid=True),
            sa.ForeignKey("goods_receipts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("ingredient_id", sa.String(50), nullable=False, index=True),
        sa.Column("ordered_qty", sa.Numeric(12, 3), nullable=False),
        sa.Column("received_qty", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("rejected_qty", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("unit_cost_fen", sa.Integer, nullable=True),
        sa.Column("qc_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("qc_remark", sa.Text, nullable=True),
        sa.Column("temperature", sa.Numeric(5, 2), nullable=True),
        sa.Column("prod_date", sa.Date, nullable=True),
        sa.Column("expiry_date", sa.Date, nullable=True),
        sa.Column("waste_event_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # ─────────── Task 3: attendance_punches ───────────
    op.create_table(
        "attendance_punches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", sa.String(50), nullable=False, index=True),
        sa.Column("store_id", sa.String(50), nullable=False, index=True),
        sa.Column("punch_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("direction", sa.String(10), nullable=False, server_default="in"),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("payload_json", JSON, nullable=True),
        sa.Column("location_lat", sa.Numeric(10, 7), nullable=True),
        sa.Column("location_lng", sa.Numeric(10, 7), nullable=True),
        sa.Column("verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("verify_remark", sa.String(200), nullable=True),
        sa.Column("shift_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("needs_approval", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # ─────────── Task 4: shift_swap_requests ───────────
    op.create_table(
        "shift_swap_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("requester_id", sa.String(50), nullable=False, index=True),
        sa.Column("target_employee_id", sa.String(50), nullable=False, index=True),
        sa.Column(
            "original_shift_id",
            UUID(as_uuid=True),
            sa.ForeignKey("shifts.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "swap_shift_id",
            UUID(as_uuid=True),
            sa.ForeignKey("shifts.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("approver_id", sa.String(50), nullable=True),
        sa.Column("approved_at", sa.DateTime, nullable=True),
        sa.Column("reject_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("shift_swap_requests")
    op.drop_table("attendance_punches")
    op.drop_table("goods_receipt_items")
    op.drop_table("goods_receipts")
    op.drop_table("purchase_approval_logs")
