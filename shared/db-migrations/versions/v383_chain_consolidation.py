"""v383 — alembic 链多 head 合并（结构性 merge，无 schema 改动）

历史上仓库的 alembic 迁移链上有 26 个 head（多分支 + 孤儿 reanchor 后），
导致 `alembic upgrade head` 无法自动选择目标，需要每次 -r 显式指定 rev。

本 migration 把所有 head 用 tuple down_revision 合并，让链恢复"单 head"。

合并的 head 来源（按版本号排序）：

  早期分支（v047 起的并行分支，未合）：
    · v048 discount_audit_log
    · v049 service_bell
    · v050 course_firing
    · v051 seat_ordering
    · v052 allergen_management
    · v053 supply_chain_mobile
    · v054 business_diagnosis
    · v056b multichannel_publish
    · v057 stored_value_cards
    · v058 delivery_platforms
    · v059 approval_workflow
    · v061 payroll_system
    · v062 central_kitchen

  中期分支：
    · v206b human_hub_foundation
    · v207b ai_marketing_tables
    · v235b knowledge_graph_tables
    · v254 performance_reviews
    · v296 api_idempotency_cache
    · v319_banquets
    · v342_barcode_tracking
    · v346_banquet_kpi

  近期 head（Sprint G/D/E + Forge + P0 系列产生的扇出分支）：
    · v366 price_ledger（P0-1 价格台账）
    · v367 warehouse_locations（P0-2 库位）
    · v369_delivery_proof（P0-4 电子签收）
    · v371_devforge_application（DevForge 平台 #120）
    · v382_fill_rls_historical_debt（RLS 历史债 #102）

  重复 revision 重命名后的 sibling head（rename 自相同槽位的并行 PR）：
    · v150b/v151b/v167b/v168b/v169b（早期分支并行）
    · v206c/v206d/v207c/v208b（中期分支并行）
    · v235c/v236b/v237b（中期分支并行）
    · v250b/v251b/v252b/v253b/v254b/v255b/v256b（绩效/费控并行）
    · v260b/v261b（菜单/审计并行）

upgrade(): 无 schema 改动 — 仅作为结构性 merge node。
downgrade(): 同样无操作。

Revision ID: v383_chain_consolidation
Revises: 47 heads（见 down_revision tuple）
Create Date: 2026-04-27
"""
from typing import Sequence, Union

revision: str = "v383_chain_consolidation"
down_revision: Union[str, Sequence[str], None] = (
    # 早期 v047 起的并行分支
    "v048",
    "v049",
    "v050",
    "v051",
    "v052",
    "v053",
    "v054",
    "v056b",
    "v057",
    "v058",
    "v059",
    "v061",
    "v062",
    # 重复 revision 重命名后的 sibling head
    # B-prime-6 fix (2026-05-09): 原 tuple 含 10 个 v383 创建后被新 migration 引用降级
    # 的 non-heads (v169b v206b v207b v235b v235c v237b v253b v255b v256b v260b —
    # 各自被 v170 v207 v208 v236 v238 v254 v256b v297 v257 v261 references) 已删除；
    # 这些 revision 通过自己的真实 children 进入主链，无需 v383 兜底。
    "v150b",
    "v151b",
    "v167b",
    "v168b",
    "v206c",
    "v206d",
    "v207c",
    "v208b",
    "v236b",
    "v250b",
    "v251b",
    "v252b",
    "v254",
    "v254b",
    "v261b",
    # 中期分支
    "v296",
    "v319_banquets",
    "v342_barcode_tracking",
    "v346_banquet_kpi",
    # 近期 head
    "v366",
    "v367",
    "v369_delivery_proof",
    "v371_devforge_application",
    "v382_fill_rls_historical_debt",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """结构性 merge — 无 schema 改动。"""
    pass


def downgrade() -> None:
    """结构性 merge 不可降级 — 降级方向必须按 head 单独处理。"""
    pass
