"""v261 — tx-trade RBAC 审计日志表：trade_audit_logs

新建：
  trade_audit_logs — 支付/退款/折扣等资金/风险敏感路由的统一审计留痕

用途：
  Sprint A4（RBAC 统一装饰器 + 审计日志）。tx-trade 内部 9 个支付/退款/折扣类
  路由文件在每次写操作后通过 services.trade_audit_log.write_audit 写入本表，
  事后可追查"谁、何时、对什么、做了什么、金额多少"。

设计要点：
  - tenant_id + RLS（app.tenant_id），防跨租户查询
  - 按月分区（PostgreSQL 14+ 原生 RANGE 分区），降低高频写入表的索引开销
  - 预建 2026-04 / 2026-05 / 2026-06 三个月分区
  - 索引覆盖（tenant_id, created_at DESC）/（user_id, created_at DESC）/
    （action, created_at DESC）三条典型查询
  - amount_fen 可空（查询/取消等操作无金额）

Revision ID: v261
Revises: v260
Create Date: 2026-04-18
"""

import sqlalchemy as sa
from alembic import op

revision = "v299"
down_revision = "v260"
branch_labels = None
depends_on = None


_PARTITIONS = (
    ("trade_audit_logs_2026_04", "2026-04-01", "2026-05-01"),
    ("trade_audit_logs_2026_05", "2026-05-01", "2026-06-01"),
    ("trade_audit_logs_2026_06", "2026-06-01", "2026-07-01"),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "trade_audit_logs" not in existing:
        # 父表（按 created_at RANGE 分区）
        # 注意：分区表主键必须包含分区键，因此主键为 (log_id, created_at)
        op.execute("""
            CREATE TABLE trade_audit_logs (
                log_id UUID NOT NULL DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                store_id UUID NULL,
                user_id UUID NOT NULL,
                user_role TEXT NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT NULL,
                target_id UUID NULL,
                amount_fen BIGINT NULL,
                client_ip INET NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (log_id, created_at)
            ) PARTITION BY RANGE (created_at);
        """)

        # 预建三个月分区
        for part_name, start, end in _PARTITIONS:
            op.execute(f"""
                CREATE TABLE IF NOT EXISTS {part_name}
                PARTITION OF trade_audit_logs
                FOR VALUES FROM ('{start}') TO ('{end}');
            """)

        # 索引（分区表父表上创建会自动在每个分区上生效，PG 11+）
        op.create_index(
            "ix_trade_audit_logs_tenant_created",
            "trade_audit_logs",
            ["tenant_id", sa.text("created_at DESC")],
        )
        op.create_index(
            "ix_trade_audit_logs_user_created",
            "trade_audit_logs",
            ["user_id", sa.text("created_at DESC")],
        )
        op.create_index(
            "ix_trade_audit_logs_action_created",
            "trade_audit_logs",
            ["action", sa.text("created_at DESC")],
        )

    # RLS 强制租户隔离
    op.execute("ALTER TABLE trade_audit_logs ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS trade_audit_logs_tenant ON trade_audit_logs;")
    op.execute("""
        CREATE POLICY trade_audit_logs_tenant ON trade_audit_logs
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS trade_audit_logs_tenant ON trade_audit_logs;")
    op.execute("ALTER TABLE IF EXISTS trade_audit_logs DISABLE ROW LEVEL SECURITY;")
    # 先删子分区再删父表
    for part_name, _, _ in _PARTITIONS:
        op.execute(f"DROP TABLE IF EXISTS {part_name};")
    op.execute("DROP INDEX IF EXISTS ix_trade_audit_logs_action_created;")
    op.execute("DROP INDEX IF EXISTS ix_trade_audit_logs_user_created;")
    op.execute("DROP INDEX IF EXISTS ix_trade_audit_logs_tenant_created;")
    op.execute("DROP TABLE IF EXISTS trade_audit_logs;")
