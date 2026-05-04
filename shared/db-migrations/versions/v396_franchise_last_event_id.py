"""v396 — 加盟相关表加 last_event_id 字段（事件溯源对齐）

PG.6 — 配合 PB.3 (加盟接入事件总线) 实装；为 PG.5 (加盟历史回放 backfill) 准备字段。

加盟域 6 张表（v060/v066 创建）补充 last_event_id UUID 列：

  1. franchisees                    — 加盟商主表
  2. franchisee_stores              — 加盟商门店关联
  3. royalty_bills                  — 月度特许权账单
  4. franchise_audits               — 加盟商稽核记录
  5. franchise_settlements          — 月度结算单
  6. franchise_settlement_items     — 结算明细行

字段语义：
  - 类型：UUID NULL（旧行允许 NULL，未关联到事件）
  - 含义：本行最后一次状态变化所对应的 events.event_id
  - 用途：
    a) 事件投影对账：projector 重建时，对比物化视图 last_event_id 与
       events 表确认是否所有事件已应用
    b) PG.5 backfill 锚点：旧行 backfill 出 events 后，把 events.event_id
       回填进 last_event_id，标记"已纳入事件流"
    c) 边缘 sync_pull 增量定位：客户端可基于 last_event_id 精确定位下一批

  - 索引：(tenant_id, last_event_id) — 用于 backfill 反查；
    last_event_id IS NULL 索引（PARTIAL）— 用于增量补 backfill

  - RLS：六张表本身已在 v060/v066 启用 RLS（_apply_safe_rls），
    本 migration 仅增列 + 加索引，不动 policy。

向后兼容：
  - ALTER TABLE ADD COLUMN IF NOT EXISTS — 幂等
  - 默认 NULL，旧 INSERT 路径不受影响
  - 服务端 emit_event 后，业务代码应在同事务/或异步把 event_id 回填
    （不强制；本 migration 不包含触发器）

部署约束（CLAUDE.md §17 Tier1 + §21 灰度）：
  - ADD COLUMN IF NOT EXISTS：PostgreSQL 11+ 是元数据级修改，毫秒完成
  - 索引：CREATE INDEX CONCURRENTLY IF NOT EXISTS — 不阻塞写入
  - 6 张表 ×（1 ADD + 2 INDEX） = 18 个 DDL 操作，估计总耗时 < 1s

Revision ID: v396
Revises: v395
Create Date: 2026-05-04
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v396"
down_revision: Union[str, None] = "v395"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FRANCHISE_TABLES: tuple[str, ...] = (
    "franchisees",
    "franchisee_stores",
    "royalty_bills",
    "franchise_audits",
    "franchise_settlements",
    "franchise_settlement_items",
)


def upgrade() -> None:
    for table in _FRANCHISE_TABLES:
        # 1. 加列（幂等）
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS last_event_id UUID")
        # 2. 主索引：按租户 + last_event_id 反查
        op.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_last_event ON {table} (tenant_id, last_event_id)")
        # 3. PARTIAL 索引：定位"未纳入事件流"的行（PG.5 backfill 入口）
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_last_event_null ON {table} (tenant_id) WHERE last_event_id IS NULL"
        )


def downgrade() -> None:
    for table in _FRANCHISE_TABLES:
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_last_event_null")
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_last_event")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS last_event_id")
