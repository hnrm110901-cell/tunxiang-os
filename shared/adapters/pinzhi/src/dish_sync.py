"""
品智菜品同步模块
拉取品智菜品数据并映射为屯象 Ontology Dish 格式
"""
from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()


class PinzhiDishSync:
    """品智菜品同步器"""

    def __init__(self, adapter):
        """
        Args:
            adapter: PinzhiAdapter 实例
        """
        self.adapter = adapter

    async def fetch_dishes(self, brand_id: str) -> list[dict]:
        """
        从品智拉取菜品列表。

        品智 get_dishes 接口以 updatetime 增量拉取；
        此处传 0 获取全量数据，同时拉取菜品类别以补充分类信息。

        Args:
            brand_id: 品牌ID（用于日志标记，品智接口无需此参数）

        Returns:
            品智原始菜品列表
        """
        dishes = await self.adapter.get_dishes(updatetime=0)
        logger.info("pinzhi_dishes_fetched", brand_id=brand_id, count=len(dishes))
        return dishes

    @staticmethod
    def map_to_tunxiang_dish(pinzhi_dish: dict) -> dict:
        """
        将品智原始菜品映射为屯象 Ontology Dish 格式（纯函数）。

        金额单位统一为分(fen)。

        Args:
            pinzhi_dish: 品智原始菜品字典

        Returns:
            屯象标准菜品字典
        """
        # 品智菜品状态: 1=启用, 0=停用
        status_map = {1: "active", 0: "inactive"}
        dish_status = pinzhi_dish.get("status", pinzhi_dish.get("dishStatus", 1))

        # 价格处理（品智金额单位为分）
        price_fen = int(pinzhi_dish.get("dishPrice", pinzhi_dish.get("price", 0)))
        cost_fen = int(pinzhi_dish.get("costPrice", 0))
        member_price_fen = int(pinzhi_dish.get("memberPrice", pinzhi_dish.get("vipPrice", 0)))

        # 规格/SKU
        specs = []
        for spec in pinzhi_dish.get("specList", pinzhi_dish.get("skuList", [])):
            specs.append({
                "spec_id": str(spec.get("specId", spec.get("skuId", ""))),
                "spec_name": str(spec.get("specName", spec.get("skuName", ""))),
                "price_fen": int(spec.get("specPrice", spec.get("skuPrice", 0))),
            })

        # 做法/口味
        practices = []
        for p in pinzhi_dish.get("practiceList", []):
            practices.append({
                "practice_id": str(p.get("practiceId", "")),
                "practice_name": str(p.get("practiceName", "")),
                "extra_price_fen": int(p.get("extraPrice", 0)),
            })

        return {
            "dish_id": str(pinzhi_dish.get("dishId", "")),
            "dish_name": str(pinzhi_dish.get("dishName", "")),
            "dish_code": str(pinzhi_dish.get("dishCode", pinzhi_dish.get("dishNo", ""))),
            "category_id": str(pinzhi_dish.get("categoryId", pinzhi_dish.get("catId", ""))),
            "category_name": str(pinzhi_dish.get("categoryName", pinzhi_dish.get("catName", ""))),
            "price_fen": price_fen,
            "cost_fen": cost_fen,
            "member_price_fen": member_price_fen,
            "unit": str(pinzhi_dish.get("unit", "份")),
            "status": status_map.get(dish_status, "active"),
            "is_weighing": bool(pinzhi_dish.get("isWeighing", 0)),
            "is_temporary": bool(pinzhi_dish.get("isTemporary", 0)),
            "specs": specs,
            "practices": practices,
            "image_url": pinzhi_dish.get("dishImage", pinzhi_dish.get("imageUrl")),
            "description": pinzhi_dish.get("dishDesc", pinzhi_dish.get("description", "")),
            "sort_order": int(pinzhi_dish.get("sortOrder", pinzhi_dish.get("dishSort", 0))),
            "source_system": "pinzhi",
        }

    async def sync_dishes(self, brand_id: str) -> dict:
        """
        完整同步流程：拉取 + 映射 + 返回统计。

        Args:
            brand_id: 品牌ID

        Returns:
            同步统计 {"total": int, "success": int, "failed": int, "dishes": list}
        """
        raw_dishes = await self.fetch_dishes(brand_id)

        mapped: list[dict] = []
        failed = 0
        for raw in raw_dishes:
            try:
                mapped.append(self.map_to_tunxiang_dish(raw))
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "dish_mapping_failed",
                    dish_id=raw.get("dishId"),
                    error=str(exc),
                )
                failed += 1

        logger.info(
            "pinzhi_dishes_synced",
            brand_id=brand_id,
            total=len(raw_dishes),
            success=len(mapped),
            failed=failed,
        )

        return {
            "total": len(raw_dishes),
            "success": len(mapped),
            "failed": failed,
            "dishes": mapped,
        }
