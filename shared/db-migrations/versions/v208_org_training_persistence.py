"""门店借调持久化 — transfers._transfer_store 内存→DB

为 employee_transfers 表补全借调所需字段：
  employee_name  — 员工姓名（冗余存储，避免关联查询）
  from_store_name — 原门店名称（冗余存储）
  to_store_name   — 借调目标门店名称（冗余存储）
  start_date      — 借调开始日期（NOT NULL，业务必填）
  end_date        — 借调结束日期（NOT NULL，业务必填）
  approved_at     — 审批时间（nullable，待审批时为空）

Revision ID: v208b
Revises: v207
Create Date: 2026-04-11
"""
from alembic import op
import sqlalchemy as sa

revision = "v208b"
down_revision = 'v207'
branch_labels = None
depends_on = None

TABLE = 'employee_transfers'


def upgrade() -> None:
    # 类 A 副本去重 (B'-3, 2026-05-09): 本文件 (revision="v208b") 与
    # v287_org_training_persistence.py (revision="v287") 是 100% 内容副本。
    # 两者 down_revision 同为 "v207"（平行分支），alembic 拓扑序两条都跑 →
    # 后跑的撞 DuplicateColumn / DuplicateTable。v287 是规范保留版本（已在
    # B'-2 加 IF NOT EXISTS 索引），本文件改 no-op：让 v287 唯一负责 schema
    # 变更，本文件仅作为 chain 节点存在不动 schema。
    return


def downgrade() -> None:
    # 同 upgrade，no-op；schema 状态由 v287 的 downgrade 反向负责
    return
