"""shared.events.schemas — Ontology 事件 Pydantic schema 包.

T5.1.3 在此包下展开具体事件 payload 定义.
基类见 base.OntologyEvent.
"""
from .base import OntologyEvent
from .finance_events import CashFlowSnapshotPayload
from .invoice_events import InvoiceType, InvoiceVerifiedPayload
from .order_events import (
    OrderChannel,
    OrderCreatedPayload,
    OrderPaidPayload,
    PaymentMethod,
)

__all__ = [
    "CashFlowSnapshotPayload",
    "InvoiceType",
    "InvoiceVerifiedPayload",
    "OntologyEvent",
    "OrderChannel",
    "OrderCreatedPayload",
    "OrderPaidPayload",
    "PaymentMethod",
]
