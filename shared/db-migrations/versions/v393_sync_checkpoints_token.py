"""Tier1: sync_checkpoints 增量 token 持久化（CRDT 接线 W12-3）

W12-3 智能体落地了 LWW-Register + SyncToken 算法，但 OfflineSyncService 现有
sync_checkpoints 表（v036）只存了 last_pull_seq + last_push_at + last_pull_at，
没有"双键 token"（last_seen_ts + last_seen_seq + 序列化 token）。

后果：sync-engine 崩溃恢复后，watermark 退化为单纯时间戳，同一秒内多事件可能
被遗漏；4h 断网回放后没有可校验的崩溃续跑点。

本迁移在已有 sync_checkpoints 表上**增量**增加两列（不重建表，不影响 v036 索引/RLS）：

  last_pull_token       TEXT          -- SyncToken.to_string()，崩溃恢复直接 from_string
  last_pull_token_ts    TIMESTAMPTZ   -- 显式存 max(client_ts)，便于跨节点查询/审计

说明：
  - last_pull_seq (BIGINT, 已存在) 继续作为 max(seq) 的显式列（保持兼容）
  - last_pull_token 是冗余但权威的"完整 token"，崩溃恢复从此读取，等价于
    SyncToken(last_seen_ts=last_pull_token_ts, last_seen_seq=last_pull_seq)

  RLS：sync_checkpoints 已在 v036 启用 RLS（tenant_id），新列继承现有策略
  无需重建 policy。

Revision ID: v393_sync_checkpoints_token
Revises: v392_points_system_core
Create Date: 2026-05-04
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v393_sync_checkpoints_token"
down_revision: Union[str, None] = "v392_points_system_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 增量列：完整 SyncToken 持久化 ──────────────────────────────────────
    op.execute("""
        ALTER TABLE sync_checkpoints
            ADD COLUMN IF NOT EXISTS last_pull_token TEXT
    """)
    op.execute("""
        ALTER TABLE sync_checkpoints
            ADD COLUMN IF NOT EXISTS last_pull_token_ts TIMESTAMPTZ
    """)

    # 索引：崩溃恢复时按 (tenant, store, device) 已经有 v036 唯一索引，无需新增。
    # 但加一个按 (tenant_id, last_pull_token_ts) 的索引方便审计扫描"哪些设备落后"。
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sync_checkpoints_tenant_token_ts
            ON sync_checkpoints (tenant_id, last_pull_token_ts DESC)
            WHERE last_pull_token_ts IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sync_checkpoints_tenant_token_ts")
    op.execute("ALTER TABLE sync_checkpoints DROP COLUMN IF EXISTS last_pull_token_ts")
    op.execute("ALTER TABLE sync_checkpoints DROP COLUMN IF EXISTS last_pull_token")
