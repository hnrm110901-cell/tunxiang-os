"""搜索意图 ORM"""

from typing import Optional

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeSearchIntent(TenantBase):
    __tablename__ = "forge_search_intents"

    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_intents = mapped_column(JSONB, default=[])
    matched_app_ids = mapped_column(JSONB, default=[])
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    clicked_app_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    search_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
