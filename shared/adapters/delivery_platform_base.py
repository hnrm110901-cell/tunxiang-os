"""
外卖平台统一接口基类
定义美团/饿了么等外卖平台适配器的统一接口规范

所有外卖平台适配器必须实现本基类的全部方法，
确保业务层可以通过工厂模式无差别调用不同平台。
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger()


class DeliveryPlatformError(Exception):
    """外卖平台错误基类"""

    def __init__(self, platform: str, code: int, message: str):
        self.platform = platform
        self.code = code
        self.message = message
        super().__init__(f"[{platform}] {code}: {message}")


class DeliveryPlatformTimeoutError(DeliveryPlatformError):
    """网络超时错误"""

    pass


class DeliveryPlatformSignError(DeliveryPlatformError):
    """签名校验失败"""

    pass


class DeliveryPlatformAdapter(ABC):
    """外卖平台统一接口基类

    所有外卖平台（美团、饿了么等）的适配器必须实现本基类，
    确保上层业务代码可以通过统一接口操作不同平台。

    统一订单格式（屯象内部）：
        platform: str           平台标识 (meituan / eleme)
        platform_order_id: str  平台侧订单ID
        day_seq: str            日流水号
        status: str             统一状态 (pending/confirmed/preparing/delivering/completed/cancelled/refunded)
        items: list[dict]       订单明细（name, quantity, price_fen, sku_id, notes, internal_dish_id）
        total_fen: int          订单总额（分）
        customer_phone: str     顾客手机
        delivery_address: str   配送地址
        expected_time: str      期望送达时间
        notes: str              订单备注
    """

    @abstractmethod
    async def pull_orders(self, store_id: str, since: datetime) -> list[dict]:
        """拉取指定时间之后的新订单

        Args:
            store_id: 屯象门店ID
            since: 起始时间

        Returns:
            屯象统一订单格式列表
        """
        ...

    @abstractmethod
    async def accept_order(self, order_id: str) -> bool:
        """接受订单

        Args:
            order_id: 平台侧订单ID

        Returns:
            是否成功
        """
        ...

    @abstractmethod
    async def reject_order(self, order_id: str, reason: str) -> bool:
        """拒绝订单

        Args:
            order_id: 平台侧订单ID
            reason: 拒单原因

        Returns:
            是否成功
        """
        ...

    @abstractmethod
    async def mark_ready(self, order_id: str) -> bool:
        """标记订单出餐完成，等待骑手取餐

        Args:
            order_id: 平台侧订单ID

        Returns:
            是否成功
        """
        ...

    @abstractmethod
    async def sync_menu(self, store_id: str, dishes: list[dict]) -> dict:
        """同步菜品到外卖平台

        Args:
            store_id: 屯象门店ID
            dishes: 屯象统一菜品格式列表（参考 UnifiedDish）

        Returns:
            同步结果 {"synced": int, "failed": int, "errors": list}
        """
        ...

    @abstractmethod
    async def update_stock(self, store_id: str, dish_id: str, available: bool) -> bool:
        """更新单个菜品的上下架状态

        Args:
            store_id: 屯象门店ID
            dish_id: 平台侧菜品ID
            available: True=上架, False=售罄下架

        Returns:
            是否成功
        """
        ...

    @abstractmethod
    async def get_order_detail(self, order_id: str) -> dict:
        """获取订单详情

        Args:
            order_id: 平台侧订单ID

        Returns:
            屯象统一订单格式
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """释放资源（HTTP 连接等）"""
        ...

    async def __aenter__(self) -> "DeliveryPlatformAdapter":
        return self

    async def __aexit__(self, exc_type: type, exc_val: BaseException, exc_tb: Any) -> None:
        await self.close()
