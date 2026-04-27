"""菜单一键多平台发布 — 美团/饿了么/抖音同步

核心流程:
1. 商户在屯象OS更新菜品(价格/上下架/描述/图片)
2. 点击"一键发布"
3. 系统自动同步到: 美团外卖/饿了么/抖音团购
4. 记录同步结果(成功/失败/部分成功)
5. 失败自动重试(最多3次)

平台适配:
- 美团: 菜品名/价格/SKU/库存/上下架
- 饿了么: 菜品名/价格/分类/图片/上下架
- 抖音: 团购商品名/价格/库存/有效期
"""

import asyncio
import uuid as _uuid
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class MultiPlatformPublishService:
    """菜单一键多平台发布服务。"""

    # 支持的平台
    PLATFORMS: list[str] = ["meituan", "eleme", "douyin"]
    MAX_RETRY: int = 3

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    # ──────────────────────────────────────────────
    # 一键发布到所有平台
    # ──────────────────────────────────────────────

    async def publish_to_all(
        self,
        store_id: str,
        dish_ids: Optional[list[str]] = None,
    ) -> dict:
        """一键发布到所有平台。

        Args:
            store_id: 门店ID
            dish_ids: 菜品ID列表, None时发布全部active菜品

        Returns:
            {platforms: [{name, status, synced_count, failed_count, errors}], summary: {...}}
        """
        await self._set_tenant()

        # 获取待发布菜品
        dishes = await self._get_dishes(store_id, dish_ids)
        if not dishes:
            raise ValueError("没有找到可发布的菜品")

        actual_dish_ids = [d["id"] for d in dishes]

        platform_results: list[dict] = []
        total_synced = 0
        total_failed = 0

        for platform in self.PLATFORMS:
            result = await self._publish_single_platform(
                store_id=store_id,
                platform=platform,
                dishes=dishes,
            )
            platform_results.append(result)
            total_synced += result["synced_count"]
            total_failed += result["failed_count"]

        overall_status = "success"
        if total_failed > 0 and total_synced > 0:
            overall_status = "partial"
        elif total_failed > 0 and total_synced == 0:
            overall_status = "failed"

        log.info(
            "multi_platform_publish.all",
            store_id=store_id,
            dish_count=len(dishes),
            total_synced=total_synced,
            total_failed=total_failed,
            overall_status=overall_status,
        )

        return {
            "platforms": platform_results,
            "summary": {
                "store_id": store_id,
                "dish_count": len(dishes),
                "dish_ids": actual_dish_ids,
                "total_synced": total_synced,
                "total_failed": total_failed,
                "status": overall_status,
                "published_at": datetime.utcnow().isoformat(),
            },
        }

    # ──────────────────────────────────────────────
    # 发布到单个平台
    # ──────────────────────────────────────────────

    async def publish_to_platform(
        self,
        store_id: str,
        platform: str,
        dish_ids: Optional[list[str]] = None,
    ) -> dict:
        """发布到单个平台。

        Args:
            store_id: 门店ID
            platform: meituan / eleme / douyin
            dish_ids: 菜品ID列表, None时发布全部

        Returns:
            {name, status, synced_count, failed_count, errors, items}
        """
        if platform not in self.PLATFORMS:
            raise ValueError(f"不支持的平台: {platform!r}, 支持: {self.PLATFORMS}")

        await self._set_tenant()

        dishes = await self._get_dishes(store_id, dish_ids)
        if not dishes:
            raise ValueError("没有找到可发布的菜品")

        result = await self._publish_single_platform(
            store_id=store_id,
            platform=platform,
            dishes=dishes,
        )

        log.info(
            "multi_platform_publish.single",
            store_id=store_id,
            platform=platform,
            synced_count=result["synced_count"],
            failed_count=result["failed_count"],
        )

        return result

    # ──────────────────────────────────────────────
    # 各平台同步状态概览
    # ──────────────────────────────────────────────

    async def get_sync_status(self, store_id: str) -> dict:
        """各平台同步状态概览。

        当前为模拟实现，返回各平台最近同步状态。
        后续接入真实平台API后，从同步日志表查询。

        Args:
            store_id: 门店ID

        Returns:
            各平台同步状态
        """
        await self._set_tenant()

        # 获取门店菜品总数
        count_result = await self.db.execute(
            text("""
                SELECT COUNT(*)
                FROM dishes
                WHERE tenant_id = :tid
                  AND is_deleted = false
                  AND is_available = true
            """),
            {"tid": _uuid.UUID(self.tenant_id)},
        )
        total_dishes: int = count_result.scalar() or 0

        # 模拟各平台状态
        # TODO: 真实接入后，从 platform_sync_logs 表查询最近同步记录
        platforms_status: list[dict] = []
        for platform in self.PLATFORMS:
            platforms_status.append({
                "platform": platform,
                "total_dishes": total_dishes,
                "synced_count": 0,
                "pending_count": total_dishes,
                "failed_count": 0,
                "last_sync_at": None,
                "status": "not_synced",
            })

        return {
            "store_id": store_id,
            "total_dishes": total_dishes,
            "platforms": platforms_status,
        }

    # ──────────────────────────────────────────────
    # 重试失败项
    # ──────────────────────────────────────────────

    async def retry_failed(
        self,
        store_id: str,
        platform: str,
    ) -> dict:
        """重试失败项。

        当前为模拟实现。真实接入后，从同步日志表查询失败记录并重试。

        Args:
            store_id: 门店ID
            platform: 目标平台

        Returns:
            重试结果
        """
        if platform not in self.PLATFORMS:
            raise ValueError(f"不支持的平台: {platform!r}, 支持: {self.PLATFORMS}")

        await self._set_tenant()

        # TODO: 真实接入后的流程:
        # 1. 从 platform_sync_logs 查询该平台的失败记录
        # 2. 逐条重试(最多 MAX_RETRY 次)
        # 3. 更新同步状态

        log.info(
            "multi_platform_publish.retry",
            store_id=store_id,
            platform=platform,
        )

        return {
            "store_id": store_id,
            "platform": platform,
            "retry_count": 0,
            "success_count": 0,
            "still_failed_count": 0,
            "message": "当前无失败记录需要重试",
        }

    # ──────────────────────────────────────────────
    # 平台格式转换
    # ──────────────────────────────────────────────

    def _transform_to_meituan(self, dishes: list[dict]) -> list[dict]:
        """转换为美团格式。

        美团外卖API字段映射:
          - dish_name → name
          - price_fen → min_price(分)
          - dish_code → sku_id
          - is_available → is_online
          - stock: 默认999(无限)
        """
        items: list[dict] = []
        for dish in dishes:
            items.append({
                "name": dish["dish_name"],
                "min_price": dish["price_fen"],
                "sku_id": dish.get("dish_code") or str(dish["id"]),
                "is_online": 1 if dish.get("is_available", True) else 0,
                "stock": 999,
                "description": dish.get("description", ""),
                "picture": dish.get("image_url", ""),
                "category_name": dish.get("category_name", "默认分类"),
            })
        return items

    def _transform_to_eleme(self, dishes: list[dict]) -> list[dict]:
        """转换为饿了么格式。

        饿了么API字段映射:
          - dish_name → name
          - price_fen → price(分)
          - category_name → categoryName
          - image_url → imagePath
          - is_available → onShelf
        """
        items: list[dict] = []
        for dish in dishes:
            items.append({
                "name": dish["dish_name"],
                "price": dish["price_fen"],
                "categoryName": dish.get("category_name", "默认分类"),
                "imagePath": dish.get("image_url", ""),
                "onShelf": dish.get("is_available", True),
                "description": dish.get("description", ""),
                "skuId": dish.get("dish_code") or str(dish["id"]),
            })
        return items

    def _transform_to_douyin(self, dishes: list[dict]) -> list[dict]:
        """转换为抖音团购格式。

        抖音团购API字段映射:
          - dish_name → product_name
          - price_fen → sold_price(分)
          - original_price: price_fen(原价=售价)
          - stock_qty: 默认999
          - valid_days: 默认30天有效期
        """
        items: list[dict] = []
        for dish in dishes:
            items.append({
                "product_name": dish["dish_name"],
                "sold_price": dish["price_fen"],
                "original_price": dish["price_fen"],
                "stock_qty": 999,
                "valid_days": 30,
                "description": dish.get("description", ""),
                "cover_image": dish.get("image_url", ""),
                "category": dish.get("category_name", "默认分类"),
            })
        return items

    # ──────────────────────────────────────────────
    # 内部方法
    # ──────────────────────────────────────────────

    async def _set_tenant(self) -> None:
        """设置 RLS 租户上下文。"""
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    async def _get_dishes(
        self,
        store_id: str,
        dish_ids: Optional[list[str]] = None,
    ) -> list[dict]:
        """获取待发布菜品列表。"""
        where = """
            WHERE d.tenant_id = :tid
              AND d.is_deleted = false
              AND d.is_available = true
        """
        params: dict = {"tid": _uuid.UUID(self.tenant_id)}

        if dish_ids:
            placeholders = ", ".join(f":did_{i}" for i in range(len(dish_ids)))
            where += f" AND d.id IN ({placeholders})"
            for i, did in enumerate(dish_ids):
                params[f"did_{i}"] = _uuid.UUID(did)

        result = await self.db.execute(
            text(f"""
                SELECT d.id, d.dish_name, d.dish_code, d.price_fen,
                       d.description, d.image_url, d.category_id,
                       d.is_available
                FROM dishes d
                {where}
                ORDER BY d.sort_order, d.dish_name
            """),
            params,
        )

        return [
            {
                "id": str(r[0]),
                "dish_name": r[1],
                "dish_code": r[2],
                "price_fen": r[3],
                "description": r[4],
                "image_url": r[5],
                "category_id": str(r[6]) if r[6] else None,
                "is_available": r[7],
                "category_name": None,  # 可扩展：关联分类表获取名称
            }
            for r in result.fetchall()
        ]

    async def _publish_single_platform(
        self,
        store_id: str,
        platform: str,
        dishes: list[dict],
    ) -> dict:
        """发布到单个平台(含格式转换+API调用模拟)。

        Args:
            store_id: 门店ID
            platform: 目标平台
            dishes: 菜品列表

        Returns:
            {name, status, synced_count, failed_count, errors, items}
        """
        # 1. 转换为平台格式
        transform_map = {
            "meituan": self._transform_to_meituan,
            "eleme": self._transform_to_eleme,
            "douyin": self._transform_to_douyin,
        }
        transformer = transform_map[platform]
        platform_items = transformer(dishes)

        # 2. 调用平台API（当前模拟，预留真实HTTP调用位置）
        synced: list[dict] = []
        failed: list[dict] = []
        errors: list[str] = []

        for i, item in enumerate(platform_items):
            try:
                # ━━━ TODO: 真实平台API调用 ━━━
                # 美团: await self._call_meituan_api(store_id, item)
                # 饿了么: await self._call_eleme_api(store_id, item)
                # 抖音: await self._call_douyin_api(store_id, item)
                #
                # 真实调用示例(美团):
                #   async with httpx.AsyncClient() as client:
                #       resp = await client.post(
                #           f"{MEITUAN_API_BASE}/food/save",
                #           headers={"Authorization": f"Bearer {access_token}"},
                #           json=item,
                #           timeout=10.0,
                #       )
                #       if resp.status_code != 200:
                #           raise RuntimeError(f"美团API错误: {resp.text}")
                # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━

                # 模拟成功
                synced.append({
                    "dish_name": item.get("name") or item.get("product_name", ""),
                    "platform_item": item,
                    "status": "synced",
                })

            except (RuntimeError, ConnectionError, TimeoutError) as exc:
                error_msg = f"菜品 {item.get('name', item.get('product_name', i))} 同步失败: {exc}"
                errors.append(error_msg)
                failed.append({
                    "dish_name": item.get("name") or item.get("product_name", ""),
                    "platform_item": item,
                    "status": "failed",
                    "error": str(exc),
                })
                log.warning(
                    "multi_platform_publish.item_failed",
                    store_id=store_id,
                    platform=platform,
                    error=str(exc),
                )

        status = "success"
        if failed and synced:
            status = "partial"
        elif failed and not synced:
            status = "failed"

        return {
            "name": platform,
            "status": status,
            "synced_count": len(synced),
            "failed_count": len(failed),
            "errors": errors,
            "items": synced + failed,
            "published_at": datetime.utcnow().isoformat(),
        }

    # ━━━ TODO: 真实平台API调用方法(预留) ━━━
    #
    # async def _call_meituan_api(self, store_id: str, item: dict) -> dict:
    #     """调用美团外卖API推送菜品。"""
    #     # 1. 获取门店的美团授权token
    #     # 2. 构建美团API请求
    #     # 3. 发送请求并处理响应
    #     # 4. 重试逻辑(最多 MAX_RETRY 次)
    #     raise NotImplementedError("美团API尚未接入")
    #
    # async def _call_eleme_api(self, store_id: str, item: dict) -> dict:
    #     """调用饿了么API推送菜品。"""
    #     raise NotImplementedError("饿了么API尚未接入")
    #
    # async def _call_douyin_api(self, store_id: str, item: dict) -> dict:
    #     """调用抖音团购API推送商品。"""
    #     raise NotImplementedError("抖音API尚未接入")
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
