"""
品智库存同步模块
拉取品智库存/食材数据并映射为屯象 Ontology Ingredient 格式
"""
from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()


class PinzhiInventorySync:
    """品智库存同步器"""

    def __init__(self, adapter):
        """
        Args:
            adapter: PinzhiAdapter 实例
        """
        self.adapter = adapter

    async def fetch_inventory(self, store_id: str) -> list[dict]:
        """
        从品智拉取指定门店的库存/食材列表。

        品智无独立库存接口时，通过菜品做法+配料接口间接获取食材信息。

        Args:
            store_id: 门店 ognid

        Returns:
            品智原始库存/食材列表
        """
        items: list[dict] = []

        # 尝试专用库存接口
        params = {"ognid": store_id}
        params = self.adapter._add_sign(params)
        try:
            response = await self.adapter._request(
                "GET", "/pinzhi/queryInventory.do", params=params
            )
            items = response.get("data", [])
        except (ConnectionError, TimeoutError, Exception) as exc:
            logger.warning(
                "pinzhi_inventory_endpoint_unavailable",
                store_id=store_id,
                error=str(exc),
            )
            # 降级：从做法/配料接口获取食材数据
            try:
                practice_data = await self.adapter.get_practice(ognid=store_id)
                for item in practice_data:
                    if item.get("type") == "ingredient" or item.get("practiceType") == 2:
                        items.append(item)
            except (ConnectionError, TimeoutError, Exception) as fallback_exc:
                logger.error(
                    "pinzhi_inventory_fallback_failed",
                    store_id=store_id,
                    error=str(fallback_exc),
                )

        logger.info(
            "pinzhi_inventory_fetched",
            store_id=store_id,
            count=len(items),
        )
        return items

    @staticmethod
    def map_to_tunxiang_ingredient(pinzhi_item: dict) -> dict:
        """
        将品智库存/食材数据映射为屯象 Ontology Ingredient 格式（纯函数）。

        金额单位统一为分(fen)，重量单位为克(g)。

        Args:
            pinzhi_item: 品智原始食材/库存字典

        Returns:
            屯象标准食材字典
        """
        # 价格（分）
        unit_price_fen = int(
            pinzhi_item.get("unitPrice", pinzhi_item.get("costPrice", 0))
        )

        # 库存数量
        stock_qty = float(
            pinzhi_item.get("stockQty", pinzhi_item.get("quantity", 0))
        )

        # 预警阈值
        alert_qty = float(
            pinzhi_item.get("alertQty", pinzhi_item.get("minStock", 0))
        )

        # 状态
        status_val = pinzhi_item.get("status", 1)
        status_map = {1: "active", 0: "inactive", 2: "out_of_stock"}

        return {
            "ingredient_id": str(
                pinzhi_item.get("ingredientId",
                                pinzhi_item.get("practiceId",
                                                pinzhi_item.get("id", "")))
            ),
            "ingredient_name": str(
                pinzhi_item.get("ingredientName",
                                pinzhi_item.get("practiceName",
                                                pinzhi_item.get("name", "")))
            ),
            "ingredient_code": str(
                pinzhi_item.get("ingredientCode",
                                pinzhi_item.get("code", ""))
            ),
            "category": str(
                pinzhi_item.get("category",
                                pinzhi_item.get("typeName", ""))
            ),
            "unit": str(pinzhi_item.get("unit", "g")),
            "unit_price_fen": unit_price_fen,
            "stock_qty": stock_qty,
            "alert_qty": alert_qty,
            "status": status_map.get(status_val, "active"),
            "supplier_id": str(pinzhi_item.get("supplierId", "")),
            "supplier_name": str(pinzhi_item.get("supplierName", "")),
            "shelf_life_days": int(pinzhi_item.get("shelfLifeDays", 0)),
            "storage_condition": str(
                pinzhi_item.get("storageCondition", "normal")
            ),
            "last_purchase_date": pinzhi_item.get("lastPurchaseDate"),
            "expiry_date": pinzhi_item.get("expiryDate"),
            "batch_no": pinzhi_item.get("batchNo"),
            "source_system": "pinzhi",
        }

    async def sync_inventory(self, store_id: str) -> dict:
        """
        完整同步流程：拉取 + 映射 + 返回统计。

        Args:
            store_id: 门店 ognid

        Returns:
            同步统计 {"total": int, "success": int, "failed": int, "ingredients": list}
        """
        raw_items = await self.fetch_inventory(store_id)

        mapped: list[dict] = []
        failed = 0
        for raw in raw_items:
            try:
                mapped.append(self.map_to_tunxiang_ingredient(raw))
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "ingredient_mapping_failed",
                    item_id=raw.get("ingredientId", raw.get("id")),
                    error=str(exc),
                )
                failed += 1

        logger.info(
            "pinzhi_inventory_synced",
            store_id=store_id,
            total=len(raw_items),
            success=len(mapped),
            failed=failed,
        )

        return {
            "total": len(raw_items),
            "success": len(mapped),
            "failed": failed,
            "ingredients": mapped,
        }
