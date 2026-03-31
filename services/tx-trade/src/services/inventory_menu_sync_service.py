"""
库存-菜单联动 Service

业务逻辑：
  当某食材库存低于预警阈值时，检查哪些菜品依赖此食材，
  自动或提示下架这些菜品。

对标：Lightspeed 和 Odoo 的库存-菜单联动。
"""
import math
import os
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

import httpx
import structlog
from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.soldout_record import SoldoutRecord

logger = structlog.get_logger()

MAC_STATION_URL = os.getenv("MAC_STATION_URL", "http://localhost:8000")
TX_MENU_URL = os.getenv("TX_MENU_SERVICE_URL", "http://tx-menu:8001")

# 低库存阈值：可出份数 <= 此值时标记 low_stock
LOW_STOCK_SERVINGS_THRESHOLD = 3
AUTO_SOLDOUT_SERVINGS_THRESHOLD = 0


@dataclass
class ImpactedDish:
    dish_id: str
    dish_name: str
    ingredient_id: str
    ingredient_name: str
    per_dish_usage: float       # 每份菜消耗食材量
    estimated_servings: int     # 估算可出品份数
    auto_soldout: bool          # 是否自动下架
    low_stock: bool             # 是否低库存预警


@dataclass
class InventoryAlert:
    ingredient_id: str
    ingredient_name: str
    current_stock: float
    threshold: float
    unit: str
    impacted_dishes: list[ImpactedDish] = field(default_factory=list)


# ─── 模拟数据：无真实DB schema时的合理Mock ───
# 实际使用时替换为对应的 tx-supply/tx-menu 数据库查询

MOCK_DISH_INGREDIENTS: list[dict] = [
    {
        "dish_id": "d1",
        "dish_name": "宫保鸡丁",
        "ingredient_id": "i1",
        "ingredient_name": "鸡胸肉",
        "per_dish_usage": 0.25,  # kg
        "alert_threshold": 2.0,
    },
    {
        "dish_id": "d3",
        "dish_name": "佛跳墙",
        "ingredient_id": "i2",
        "ingredient_name": "鲍鱼",
        "per_dish_usage": 0.15,
        "alert_threshold": 1.0,
    },
    {
        "dish_id": "d3",
        "dish_name": "佛跳墙",
        "ingredient_id": "i3",
        "ingredient_name": "鱼翅",
        "per_dish_usage": 0.10,
        "alert_threshold": 0.5,
    },
    {
        "dish_id": "d5",
        "dish_name": "小笼包",
        "ingredient_id": "i4",
        "ingredient_name": "猪肉馅",
        "per_dish_usage": 0.05,
        "alert_threshold": 0.5,
    },
]


