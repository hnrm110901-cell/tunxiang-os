"""MCP 服务器 ORM"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeMCPServer(TenantBase):
    __tablename__ = "forge_mcp_servers"

    server_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    app_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    server_name: Mapped[str] = mapped_column(String(200), nullable=False)
    transport: Mapped[str] = mapped_column(String(30), default="streamable-http")
    base_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    capabilities: Mapped[Optional[dict]] = mapped_column(
        JSONB, default=lambda: {"tools": [], "resources": [], "prompts": []}
    )
    schema_version: Mapped[str] = mapped_column(String(20), default="2025-03-26")
    health_endpoint: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    health_status: Mapped[str] = mapped_column(String(20), default="unknown")
    last_health_check: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_discovery: Mapped[bool] = mapped_column(Boolean, default=False)
