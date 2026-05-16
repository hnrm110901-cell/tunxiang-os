"""tx-supply service-local projectors (PRD-11 sub-B.2 / 2026-05-16)

按架构师 D1 ① 推荐 — service-local daemon 隔离 mv_* "投影器只读" 心智:
sub-B.2 IndexSplitProjector 是首次让 projector 触发业务侧写 (auto_deduction
deduct_for_order → ingredients/ingredient_transactions), 与全局 mv_* 投影器 (只更新
物化视图) 性质不同, 物理隔离避免污染全局 9 个 mv_* projector 的语义/checkpoint/rebuild.

启动方式: 由独立 worker 进程或 tx-supply 启动时 lifespan 钩子调用
`start_index_split_projector(tenant_id)`. 通过 env `TX_SUPPLY_ENABLE_INDEX_SPLIT_PROJECTOR`
(默认 false) gate, Phase 2 W11 ship + Phase 2 W12 灰度开关.
"""

from .index_split import IndexSplitProjector

__all__ = ["IndexSplitProjector"]
