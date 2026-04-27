"""Invoice 聚合的 Ontology 事件 payload 定义.

聚合根: Invoice (aggregate_type='invoice')
相关事件: invoice.verified / invoice.matched

演进规则: 只加不改
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field

from .base import OntologyEvent


class InvoiceType(str, Enum):
    """发票类型枚举."""

    FULLY_ELECTRONIC = "fully_electronic"  # 全电发票 (金税四期)
    ELECTRONIC = "electronic"              # 普通电子发票
    PAPER = "paper"                        # 纸质发票
    SPECIAL = "special"                    # 专用发票


class InvoiceVerifiedPayload(OntologyEvent):
    """发票验真通过事件 payload.

    供应商发票经 OCR / 国税平台验真后发射, 下游 InvoiceMatchAgent
    据此做三流合一匹配.
    """

    invoice_no: str
    supplier_tax_id: str
    amount_fen: int = Field(ge=0, description="不含税金额, 分")
    tax_fen: int = Field(ge=0, description="税额, 分")
    invoice_type: InvoiceType
    verified_at: str = Field(description="ISO8601 验真时间")
    three_way_match_id: Optional[str] = Field(
        default=None,
        description="三流合一匹配 ID, 未匹配为 None",
    )
