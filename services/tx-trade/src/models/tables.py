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
    # extend_existing=True 兜住 pytest 跨测试文件双重 import 引发的
    # `Table 'tables' is already defined for this MetaData instance` 冲突：
    # services/tx-trade/src/tests/ 下不同 test 文件以裸 `services.X`
    # 与全路径 `services.tx_trade.src.services.X` 加载同一磁盘文件
    # cashier_engine.py / order_service.py，各自相对 `from ..models.tables`
    # 解析到不同 module key（`models.tables` vs
    # `services.tx_trade.src.models.tables`），共享同一 TenantBase.metadata
    # 时 SQLAlchemy 拒绝重复声明。生产链路单一 import 路径，extend_existing
    # 是 no-op。长期收敛：统一 src/tests/ import 风格（follow-up issue）。
    __table_args__ = {"extend_existing": True}

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
