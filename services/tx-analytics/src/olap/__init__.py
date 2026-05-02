"""OLAP 多维分析引擎 — BI-1.1

提供钻取（Drill Down）、切片（Slice）、切块（Dice）、透视（Pivot）
多维分析能力，基于预定义 Cube 和现有物化视图。
"""

from .engine import OLAPEngine, OLAPQuery, OLAPResult, CubeMeta, MeasureDef, DimensionDef, FilterDef, SortDef, AggFunction

__all__ = [
    "OLAPEngine",
    "OLAPQuery",
    "OLAPResult",
    "CubeMeta",
    "MeasureDef",
    "DimensionDef",
    "FilterDef",
    "SortDef",
    "AggFunction",
]
