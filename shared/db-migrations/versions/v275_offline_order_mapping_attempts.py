"""v275 — Sprint A3 §19 P1：offline_order_mapping 增补 last_error_message

A3 §19 审查致命级 #1 配套迁移：

  v270 已建表 offline_order_mapping，列 sync_attempts INTEGER NOT NULL DEFAULT 0
  存在但实际触发链路缺失（DEAD_LETTER_MAX_ATTEMPTS=20 是孤岛常量）。

  本迁移补一个字段：
    last_error_message TEXT NULL
      — 记录最近一次同步失败的简要原因（500 字符截断）
      — 店长在"离线订单异常"面板查看死信时直接显示此字段
      — 不替代 dead_letter_reason（后者在 mark_dead_letter 时一次性填入聚合原因）
      — 每次 increment_attempts 都会刷新此字段，便于运维追踪渐进性失败

  设计约束（CLAUDE.md §17 Tier1）：
    - sync_attempts 已是 NOT NULL DEFAULT 0（v270），本迁移不改其类型/默认
    - last_error_message 用 NULL 而非空串：未发生过失败的条目应清晰区分
    - 不重建索引：sync_attempts/last_error_message 仅在按 offline_order_id 单点
      读写时使用，无需 secondary index
    - downgrade 可逆（DROP COLUMN IF EXISTS）

  与 v274 trade_audit_logs RLS 加固独立：
    - 本迁移不动 RLS 策略
    - last_error_message 不属于审计证据链，仅为运维提示

Revision ID: v275
Revises: v274
Create Date: 2026-04-25
"""

import sqlalchemy as sa
from alembic import op

revision = "v275"
down_revision = "v274"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "offline_order_mapping" not in set(inspector.get_table_names()):
        # 父迁移 v270 未应用 — no-op（新环境从头初始化时 v270 会带最终 schema）
        return

    existing_cols = {c["name"] for c in inspector.get_columns("offline_order_mapping")}

    # last_error_message：每次同步失败的简要原因（最近一次）
    if "last_error_message" not in existing_cols:
        op.execute(
            "ALTER TABLE offline_order_mapping "
            "ADD COLUMN last_error_message TEXT NULL;"
        )

    # 防御：v270 已声明 sync_attempts NOT NULL DEFAULT 0；若环境上被人为
    # ALTER 改为 NULL（异常路径），此处幂等修补一次
    if "sync_attempts" in existing_cols:
        op.execute(
            "ALTER TABLE offline_order_mapping "
            "ALTER COLUMN sync_attempts SET DEFAULT 0;"
        )
        op.execute(
            "UPDATE offline_order_mapping SET sync_attempts = 0 "
            "WHERE sync_attempts IS NULL;"
        )
        op.execute(
            "ALTER TABLE offline_order_mapping "
            "ALTER COLUMN sync_attempts SET NOT NULL;"
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "offline_order_mapping" not in set(inspector.get_table_names()):
        return

    existing_cols = {c["name"] for c in inspector.get_columns("offline_order_mapping")}
    if "last_error_message" in existing_cols:
        op.execute("ALTER TABLE offline_order_mapping DROP COLUMN IF EXISTS last_error_message;")