async def _fetch_dish_ingredients_by_ingredient(
    ingredient_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """
    查询依赖指定食材的所有菜品及其用量配置。

    实际应查询 tx-supply 的 dish_bom / recipe 表。
    当前使用 Mock 数据直到 BOM 表 schema 确定。
    """
    return [
        row for row in MOCK_DISH_INGREDIENTS
        if row["ingredient_id"] == ingredient_id
    ]


async def _fetch_all_ingredient_stocks(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """
    查询门店所有食材的当前库存及预警阈值。

    实际应查询 tx-supply 的 ingredient_stocks 表。
    当前使用 Mock 数据。
    """
    return [
        {
            "ingredient_id": "i1",
            "ingredient_name": "鸡胸肉",
            "current_stock": 0.4,   # kg — 低库存
            "threshold": 2.0,
            "unit": "kg",
        },
        {
            "ingredient_id": "i2",
            "ingredient_name": "鲍鱼",
            "current_stock": 0.0,   # kg — 售完
            "threshold": 1.0,
            "unit": "kg",
        },
        {
            "ingredient_id": "i3",
            "ingredient_name": "鱼翅",
            "current_stock": 0.8,
            "threshold": 0.5,
            "unit": "kg",
        },
        {
            "ingredient_id": "i4",
            "ingredient_name": "猪肉馅",
            "current_stock": 2.5,
            "threshold": 0.5,
            "unit": "kg",
        },
    ]


# ─── 核心业务函数 ───

async def check_ingredient_impact(
    ingredient_id: str,
    current_stock: float,
    tenant_id: str,
    db: AsyncSession,
) -> list[ImpactedDish]:
    """
    查找依赖此食材的所有菜品，估算可出品份数。

    可出品份数 = floor(current_stock / per_dish_usage)
    如果可出品份数 == 0 → auto_soldout=True
    如果可出品份数 <= 3 → low_stock=True
    """
    rows = await _fetch_dish_ingredients_by_ingredient(ingredient_id, tenant_id, db)

    impacted: list[ImpactedDish] = []
    for row in rows:
        per_usage = row["per_dish_usage"]
        if per_usage <= 0:
            logger.warning(
                "inventory.impact.zero_usage",
                dish_id=row["dish_id"],
                ingredient_id=ingredient_id,
            )
            continue

        servings = math.floor(current_stock / per_usage)
        auto_soldout = servings == AUTO_SOLDOUT_SERVINGS_THRESHOLD
        low_stock = not auto_soldout and servings <= LOW_STOCK_SERVINGS_THRESHOLD

        impacted.append(
            ImpactedDish(
                dish_id=row["dish_id"],
                dish_name=row["dish_name"],
                ingredient_id=ingredient_id,
                ingredient_name=row["ingredient_name"],
                per_dish_usage=per_usage,
                estimated_servings=servings,
                auto_soldout=auto_soldout,
                low_stock=low_stock,
            )
        )

    logger.info(
        "inventory.impact.checked",
        ingredient_id=ingredient_id,
        current_stock=current_stock,
        impacted_count=len(impacted),
        auto_soldout_count=sum(1 for d in impacted if d.auto_soldout),
        low_stock_count=sum(1 for d in impacted if d.low_stock),
    )
    return impacted


async def auto_soldout_dishes(
    dish_ids: list[str],
    reason: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """
    批量将菜品标记为缺货下架（soldout）。

    操作流程：
      1. 写入 soldout_records（source="inventory"）
      2. 广播 menu_dish_updated 事件到 mac-station（失败不阻塞主流程）
      3. 同步到 tx-menu 更新菜品可售状态（失败不阻塞主流程）

    返回：{ succeeded: [...], failed: [...] }
    """
    if not dish_ids:
        return {"succeeded": [], "failed": []}

    now = datetime.now(timezone.utc)
    succeeded: list[str] = []
    failed: list[str] = []

    for dish_id in dish_ids:
        try:
            # 检查是否已在沽清状态，避免重复记录
            existing = await db.execute(
                select(SoldoutRecord).where(
                    SoldoutRecord.tenant_id == uuid.UUID(tenant_id),
                    SoldoutRecord.dish_id == uuid.UUID(dish_id),
                    SoldoutRecord.is_active.is_(True),
                )
            )
            if existing.scalar_one_or_none():
                logger.info(
                    "inventory.soldout.already_soldout",
                    dish_id=dish_id,
                    tenant_id=tenant_id,
                )
                succeeded.append(dish_id)
                continue

            # 插入 soldout_records
            record = SoldoutRecord(
                tenant_id=uuid.UUID(tenant_id),
                store_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),  # 实际从context获取
                dish_id=uuid.UUID(dish_id),
                dish_name=dish_id,  # 实际从BOM表获取
                soldout_at=now,
                reason=reason,
                source="inventory",
                is_active=True,
                sync_status={"pos": False, "miniapp": False, "kds": False},
            )
            db.add(record)
            await db.flush()
            succeeded.append(dish_id)

            logger.info(
                "inventory.soldout.marked",
                dish_id=dish_id,
                tenant_id=tenant_id,
                reason=reason,
                record_id=str(record.id),
            )
        except (ValueError, AttributeError, TypeError) as e:
            logger.error(
                "inventory.soldout.mark_failed",
                dish_id=dish_id,
                error=str(e),
                exc_info=True,
            )
            failed.append(dish_id)

    await db.commit()

    # 广播事件（失败不阻塞）
    await _broadcast_menu_updated(succeeded, "soldout", tenant_id)

    # 同步到 tx-menu（失败不阻塞）
    await _sync_dishes_to_menu_service(succeeded, "soldout", reason, tenant_id)

    logger.info(
        "inventory.soldout.batch_complete",
        total=len(dish_ids),
        succeeded=len(succeeded),
        failed=len(failed),
    )
    return {"succeeded": succeeded, "failed": failed}


async def check_and_auto_soldout(
    ingredient_id: str,
    current_stock: float,
    tenant_id: str,
    db: AsyncSession,
) -> list[ImpactedDish]:
    """
    完整流程：检查食材影响 → 自动下架零库存菜品。

    返回：已自动下架的菜品列表（用于通知前端）。
    """
    logger.info(
        "inventory.auto_soldout.start",
        ingredient_id=ingredient_id,
        current_stock=current_stock,
        tenant_id=tenant_id,
    )

    impacted = await check_ingredient_impact(ingredient_id, current_stock, tenant_id, db)

    auto_soldout_dishes_list = [d for d in impacted if d.auto_soldout]

    if auto_soldout_dishes_list:
        dish_ids = [d.dish_id for d in auto_soldout_dishes_list]
        reason = f"食材库存归零: ingredient_id={ingredient_id}, stock={current_stock}"

        logger.warning(
            "inventory.auto_soldout.triggered",
            ingredient_id=ingredient_id,
            dish_ids=dish_ids,
            reason=reason,
        )

        await auto_soldout_dishes(
            dish_ids=dish_ids,
            reason=reason,
            tenant_id=tenant_id,
            db=db,
        )

    return auto_soldout_dishes_list


async def restore_dishes_by_ingredient(
    ingredient_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[str]:
    """
    食材补货后恢复相关菜品上架。

    仅恢复因此食材缺货（source="inventory"）而下架的菜品，
    其他原因（KDS手动下架等）下架的菜品不受影响。
    返回：已恢复的菜品 dish_id 列表。
    """
    now = datetime.now(timezone.utc)

    rows = await _fetch_dish_ingredients_by_ingredient(ingredient_id, tenant_id, db)
    candidate_dish_ids = [uuid.UUID(row["dish_id"]) for row in rows]

    if not candidate_dish_ids:
        logger.info(
            "inventory.restore.no_candidates",
            ingredient_id=ingredient_id,
        )
        return []

    # 查找因库存原因下架的记录
    result = await db.execute(
        select(SoldoutRecord).where(
            SoldoutRecord.tenant_id == uuid.UUID(tenant_id),
            SoldoutRecord.dish_id.in_(candidate_dish_ids),
            SoldoutRecord.source == "inventory",
            SoldoutRecord.is_active.is_(True),
        )
    )
    records = result.scalars().all()

    if not records:
        logger.info(
            "inventory.restore.nothing_to_restore",
            ingredient_id=ingredient_id,
            tenant_id=tenant_id,
        )
        return []

    restored_dish_ids: list[str] = []
    for record in records:
        await db.execute(
            update(SoldoutRecord)
            .where(SoldoutRecord.id == record.id)
            .values(is_active=False, restore_at=now, updated_at=now)
        )
        restored_dish_ids.append(str(record.dish_id))

    await db.commit()

    # 广播恢复事件（失败不阻塞）
    await _broadcast_menu_updated(restored_dish_ids, "restore", tenant_id)
    await _sync_dishes_to_menu_service(restored_dish_ids, "restore", "食材补货恢复", tenant_id)

    logger.info(
        "inventory.restore.complete",
        ingredient_id=ingredient_id,
        restored_count=len(restored_dish_ids),
        dish_ids=restored_dish_ids,
    )
    return restored_dish_ids


async def get_soldout_watch(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """
    返回当前低库存预警菜品列表（包含已自动下架和低库存警告）。
    """
    stocks = await _fetch_all_ingredient_stocks(store_id, tenant_id, db)

    watch_list: list[dict] = []
    seen_dishes: set[str] = set()

    for stock_info in stocks:
        ingredient_id = stock_info["ingredient_id"]
        current_stock = stock_info["current_stock"]

        if current_stock > stock_info["threshold"]:
            continue  # 库存正常，跳过

        impacted = await check_ingredient_impact(ingredient_id, current_stock, tenant_id, db)

        for dish in impacted:
            if dish.dish_id in seen_dishes:
                continue
            if not (dish.auto_soldout or dish.low_stock):
                continue

            seen_dishes.add(dish.dish_id)
            watch_list.append({
                "dish_id": dish.dish_id,
                "dish_name": dish.dish_name,
                "ingredient_name": dish.ingredient_name,
                "ingredient_id": dish.ingredient_id,
                "estimated_servings": dish.estimated_servings,
                "is_auto_soldout": dish.auto_soldout,
                "is_low_stock": dish.low_stock,
                "current_stock": current_stock,
                "unit": stock_info["unit"],
            })

    # 按紧急程度排序：已下架 > 低库存，可出份数从少到多
    watch_list.sort(key=lambda x: (not x["is_auto_soldout"], x["estimated_servings"]))
    return watch_list


async def get_inventory_dashboard(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """
    返回库存健康状态汇总。
    """
    stocks = await _fetch_all_ingredient_stocks(store_id, tenant_id, db)

    low_stock_ingredients: list[dict] = []
    total_auto_soldout_dishes: set[str] = set()
    alerts: list[dict] = []

    for stock_info in stocks:
        ingredient_id = stock_info["ingredient_id"]
        current_stock = stock_info["current_stock"]

        if current_stock <= stock_info["threshold"]:
            low_stock_ingredients.append(stock_info)

            impacted = await check_ingredient_impact(ingredient_id, current_stock, tenant_id, db)
            auto_soldout = [d for d in impacted if d.auto_soldout]
            for d in auto_soldout:
                total_auto_soldout_dishes.add(d.dish_id)

            impacted_count = len(impacted)
            if impacted_count > 0:
                alerts.append({
                    "ingredient_id": ingredient_id,
                    "ingredient_name": stock_info["ingredient_name"],
                    "current_stock": current_stock,
                    "threshold": stock_info["threshold"],
                    "unit": stock_info["unit"],
                    "impacted_dishes_count": impacted_count,
                    "auto_soldout_count": len(auto_soldout),
                })

    # 按影响菜品数降序
    alerts.sort(key=lambda x: x["impacted_dishes_count"], reverse=True)

    return {
        "total_ingredients": len(stocks),
        "low_stock_count": len(low_stock_ingredients),
        "soldout_dishes_count": len(total_auto_soldout_dishes),
        "alerts": alerts,
    }


# ─── 内部广播 / 同步函数（失败不阻塞主流程）───

async def _broadcast_menu_updated(
    dish_ids: list[str],
    action: str,
    tenant_id: str,
) -> bool:
    """广播 menu_dish_updated 事件到 mac-station WebSocket。"""
    if not dish_ids:
        return True
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.post(
                f"{MAC_STATION_URL}/api/kds/broadcast",
                json={
                    "event": "menu_dish_updated",
                    "data": {
                        "dish_ids": dish_ids,
                        "action": action,
                        "source": "inventory",
                    },
                },
                headers={"X-Tenant-ID": tenant_id},
            )
            success = resp.status_code == 200
            if not success:
                logger.warning(
                    "inventory.broadcast.non_200",
                    status_code=resp.status_code,
                    action=action,
                )
            return success
    except httpx.RequestError as e:
        logger.warning(
            "inventory.broadcast.failed",
            error=str(e),
            action=action,
            dish_count=len(dish_ids),
        )
        return False


async def _sync_dishes_to_menu_service(
    dish_ids: list[str],
    action: str,
    reason: str,
    tenant_id: str,
) -> bool:
    """同步菜品可售状态到 tx-menu 服务。"""
    if not dish_ids:
        return True
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"{TX_MENU_URL}/api/v1/menu/dishes/bulk-availability",
                json={
                    "dish_ids": dish_ids,
                    "is_available": action == "restore",
                    "reason": reason,
                    "source": "inventory",
                },
                headers={"X-Tenant-ID": tenant_id},
            )
            success = resp.status_code == 200
            if not success:
                logger.warning(
                    "inventory.menu_sync.non_200",
                    status_code=resp.status_code,
                    action=action,
                )
            return success
    except httpx.RequestError as e:
        logger.warning(
            "inventory.menu_sync.failed",
            error=str(e),
            action=action,
            dish_count=len(dish_ids),
        )
        return False
