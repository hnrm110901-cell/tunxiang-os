"""角色级别体系 — 角色权限配置与校验"""
import uuid
from typing import Literal

from sqlalchemy import String, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

DataQueryLimit = Literal["unlimited", "7d", "30d", "90d", "1y"]


class RoleConfig(TenantBase):
    """角色权限配置"""
    __tablename__ = "role_configs"

    role_name: Mapped[str] = mapped_column(String(50), nullable=False, comment="角色名称")
    role_code: Mapped[str] = mapped_column(String(30), nullable=False, index=True, comment="角色编码")
    role_level: Mapped[int] = mapped_column(Integer, nullable=False, comment="角色级别 1-10，数字越大权限越高")
    max_discount_pct: Mapped[int] = mapped_column(Integer, default=100, comment="最大折扣百分比(100=不打折)")
    max_tip_off_fen: Mapped[int] = mapped_column(Integer, default=0, comment="最大抹零金额(分)")
    max_gift_fen: Mapped[int] = mapped_column(Integer, default=0, comment="最大赠送金额(分)")
    max_order_gift_fen: Mapped[int] = mapped_column(Integer, default=0, comment="最大整单赠送金额(分)")
    data_query_limit: Mapped[str] = mapped_column(String(20), default="7d", comment="数据查询范围: unlimited/7d/30d/90d/1y")


# ---- 纯函数：角色权限校验 ----

# 操作所需的最低角色级别
_ACTION_MIN_LEVEL = {
    "discount": 3,
    "tip_off": 2,
    "gift": 4,
    "order_gift": 5,
    "void_order": 6,
    "refund": 5,
    "view_reports": 3,
    "edit_menu": 7,
    "manage_employees": 8,
    "system_settings": 10,
}

# 操作对应的金额上限字段名
_ACTION_AMOUNT_FIELD = {
    "discount": "max_discount_pct",
    "tip_off": "max_tip_off_fen",
    "gift": "max_gift_fen",
    "order_gift": "max_order_gift_fen",
}


def check_role_permission(role_level: int, action: str, amount: int = 0) -> bool:
    """校验角色是否有权执行指定操作。

    Args:
        role_level: 角色级别 (1-10)
        action: 操作类型 (discount/tip_off/gift/order_gift/void_order/refund/...)
        amount: 操作涉及金额（折扣时为折扣百分比，其余为分）

    Returns:
        True 表示允许，False 表示拒绝
    """
    if role_level < 1 or role_level > 10:
        return False

    min_level = _ACTION_MIN_LEVEL.get(action)
    if min_level is None:
        # 未知操作默认拒绝
        return False

    if role_level < min_level:
        return False

    # 对于有金额限制的操作，仅校验级别（金额上限需结合 RoleConfig 实例）
    # 此纯函数仅做级别校验
    return True
