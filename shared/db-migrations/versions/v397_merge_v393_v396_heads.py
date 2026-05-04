"""v397 — 合并 alembic 双 head: v393_sync_checkpoints_token + v396 [PG.1.1][SECURITY]

主分支当前存在两条并列演进的 alembic 链：

  v390 ─→ v391 ┬→ v392 ─→ v393_sync_checkpoints_token  (head A: 业务推进 — 积分 + sync token)
                └→ v395 ─→ v396                          (head B: 安全 — RLS WITH CHECK + 加盟 last_event_id)

`alembic upgrade head` 见到 multiple heads 会拒绝执行（"Multiple head revisions are
present for given argument 'head'"），导致：

  1. 任何环境（dev / staging / prod / demo）跑 `alembic upgrade head` 立即失败
  2. 后续 v398+ migration 的 down_revision 二选一即引入新分叉
  3. CI migration-ci.yml 当前只检 down_revision 引用存在性，未检 multiple heads，
     所以静默放行了 v393 + v396 同时合入 main（PG.1.1 真因）

修补方案（alembic 标准 merge migration）：

  本文件 down_revision 为元组 (v393_sync_checkpoints_token, v396)，
  alembic 视为合并节点；upgrade/downgrade 均为 no-op（纯链路收敛，不改 schema）。
  合并后唯一 head = v397，v398+ 的 down_revision 直接指 v397 即可。

关联：
  - PG.1 主项（v391 INSERT policy USING-only）已由 v395 修补
  - 本迁移仅消除 alembic 链分叉，无业务影响
  - 配套 CI 增强（multiple heads 检测）见 .github/workflows/migration-ci.yml

Revision ID: v397
Revises: v393_sync_checkpoints_token, v396
Create Date: 2026-05-04
"""

from typing import Sequence, Union

revision: str = "v397"
down_revision: Union[str, Sequence[str], None] = ("v393_sync_checkpoints_token", "v396")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """纯合并节点 — 无 schema 变更"""
    pass


def downgrade() -> None:
    """合并节点 downgrade 等价 no-op — 拆回双 head 由 alembic 自动处理"""
    pass
