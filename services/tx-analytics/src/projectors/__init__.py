"""tx-analytics service-local projectors (PRD-11 sub-C / 2026-05-16).

按架构师 D1 ① 与 tx-supply IndexSplitProjector 同 pattern:
SplitAttributionProjector 物理隔离于全局 `shared.events.src.projector_registry`
(那 9 个是 mv_* "只读"投影器, 本 projector 把 inventory.split_attributed 事件
汇总写到 cost_attribution_summary 表给 sub-C dashboard 消费, 性质不同).
"""
