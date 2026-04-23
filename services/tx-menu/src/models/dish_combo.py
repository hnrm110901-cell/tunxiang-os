"""套餐组合 ORM 模型

套餐由多个菜品组成，items_json 存储组合明细。
金额统一存分（fen）。
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class DishCombo(TenantBase):
    """套餐组合"""

    __tablename__ = "dish_combos"

    store_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id"),
        index=True,
        comment="所属门店，NULL=集团通用套餐",
    )
    combo_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="套餐名称",
    )
    combo_price_fen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="套餐售价(分)",
    )
    original_price_fen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="原价合计(分)=各子项原价之和",
    )
    items_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment='[{"dish_id":"..","dish_name":"..","qty":1,"price_fen":1800}]',
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        comment="套餐描述",
    )
    image_url: Mapped[str | None] = mapped_column(
        String(500),
        comment="套餐图片",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        comment="是否上架",
    )
