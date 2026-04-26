"""MCP 工具 ORM"""

from typing import Optional

from sqlalchemy import String, Text, Integer, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeMCPTool(TenantBase):
    __tablename__ = "forge_mcp_tools"

    tool_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    server_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    input_schema: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    output_schema: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    ontology_bindings: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    trust_tier_required: Mapped[str] = mapped_column(String(10), default="T1")
    call_count: Mapped[int] = mapped_column(BigInteger, default=0)
    avg_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
