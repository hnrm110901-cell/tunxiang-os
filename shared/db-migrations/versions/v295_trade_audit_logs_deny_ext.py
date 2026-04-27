"""v295 — trade_audit_logs 扩列：deny 审计追溯（R-补1-1 / Tier1）

§19 审查发现：tx-trade 9 个套了 require_role/require_mfa 装饰器的路由
**只在 allow 路径写审计**，cashier 被 403 拒绝时数据库无任何记录，违反 Tier1
"审计全覆盖"。本迁移 + 配套 audit_deny helper 是修复包的基建。

扩列（全 nullable，向前兼容现有 write_audit 调用）：
  - result        — allow / deny / mfa_required（装饰器分支产物）
  - reason        — 人类可读的拒绝原因（ROLE_FORBIDDEN / MFA_REQUIRED /
                    over_threshold / cross_tenant_blocked 等）
  - request_id    — 链路追踪 ID
  - severity      — info / warn / error / critical（SIEM 分级；不与 result 重叠）
  - session_id    — 前端 session ID（关联同一收银员连续操作）
  - before_state  — JSONB，变更前快照（改价/改单等）
  - after_state   — JSONB，变更后快照

部分索引：
  - idx_trade_audit_deny — WHERE result = 'deny'，支持"过去 N 天某用户被拒"
    类查询；deny 率 < 1% 时索引体积仅占主表的 ~1%

向前兼容：
  - 全部 nullable=True，现有 write_audit 调用无需修改
  - 现有索引 ix_trade_audit_logs_tenant_created / user_created / action_created 不动

注意：
  - f53370 分支历史上有过 v267_trade_audit_logs_ext 占用 v267，但 main v267
    已被 agent_episodes 占用 → 本迁移最初打算用 v290。但 main 当前 head 已经
    是 v294_mrp_forecast，且 v290 已被 v290_call_center_tables 占用，**为
    避免 alembic 双 head 冲突**改 revision 至 v295（在 v294 之后）。
  - 当 f53370 分支后续合入 main 时，其 v267_trade_audit_logs_ext 已经
    inspect-and-skip 兼容 nullable 列存在的情况 → 预期合并不冲突。
  - severity 值域：info/warn/error/critical（SIEM 标准 4 级），不复用 deny 字面量
    避免与 result 列语义重叠。

Revision ID: v295
Revises: v294_mrp_forecast
Create Date: 2026-04-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v295"
down_revision: Union[str, None] = "v294_mrp_forecast"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_COLS = (
    ("result", sa.String(16)),
    ("reason", sa.String(128)),
    ("request_id", sa.String(64)),
    ("severity", sa.String(16)),
    ("session_id", sa.String(64)),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "trade_audit_logs" not in set(inspector.get_table_names()):
        # 父迁移 v261 未应用（新环境）— 本迁移 no-op，后续 v261 会在重新初始化时建表
        return

    existing_cols = {c["name"] for c in inspector.get_columns("trade_audit_logs")}

    for col_name, col_type in _NEW_COLS:
        if col_name not in existing_cols:
            op.add_column(
                "trade_audit_logs",
                sa.Column(col_name, col_type, nullable=True),
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

    # 部分索引：仅 deny 行（deny 率 < 1% 时索引体积小，查询命中快）
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
    # 倒序：先删 JSONB，再删定长列
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
