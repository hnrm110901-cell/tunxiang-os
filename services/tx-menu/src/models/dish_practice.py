"""菜品口味做法 ORM 模型

每道菜可配置多种做法（如辣度、温度、加料），按 practice_group 分组。
金额统一存分（fen）。
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class DishPractice(TenantBase):
    """菜品做法/口味选项"""

    __tablename__ = "dish_practices"

    dish_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dishes.id"),
        nullable=False,
        index=True,
        comment="关联菜品ID",
    )
    practice_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="做法名称，如：微辣/中辣/特辣",
    )
    practice_group: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="default",
        comment="分组，如：辣度/温度/加料/烹饪方式",
    )
    additional_price_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="加价金额(分)，0=不加价",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="是否为该分组默认选项",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="排序权重，越小越靠前",
    )
