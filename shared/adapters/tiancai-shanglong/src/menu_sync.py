"""
天财商龙 → 屯象OS 菜品数据迁移

天财菜品 API（来源：官方文档 #/46）：
  GET /api/menu/getItemList  — 获取菜品列表（分页）

字段映射：
  item_code     → dish_code（天财菜品编码）
  item_name     → dish_name
  sale_price    → current_price_fen（分）
  cost_price    → cost_fen（分）
  category_name → 用于推断 dish_category
  kitchen_code  → kds_zone_code
  item_status   → is_available（1=可用）
  unit          → unit（份/碗/个等）

迁移策略：
  - 采用 UPSERT ON CONFLICT (tenant_id, dish_code)
  - 原有 dish_code 若已存在则更新名称/价格，不覆盖门店微调
  - 所有金额统一转换为分（整数），不使用浮点
  - 失败的单条记录记录到 migration_errors，不阻断整体迁移
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

_MENU_PATH = "/api/menu/getItemList"
_MAX_PAGE_SIZE = 200


@dataclass
class DishMigrationResult:
    total_fetched: int = 0
    total_upserted: int = 0
    total_skipped: int = 0
    errors: list[dict] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_fetched == 0:
            return 1.0
        return (self.total_upserted + self.total_skipped) / self.total_fetched


class TiancaiMenuSync:
    """
    天财商龙菜品迁移器。

    Usage:
        adapter = TiancaiShanglongAdapter(config)
        sync = TiancaiMenuSync(adapter)
        result = await sync.pull_and_upsert(tenant_id, brand_id)
    """

    def __init__(self, adapter) -> None:
        self._adapter = adapter

    async def fetch_all_dishes(self, max_pages: int = 20) -> list[dict]:
        """
        分页拉取天财全量菜品列表。

        天财菜品接口：POST /api/menu/getItemList
        参数：centerId, shopId, pageNo, pageSize

        注：天财开放平台文档中菜品列表接口在部分版本为 getdishlist，
        本实现优先尝试 getItemList，失败时降级返回空列表。
        """
        all_items: list[dict] = []
        page = 1

        while page <= max_pages:
            try:
                data = await self._adapter._request(
                    _MENU_PATH,
                    {
                        "centerId": self._adapter.center_id,
                        "shopId": self._adapter.shop_id,
                        "pageNo": page,
                        "pageSize": _MAX_PAGE_SIZE,
                    },
                )
            except Exception as exc:
                logger.warning(
                    "tiancai_menu_fetch_failed",
                    page=page,
                    error=str(exc),
                )
                break

            items = data.get("itemList", data.get("dishList", data.get("list", [])))
            all_items.extend(items)

            page_info = data.get("pageInfo", {})
            total = int(page_info.get("total", len(items)))
            if page * _MAX_PAGE_SIZE >= total or not items:
                break
            page += 1

        logger.info("tiancai_menu_fetched", total=len(all_items), pages=page)
        return all_items

    def to_dish_dict(self, raw: dict, tenant_id: str, brand_id: str) -> dict:
        """
        将天财菜品原始数据转换为屯象 dishes 表结构。

        金额字段说明：
          sale_price 单位为分（天财），直接赋给 current_price_fen
          cost_price 单位为分（天财），直接赋给 cost_fen
        """
        # 金额（天财统一用分）
        sale_price_raw = raw.get("sale_price", raw.get("salePrice", 0))
        cost_price_raw = raw.get("cost_price", raw.get("costPrice", 0))
        current_price_fen = int(sale_price_raw) if sale_price_raw else 0
        cost_fen = int(cost_price_raw) if cost_price_raw else 0

        # 状态
        item_status = raw.get("item_status", raw.get("itemStatus", raw.get("status", 1)))
        is_available = int(item_status) == 1 if item_status is not None else True

        # KDS 分区（天财 kitchen_code → 屯象 kds_zone_code）
        kds_zone_code = str(raw.get("kitchen_code", raw.get("kitchenCode", ""))) or None

        # 单位
        unit = raw.get("unit", "份")

        # 菜品分类（天财的 category_name 映射到屯象）
        category_name = raw.get("category_name", raw.get("categoryName", ""))

        return {
            "tenant_id": tenant_id,
            "brand_id": brand_id,
            "dish_code": str(raw.get("item_code", raw.get("itemCode", ""))),
            "dish_name": str(raw.get("item_name", raw.get("itemName", "未知菜品"))),
            "category_name": category_name,
            "current_price_fen": current_price_fen,
            "cost_fen": cost_fen,
            "unit": unit,
            "is_available": is_available,
            "kds_zone_code": kds_zone_code,
            "source": "tiancai_migration",
            "source_item_id": str(raw.get("item_id", raw.get("itemId", ""))),
        }

    async def pull_and_upsert(
        self,
        tenant_id: str,
        brand_id: str,
        dry_run: bool = False,
    ) -> DishMigrationResult:
        """
        拉取天财全量菜品并 UPSERT 到屯象 dishes 表。

        dry_run=True：只拉取和转换，不写入数据库。
        """
        result = DishMigrationResult()

        raw_items = await self.fetch_all_dishes()
        result.total_fetched = len(raw_items)

        if dry_run or not raw_items:
            logger.info(
                "tiancai_menu_dry_run" if dry_run else "tiancai_menu_empty",
                fetched=result.total_fetched,
            )
            return result

        dishes = []
        for raw in raw_items:
            try:
                dishes.append(self.to_dish_dict(raw, tenant_id, brand_id))
            except (KeyError, ValueError, TypeError) as exc:
                result.errors.append({
                    "item_code": raw.get("item_code"),
                    "error": str(exc),
                })

        await self._upsert_dishes(dishes, result)

        logger.info(
            "tiancai_menu_sync_done",
            tenant_id=tenant_id,
            fetched=result.total_fetched,
            upserted=result.total_upserted,
            errors=len(result.errors),
        )
        return result

    async def _upsert_dishes(
        self,
        dishes: list[dict],
        result: DishMigrationResult,
    ) -> None:
        """批量 UPSERT dishes 表（ON CONFLICT dish_code 更新价格和状态）。"""
        try:
            from shared.ontology.src.database import async_session_factory
            from sqlalchemy import text

            async with async_session_factory() as db:
                for d in dishes:
                    try:
                        await db.execute(text("""
                            INSERT INTO dishes
                              (tenant_id, brand_id, dish_code, dish_name,
                               category_name, current_price_fen, cost_fen,
                               unit, is_available, kds_zone_code,
                               source, source_item_id,
                               created_at, updated_at)
                            VALUES
                              (:tenant_id, :brand_id, :dish_code, :dish_name,
                               :category_name, :current_price_fen, :cost_fen,
                               :unit, :is_available, :kds_zone_code,
                               :source, :source_item_id,
                               NOW(), NOW())
                            ON CONFLICT (tenant_id, dish_code)
                            DO UPDATE SET
                              dish_name          = EXCLUDED.dish_name,
                              current_price_fen  = EXCLUDED.current_price_fen,
                              cost_fen           = EXCLUDED.cost_fen,
                              is_available       = EXCLUDED.is_available,
                              kds_zone_code      = EXCLUDED.kds_zone_code,
                              updated_at         = NOW()
                        """), d)
                        result.total_upserted += 1
                    except Exception as exc:  # noqa: BLE001
                        result.errors.append({
                            "dish_code": d.get("dish_code"),
                            "error": str(exc),
                        })
                        result.total_skipped += 1

                await db.commit()

        except Exception as exc:  # noqa: BLE001 — DB 不可用时整体标记失败
            logger.error("tiancai_menu_upsert_failed", error=str(exc), exc_info=True)
            result.errors.append({"db_error": str(exc)})
