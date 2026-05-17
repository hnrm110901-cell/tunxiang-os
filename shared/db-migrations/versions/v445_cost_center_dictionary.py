"""v445 — GL 内核成本中心字典表（W3 P0 #756 round-1 §19 critic P1-2 新增 / Tier1 邻接）

业务背景：
  v444 journal_line.cost_center 是 VARCHAR(64) 自由文本，缺乏统一字典管控。
  本表为成本中心建立租户级字典，为 web-admin 提供 CRUD UI 与 P&L 切片维度受控管理。
  - cost_center_type 三分类：业态（line_of_business）/ 门店（store）/ 部门（department）
  - parent_code 自引用支持成本中心树（业态 → 门店 → 部门）
  - is_active 区分启用/停用，停用后历史 journal_line 仍可关联但不再可选

设计要点：
  - 松耦合：不加 FK from journal_line.cost_center 到本表（避免 W3-W5 业务路径需要
    backfill 字典即可入账；W5 settle_order 接入 GL 时再考虑加约束或 service-level 校验）
  - 单租户隔离：(tenant_id, cost_center_code) 唯一约束 → 编码租户内唯一
  - parent_code != cost_center_code CHECK 防自闭环（与 v442 chart_of_accounts 同模式）
  - 软删除：is_deleted BOOLEAN（list 默认过滤）
  - RLS 四联（ENABLE + FORCE + POLICY + WITH CHECK），v139 NULLIF::uuid 模式
  - inspector-and-skip 幂等模式（与 v421+ 一致）

W5 接入注意（commit message 也说明）：
  W5 settle_order 接入 GL 前必须 seed 字典初始 16 条记录
  （8 业态 placeholder + 8 门店 placeholder），否则 cost_center 字段无字典 fallback。
  立 W5 follow-up issue 跟进 seed 数据。

Migration 链：
  v444_journal_line → v445_cost_center_dictionary (本 PR 5/5)

Revision ID: v445_cost_center_dictionary
Revises: v444_journal_line
Create Date: 2026-05-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v445_cost_center_dictionary"
down_revision: Union[str, Sequence[str], None] = "v444_journal_line"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ─────────────────────────────────────────────────────────────────────────
    # cost_center_dictionary 成本中心字典表
    # ─────────────────────────────────────────────────────────────────────────
    if "cost_center_dictionary" not in existing:
        op.execute(
            """
            CREATE TABLE cost_center_dictionary (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                cost_center_code    VARCHAR(64) NOT NULL,
                cost_center_name    VARCHAR(128) NOT NULL,
                cost_center_type    VARCHAR(32) NOT NULL,
                parent_code         VARCHAR(64),
                is_active           BOOLEAN NOT NULL DEFAULT TRUE,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_ccd_cost_center_type
                    CHECK (cost_center_type IN ('line_of_business', 'store', 'department')),
                CONSTRAINT chk_ccd_no_self_parent
                    CHECK (parent_code IS NULL OR parent_code != cost_center_code),
                CONSTRAINT uq_ccd_tenant_cost_center_code
                    UNIQUE (tenant_id, cost_center_code)
            )
            """
        )
        op.execute("ALTER TABLE cost_center_dictionary ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE cost_center_dictionary FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY cost_center_dictionary_tenant_isolation
            ON cost_center_dictionary
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            """
        )
        # 树形遍历：按租户 + parent_code 查子节点
        op.execute(
            """
            CREATE INDEX idx_ccd_tenant_parent
            ON cost_center_dictionary (tenant_id, parent_code)
            WHERE is_deleted = FALSE
            """
        )
        # 启用字典查询：按租户 + type 拿 active 选项（list 主路径）
        op.execute(
            """
            CREATE INDEX idx_ccd_tenant_type_active
            ON cost_center_dictionary (tenant_id, cost_center_type)
            WHERE is_active = TRUE AND is_deleted = FALSE
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "cost_center_dictionary" in existing:
        op.execute("DROP TABLE cost_center_dictionary CASCADE")
