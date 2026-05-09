"""桌台模型 — 门店桌台拓扑管理"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

from .enums import TableStatus


class Table(TenantBase):
    """桌台"""

    __tablename__ = "tables"

    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    table_no: Mapped[str] = mapped_column(String(20), nullable=False, comment="桌号如A01")
    area: Mapped[str | None] = mapped_column(String(50), comment="区域：大厅/包间/露台")
    floor: Mapped[int] = mapped_column(Integer, default=1)
    seats: Mapped[int] = mapped_column(Integer, nullable=False, comment="座位数")
    min_consume_fen: Mapped[int] = mapped_column(Integer, default=0, comment="最低消费(分)")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TableStatus.free.value, index=True)
    current_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), comment="当前订单ID")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict | None] = mapped_column(JSON, default=dict, comment="桌台特殊配置")
