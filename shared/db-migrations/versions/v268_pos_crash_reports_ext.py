"""v268 — pos_crash_reports 扩列：Sprint A1 徐记海鲜 Tier1

扩列（Sprint A1，CLAUDE.md §17 Tier1）：
  - timeout_reason    — fetch_timeout / saga_timeout / gateway_timeout / rls_deny /
                        disk_io_error / unknown（R1：预留 disk_io_error 不建 CHECK 约束）
  - recovery_action   — reset / redirect_tables / retry / abort
  - saga_id           — 关联 payment_sagas.saga_id（软 FK，可空）
  - order_no          — 软关联订单号（如 XJ20260424-00047）
  - severity          — fatal / warn / info，默认 fatal
  - boundary_level    — root / cashier / unknown

索引：
  - idx_pos_crash_severity_tenant_time — 支持"查某租户某严重级别时段内记录"

向前兼容：
  - 全列 nullable，v260 已落地行不需回填
  - 前端旧版本（不带新字段）提交时后端填 NULL，不报错

Revision ID: v268
Revises: v267
Create Date: 2026-04-24
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v268b"
down_revision = "v267"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "pos_crash_reports" not in set(inspector.get_table_names()):
        # 父迁移未应用（新环境从头初始化）— no-op
        return

    existing_cols = {c["name"] for c in inspector.get_columns("pos_crash_reports")}

    if "timeout_reason" not in existing_cols:
        op.add_column(
            "pos_crash_reports",
            sa.Column("timeout_reason", sa.String(32), nullable=True),
        )
    if "recovery_action" not in existing_cols:
        op.add_column(
            "pos_crash_reports",
            sa.Column("recovery_action", sa.String(32), nullable=True),
        )
    if "saga_id" not in existing_cols:
        op.add_column(
            "pos_crash_reports",
            sa.Column("saga_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    if "order_no" not in existing_cols:
        op.add_column(
            "pos_crash_reports",
            sa.Column("order_no", sa.String(64), nullable=True),
        )
    if "severity" not in existing_cols:
        op.add_column(
            "pos_crash_reports",
            sa.Column(
                "severity",
                sa.String(16),
                nullable=True,
                server_default="fatal",
            ),
        )
    if "boundary_level" not in existing_cols:
        op.add_column(
            "pos_crash_reports",
            sa.Column("boundary_level", sa.String(16), nullable=True),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("pos_crash_reports")}
    if "idx_pos_crash_severity_tenant_time" not in existing_indexes:
        op.create_index(
            "idx_pos_crash_severity_tenant_time",
            "pos_crash_reports",
            ["tenant_id", "severity", sa.text("created_at DESC")],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "pos_crash_reports" not in set(inspector.get_table_names()):
        return

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("pos_crash_reports")}
    if "idx_pos_crash_severity_tenant_time" in existing_indexes:
        op.drop_index(
            "idx_pos_crash_severity_tenant_time",
            table_name="pos_crash_reports",
        )

    existing_cols = {c["name"] for c in inspector.get_columns("pos_crash_reports")}
    # 倒序删除（与 upgrade 对称）
    for col in (
        "boundary_level",
        "severity",
        "order_no",
        "saga_id",
        "recovery_action",
        "timeout_reason",
    ):
        if col in existing_cols:
            op.drop_column("pos_crash_reports", col)
