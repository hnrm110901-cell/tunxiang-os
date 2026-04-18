"""Finance 聚合的 Ontology 事件 payload 定义.

聚合根: Finance (aggregate_type='cashflow' / 'cost' / ...)
相关事件: cashflow.snapshot / cost.anomaly

演进规则: 只加不改
"""
from __future__ import annotations

from typing import Optional

from pydantic import Field

from .base import OntologyEvent


class CashFlowSnapshotPayload(OntologyEvent):
    """门店资金流快照 payload.

    CashFlowAlertAgent 每日 08:00 扫描各店, 产出本结构.
    days_until_dry = cash_on_hand / 日均净流出  (>30 天或充裕为 None).
    cash_on_hand_fen 可为负值 (银行额度透支场景).
    """

    store_id: str
    snapshot_date: str = Field(description="YYYY-MM-DD")
    cash_on_hand_fen: int = Field(description="账面现金, 分; 透支时为负")
    projected_7d_inflow_fen: int = Field(ge=0)
    projected_7d_outflow_fen: int = Field(ge=0)
    days_until_dry: Optional[int] = Field(
        default=None,
        description="预计断流天数, None 表示 >30 天或无断流风险",
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="预测置信度 0.0–1.0"
    )
