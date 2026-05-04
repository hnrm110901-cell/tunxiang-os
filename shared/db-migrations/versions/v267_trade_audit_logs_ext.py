"""v267 — trade_audit_logs 扩列：RBAC 审计追溯增强

扩列（Sprint A4，CLAUDE.md §17 Tier1）：
  - result        — allow / deny / error，装饰器分支产物
  - reason        — 人类可读的拒绝/通过原因（manager_override / over_threshold_without_mfa 等）
  - request_id    — 链路追踪 ID，关联网关到 service 的全链路日志
  - severity      — info / warn / deny，供 SIEM 分级告警
  - session_id    — 前端会话 ID，便于关联同一收银员的连续操作
  - before_state  — JSONB，变更前状态快照（改价/改单前金额）
  - after_state   — JSONB，变更后状态快照（用于事后回放与差异审计）

索引：
  - idx_trade_audit_deny — 支持"查 tenant 某用户在时段内的 deny 动作"部分索引

向前兼容：
  - 全部新增列 nullable=True，现有 write_audit 无需改动即可继续写入
  - Phase 2 路由层在捕获 ROLE_FORBIDDEN / MFA_REQUIRED 时额外填入 result/reason/severity

Revision ID: v267
Revises: v264
Create Date: 2026-04-24
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v267b"
down_revision = "v264"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "trade_audit_logs" not in set(inspector.get_table_names()):
        # 父迁移未应用（例如新环境从头初始化）— 本迁移 no-op；
        # 真正建表由 v261_trade_audit_logs 负责。
        return

    existing_cols = {c["name"] for c in inspector.get_columns("trade_audit_logs")}

    if "result" not in existing_cols:
        op.add_column(
            "trade_audit_logs",
            sa.Column("result", sa.String(16), nullable=True),
        )
    if "reason" not in existing_cols:
        op.add_column(
            "trade_audit_logs",
            sa.Column("reason", sa.String(128), nullable=True),
        )
    if "request_id" not in existing_cols:
        op.add_column(
            "trade_audit_logs",
            sa.Column("request_id", sa.String(64), nullable=True),
        )
    if "severity" not in existing_cols:
        op.add_column(
            "trade_audit_logs",
            sa.Column("severity", sa.String(16), nullable=True),
        )
    if "session_id" not in existing_cols:
        op.add_column(
            "trade_audit_logs",
            sa.Column("session_id", sa.String(64), nullable=True),
        )
    if "before_state" not in existing_cols:
        op.add_column(
            "trade_audit_logs",
            sa.Column("before_state", postgresql.JSONB, nullable=True),
        )
    if "after_state" not in existing_cols:
        op.add_column(
            "trade_audit_logs",
            sa.Column("after_state", postgresql.JSONB, nullable=True),
        )

    # 部分索引：仅 deny 行，支持"查某租户某用户时段内的 deny 动作"
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("trade_audit_logs")}
    if "idx_trade_audit_deny" not in existing_indexes:
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_trade_audit_deny
            ON trade_audit_logs (tenant_id, user_id, created_at DESC)
            WHERE result = 'deny'
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "trade_audit_logs" not in set(inspector.get_table_names()):
        return

    op.execute("DROP INDEX IF EXISTS idx_trade_audit_deny")

    existing_cols = {c["name"] for c in inspector.get_columns("trade_audit_logs")}
    for col in (
        "after_state",
        "before_state",
        "session_id",
        "severity",
        "request_id",
        "reason",
        "result",
    ):
        if col in existing_cols:
            op.drop_column("trade_audit_logs", col)
