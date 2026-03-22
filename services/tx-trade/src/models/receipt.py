"""小票模型 — 模板管理 + 打印日志"""
import uuid

from sqlalchemy import String, Integer, Boolean, DateTime, Text, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase
from .enums import PrintType


class ReceiptTemplate(TenantBase):
    """小票模板"""
    __tablename__ = "receipt_templates"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True
    )
    template_name: Mapped[str] = mapped_column(String(100), nullable=False)
    print_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PrintType.receipt.value
    )
    # ESC/POS 模板内容（Jinja2 语法，渲染时注入订单数据）
    template_content: Mapped[str] = mapped_column(Text, nullable=False)
    paper_width: Mapped[int] = mapped_column(Integer, default=58, comment="纸宽mm: 58/80")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict | None] = mapped_column(JSON, default=dict, comment="字体/对齐/二维码等配置")


class ReceiptLog(TenantBase):
    """打印日志"""
    __tablename__ = "receipt_logs"

    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), index=True
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True
    )
    print_type: Mapped[str] = mapped_column(String(20), nullable=False)
    printer_id: Mapped[str | None] = mapped_column(String(50), comment="打印机标识")
    kitchen_station: Mapped[str | None] = mapped_column(String(50), comment="目标档口")
    content_hash: Mapped[str | None] = mapped_column(String(64), comment="内容哈希，防重复打印")
    printed_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[str | None] = mapped_column(String(500))
