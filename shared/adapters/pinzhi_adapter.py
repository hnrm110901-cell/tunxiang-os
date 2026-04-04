"""
品智POS旧系统适配器 -- 用于数据迁移和并行运行期

封装品智POS系统的数据同步能力，支持：
  - 订单同步：从品智POS拉取订单，转换为屯象格式
  - 菜品同步：从品智菜品库同步到屯象
  - 会员同步：从品智会员数据同步到屯象
  - 库存同步：从品智库存同步
  - 订单状态回写：并行运行期双向同步

底层 API 调用委托给 pinzhi/src/adapter.PinzhiAdapter，
本类在其上封装数据迁移和并行运行期的业务逻辑。

配置（环境变量）：
  PINZHI_BASE_URL       品智网关地址
  PINZHI_TOKEN          API Token
  PINZHI_PAGE_SIZE      分页大小（默认 20）
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import structlog

from .pinzhi.src.adapter import PinzhiAdapter
from .pinzhi.src.order_sync import PinzhiOrderSync
from .pinzhi.src.dish_sync import PinzhiDishSync
from .pinzhi.src.member_sync import PinzhiMemberSync
from .pinzhi.src.inventory_sync import PinzhiInventorySync

logger = structlog.get_logger()

# -- 品智订单状态 -> 屯象统一状态 ------------------------------------
PINZHI_ORDER_STATUS_MAP: Dict[int, str] = {
    0: "pending",       # 未结账
    1: "completed",     # 已结账
    2: "cancelled",     # 已退单
}

# -- 品智回写状态映射 ------------------------------------------------
TUNXIANG_TO_PINZHI_STATUS: Dict[str, int] = {
    "pending": 0,
    "confirmed": 0,
    "preparing": 0,
    "completed": 1,
    "cancelled": 2,
}


class PinzhiPOSAdapter:
    """品智POS旧系统适配器 -- 用于数据迁移和并行运行期

    封装品智POS的全量数据同步能力，包括订单、菜品、会员、库存。
    并行运行期间支持双向状态同步（屯象 -> 品智回写）。

    使用示例：
        async with PinzhiPOSAdapter() as adapter:
            orders = await adapter.sync_orders(since=yesterday)
            menu = await adapter.sync_menu(store_id="OGN001")
            members = await adapter.sync_members(since=last_week)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: int = 30,
        retry_times: int = 3,
        mock_mode: bool = False,
    ):
        self.mock_mode = mock_mode
        self._base_url = base_url or os.environ.get("PINZHI_BASE_URL", "")
        self._token = token or os.environ.get("PINZHI_TOKEN", "")

        if not self.mock_mode:
            if not self._base_url:
                raise ValueError("PINZHI_BASE_URL 不能为空（非 mock 模式）")
            if not self._token:
                raise ValueError("PINZHI_TOKEN 不能为空（非 mock 模式）")

        self._timeout = timeout
        self._retry_times = retry_times

        # 延迟初始化底层适配器（mock 模式下不需要）
        self._inner: Optional[PinzhiAdapter] = None
        self._order_sync: Optional[PinzhiOrderSync] = None
        self._dish_sync: Optional[PinzhiDishSync] = None
        self._member_sync: Optional[PinzhiMemberSync] = None
        self._inventory_sync: Optional[PinzhiInventorySync] = None

        if not self.mock_mode:
            self._init_inner()

        logger.info(
            "pinzhi_pos_adapter_init",
            mock_mode=self.mock_mode,
            base_url=self._base_url[:30] + "..." if len(self._base_url) > 30 else self._base_url,
        )

    def _init_inner(self) -> None:
        """初始化底层品智适配器及各同步模块"""
        config = {
            "base_url": self._base_url,
            "token": self._token,
            "timeout": self._timeout,
            "retry_times": self._retry_times,
        }
        self._inner = PinzhiAdapter(config)
        self._order_sync = PinzhiOrderSync(self._inner)
        self._dish_sync = PinzhiDishSync(self._inner)
        self._member_sync = PinzhiMemberSync(self._inner)
        self._inventory_sync = PinzhiInventorySync(self._inner)

    # -- 订单同步 ---------------------------------------------------

    async def sync_orders(self, since: datetime) -> list[dict]:
        """从品智POS拉取订单，转换为屯象格式

        按天遍历 [since, today] 区间，拉取所有订单并映射为屯象标准格式。

        Args:
            since: 起始时间

        Returns:
            屯象统一订单格式列表
        """
        if self.mock_mode:
            return self._mock_orders(since)

        if self._order_sync is None:
            raise RuntimeError("品智适配器未初始化")

        start_date = since.strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")

        raw_orders = await self._order_sync.fetch_orders(
            store_id="",  # 全部门店
            start_date=start_date,
            end_date=end_date,
        )

        mapped: list[dict] = []
        for raw in raw_orders:
            try:
                mapped.append(PinzhiOrderSync.map_to_tunxiang_order(raw))
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "pinzhi_order_mapping_failed",
                    bill_id=raw.get("billId"),
                    error=str(exc),
                )

        logger.info(
            "pinzhi_orders_synced",
            since=since.isoformat(),
            total=len(raw_orders),
            mapped=len(mapped),
        )
        return mapped

    # -- 菜品同步 ---------------------------------------------------

    async def sync_menu(self, store_id: str) -> list[dict]:
        """从品智菜品库同步到屯象

        拉取品智全量菜品数据，映射为屯象 Ontology Dish 格式。

        Args:
            store_id: 门店ID（品智 ognid）

        Returns:
            屯象统一菜品格式列表
        """
        if self.mock_mode:
            return self._mock_menu(store_id)

        if self._dish_sync is None:
            raise RuntimeError("品智适配器未初始化")

        raw_dishes = await self._dish_sync.fetch_dishes(brand_id=store_id)

        mapped: list[dict] = []
        for raw in raw_dishes:
            try:
                mapped.append(PinzhiDishSync.map_to_tunxiang_dish(raw))
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "pinzhi_dish_mapping_failed",
                    dish_id=raw.get("dishId"),
                    error=str(exc),
                )

        logger.info(
            "pinzhi_menu_synced",
            store_id=store_id,
            total=len(raw_dishes),
            mapped=len(mapped),
        )
        return mapped

    # -- 会员同步 ---------------------------------------------------

    async def sync_members(self, since: datetime) -> list[dict]:
        """从品智会员数据同步到屯象

        拉取品智会员列表，映射为屯象 Customer Golden ID 格式。
        品智会员接口不支持增量，每次返回全量，由调用方根据 since 过滤。

        Args:
            since: 起始时间（用于日志和统计，品智端不支持增量筛选）

        Returns:
            屯象统一会员格式列表
        """
        if self.mock_mode:
            return self._mock_members(since)

        if self._member_sync is None:
            raise RuntimeError("品智适配器未初始化")

        raw_members = await self._member_sync.fetch_members(store_id="")

        mapped: list[dict] = []
        for raw in raw_members:
            try:
                mapped.append(PinzhiMemberSync.map_to_golden_id(raw))
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "pinzhi_member_mapping_failed",
                    member_id=raw.get("customerId", raw.get("id")),
                    error=str(exc),
                )

        logger.info(
            "pinzhi_members_synced",
            since=since.isoformat(),
            total=len(raw_members),
            mapped=len(mapped),
        )
        return mapped

    # -- 库存同步 ---------------------------------------------------

    async def sync_inventory(self, store_id: str) -> list[dict]:
        """从品智库存同步

        拉取品智门店库存/食材数据，映射为屯象 Ontology Ingredient 格式。

        Args:
            store_id: 门店ID（品智 ognid）

        Returns:
            屯象统一食材格式列表
        """
        if self.mock_mode:
            return self._mock_inventory(store_id)

        if self._inventory_sync is None:
            raise RuntimeError("品智适配器未初始化")

        raw_items = await self._inventory_sync.fetch_inventory(store_id)

        mapped: list[dict] = []
        for raw in raw_items:
            try:
                mapped.append(PinzhiInventorySync.map_to_tunxiang_ingredient(raw))
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "pinzhi_inventory_mapping_failed",
                    item_id=raw.get("ingredientId", raw.get("id")),
                    error=str(exc),
                )

        logger.info(
            "pinzhi_inventory_synced",
            store_id=store_id,
            total=len(raw_items),
            mapped=len(mapped),
        )
        return mapped

    # -- 订单状态回写 -----------------------------------------------

    async def push_order_status(self, order_id: str, status: str) -> bool:
        """回写订单状态到品智（并行运行期）

        在屯象与品智并行运行期间，屯象侧的订单状态变更需要回写到品智，
        保持两个系统的数据一致性。

        Args:
            order_id: 屯象订单ID（对应品智 billId）
            status: 屯象统一状态 (pending/confirmed/preparing/completed/cancelled)

        Returns:
            是否成功
        """
        if self.mock_mode:
            logger.info(
                "pinzhi_push_order_status_mock",
                order_id=order_id,
                status=status,
            )
            return True

        if self._inner is None:
            raise RuntimeError("品智适配器未初始化")

        pinzhi_status = TUNXIANG_TO_PINZHI_STATUS.get(status)
        if pinzhi_status is None:
            logger.warning(
                "pinzhi_unknown_status_mapping",
                order_id=order_id,
                status=status,
            )
            return False

        # 品智回写接口（如有）
        # 注意：品智POS系统不一定支持外部回写订单状态
        # 此处预留接口，实际对接时根据品智网关能力实现
        try:
            params = {
                "billId": order_id,
                "billStatus": pinzhi_status,
            }
            params = self._inner._add_sign(params)
            await self._inner._request(
                "POST", "/pinzhi/updateOrderStatus.do", data=params,
            )
            logger.info(
                "pinzhi_order_status_pushed",
                order_id=order_id,
                status=status,
                pinzhi_status=pinzhi_status,
            )
            return True
        except (ConnectionError, TimeoutError, RuntimeError) as exc:
            logger.error(
                "pinzhi_push_order_status_failed",
                order_id=order_id,
                status=status,
                error=str(exc),
            )
            return False

    # -- Mock 数据 --------------------------------------------------

    @staticmethod
    def _mock_orders(since: datetime) -> list[dict]:
        """Mock 订单数据"""
        return [
            {
                "order_id": "PZ_MOCK_001",
                "order_number": "20260401001",
                "order_type": "dine_in",
                "order_status": "completed",
                "table_number": "A01",
                "items": [
                    {
                        "item_id": "PZ_MOCK_001_1",
                        "dish_id": "D001",
                        "dish_name": "红烧肉",
                        "quantity": 1,
                        "unit_price_fen": 8800,
                        "subtotal_fen": 8800,
                    },
                    {
                        "item_id": "PZ_MOCK_001_2",
                        "dish_id": "D002",
                        "dish_name": "米饭",
                        "quantity": 2,
                        "unit_price_fen": 300,
                        "subtotal_fen": 600,
                    },
                ],
                "subtotal_fen": 9400,
                "discount_fen": 0,
                "total_fen": 9400,
                "source_system": "pinzhi",
            },
        ]

    @staticmethod
    def _mock_menu(store_id: str) -> list[dict]:
        """Mock 菜品数据"""
        return [
            {
                "dish_id": "D001",
                "dish_name": "红烧肉",
                "dish_code": "HSR001",
                "category_id": "CAT01",
                "category_name": "热菜",
                "price_fen": 8800,
                "cost_fen": 3200,
                "member_price_fen": 7800,
                "unit": "份",
                "status": "active",
                "source_system": "pinzhi",
            },
            {
                "dish_id": "D002",
                "dish_name": "米饭",
                "dish_code": "MF001",
                "category_id": "CAT02",
                "category_name": "主食",
                "price_fen": 300,
                "cost_fen": 100,
                "member_price_fen": 300,
                "unit": "碗",
                "status": "active",
                "source_system": "pinzhi",
            },
        ]

    @staticmethod
    def _mock_members(since: datetime) -> list[dict]:
        """Mock 会员数据"""
        return [
            {
                "golden_id": None,
                "name": "张三",
                "gender": 1,
                "identities": [
                    {"type": "phone", "value": "13800138001"},
                    {"type": "pinzhi_card", "value": "VIP00001"},
                ],
                "level": "gold",
                "balance_fen": 50000,
                "points": 1200,
                "total_consumption_fen": 380000,
                "visit_count": 25,
                "source_system": "pinzhi",
            },
        ]

    @staticmethod
    def _mock_inventory(store_id: str) -> list[dict]:
        """Mock 库存数据"""
        return [
            {
                "ingredient_id": "ING001",
                "ingredient_name": "五花肉",
                "ingredient_code": "WHR001",
                "category": "鲜肉",
                "unit": "kg",
                "unit_price_fen": 3500,
                "stock_qty": 50.0,
                "alert_qty": 10.0,
                "status": "active",
                "source_system": "pinzhi",
            },
        ]

    # -- 资源管理 ---------------------------------------------------

    async def close(self) -> None:
        """释放资源"""
        if self._inner is not None:
            await self._inner.close()
        logger.info("pinzhi_pos_adapter_closed")

    async def __aenter__(self) -> PinzhiPOSAdapter:
        return self

    async def __aexit__(
        self, exc_type: type, exc_val: BaseException, exc_tb: Any,
    ) -> None:
        await self.close()
