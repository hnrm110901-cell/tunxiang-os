"""外卖统一管理中心 — 美团 + 饿了么多平台聚合

统一管理外卖订单拉取、接单/拒单、沽清同步、配送追踪、对账和菜品上下架。
支持自动接单规则配置（全自动 / 仅白天 / 关闭）。

所有金额单位：分（fen）。
"""

import uuid
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
from typing import Any

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# 平台常量
# ---------------------------------------------------------------------------

SUPPORTED_PLATFORMS = ("meituan", "eleme")

# 美团 / 饿了么订单状态 → 内部统一状态
_MEITUAN_STATUS_MAP = {
    1: "pending",
    2: "confirmed",
    3: "preparing",
    4: "delivering",
    5: "completed",
    6: "cancelled",
    8: "refunded",
}

_ELEME_STATUS_MAP = {
    0: "pending",
    1: "pending",
    2: "confirmed",
    3: "delivering",
    4: "completed",
    5: "cancelled",
    9: "refunded",
}

# 自动接单模式
AUTO_ACCEPT_MODE_ALL = "all"  # 全自动
AUTO_ACCEPT_MODE_DAYTIME = "daytime"  # 仅白天
AUTO_ACCEPT_MODE_OFF = "off"  # 关闭

_DEFAULT_DAYTIME_START = dtime(9, 0)
_DEFAULT_DAYTIME_END = dtime(22, 0)


def _gen_id() -> str:
    return str(uuid.uuid4())


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Mock 平台客户端 — 接口与真实 SDK 兼容，生产切换只需替换实现
# ---------------------------------------------------------------------------


class _MockMeituanClient:
    """Mock 美团外卖 API（接口与 MeituanSaasAdapter 兼容）"""

    async def pull_new_orders(self, poi_id: str) -> list[dict]:
        """拉取待处理订单列表"""
        logger.info("mock_meituan_pull_orders", poi_id=poi_id)
        return []

    async def confirm_order(self, order_id: str) -> dict:
        return {"code": "ok", "order_id": order_id}

    async def cancel_order(self, order_id: str, reason_code: int, reason: str) -> dict:
        return {"code": "ok", "order_id": order_id}

    async def sold_out_food(self, poi_id: str, food_id: str) -> dict:
        return {"code": "ok", "food_id": food_id}

    async def on_sale_food(self, poi_id: str, food_id: str) -> dict:
        return {"code": "ok", "food_id": food_id}

    async def query_logistics(self, order_id: str) -> dict:
        return {"status": "delivering", "rider_name": "", "rider_phone": ""}

    async def get_bill(self, poi_id: str, date_str: str) -> dict:
        return {"total_fen": 0, "commission_fen": 0, "orders": []}


class _MockElemeClient:
    """Mock 饿了么 API（接口与 ElemeAdapter 兼容）"""

    async def pull_new_orders(self, shop_id: str) -> list[dict]:
        logger.info("mock_eleme_pull_orders", shop_id=shop_id)
        return []

    async def confirm_order(self, order_id: str) -> dict:
        return {"code": "ok", "order_id": order_id}

    async def cancel_order(self, order_id: str, reason_code: int, reason: str) -> dict:
        return {"code": "ok", "order_id": order_id}

    async def sold_out_food(self, shop_id: str, food_id: str) -> dict:
        return {"code": "ok", "food_id": food_id}

    async def on_sale_food(self, shop_id: str, food_id: str) -> dict:
        return {"code": "ok", "food_id": food_id}

    async def query_delivery_status(self, order_id: str) -> dict:
        return {"status": "delivering", "rider_name": "", "rider_phone": ""}

    async def get_bill(self, shop_id: str, date_str: str) -> dict:
        return {"total_fen": 0, "commission_fen": 0, "orders": []}


# 全局 mock 实例（生产环境替换为真实客户端注入）
_meituan_client = _MockMeituanClient()
_eleme_client = _MockElemeClient()


def set_platform_clients(
    meituan: Any = None,
    eleme: Any = None,
) -> None:
    """注入真实平台客户端（生产环境调用）"""
    global _meituan_client, _eleme_client
    if meituan is not None:
        _meituan_client = meituan
    if eleme is not None:
        _eleme_client = eleme


# ---------------------------------------------------------------------------
# 内部存储 — 生产环境替换为 PostgreSQL（DeliveryOrder 表）
# ---------------------------------------------------------------------------

# 以 tenant_id -> store_id -> order_id 为键的内存存储
_orders_store: dict[str, dict[str, dict]] = {}
# 自动接单规则：tenant_id -> store_id -> rules dict
_auto_accept_rules: dict[str, dict[str, dict]] = {}


def _get_orders(tenant_id: str, store_id: str) -> dict[str, dict]:
    """获取门店订单字典"""
    return _orders_store.setdefault(tenant_id, {}).setdefault(store_id, {})


def _save_order(tenant_id: str, store_id: str, order: dict) -> None:
    orders = _get_orders(tenant_id, store_id)
    orders[order["order_id"]] = order


# ---------------------------------------------------------------------------
# 核心业务函数
# ---------------------------------------------------------------------------


async def sync_meituan_orders(
    store_id: str,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """拉取美团新订单并转换为内部格式

    Returns:
        {synced_count, orders: [...]}
    """
    logger.info("sync_meituan_orders", store_id=store_id, tenant_id=tenant_id)

    raw_orders = await _meituan_client.pull_new_orders(poi_id=store_id)

    synced: list[dict] = []
    for raw in raw_orders:
        status_code = int(raw.get("status", 1))
        order = {
            "order_id": _gen_id(),
            "platform": "meituan",
            "platform_order_id": str(raw.get("order_id", "")),
            "store_id": store_id,
            "status": _MEITUAN_STATUS_MAP.get(status_code, "pending"),
            "items": raw.get("detail", []),
            "total_fen": int(raw.get("order_total_price", 0)),
            "customer_phone": str(raw.get("recipient_phone", "")),
            "delivery_address": str(raw.get("recipient_address", "")),
            "expected_time": str(raw.get("delivery_time", "")),
            "notes": str(raw.get("caution", "")),
            "created_at": _now_utc().isoformat(),
        }
        _save_order(tenant_id, store_id, order)

        # 检查是否需要自动接单
        auto_result = await _try_auto_accept(store_id, tenant_id, order)
        if auto_result:
            order["status"] = "confirmed"
            order["auto_accepted"] = True

        synced.append(order)

    logger.info(
        "meituan_orders_synced",
        store_id=store_id,
        tenant_id=tenant_id,
        synced_count=len(synced),
    )
    return {"synced_count": len(synced), "orders": synced}


async def sync_eleme_orders(
    store_id: str,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """拉取饿了么新订单并转换为内部格式

    Returns:
        {synced_count, orders: [...]}
    """
    logger.info("sync_eleme_orders", store_id=store_id, tenant_id=tenant_id)

    raw_orders = await _eleme_client.pull_new_orders(shop_id=store_id)

    synced: list[dict] = []
    for raw in raw_orders:
        status_code = int(raw.get("status", 1))
        order = {
            "order_id": _gen_id(),
            "platform": "eleme",
            "platform_order_id": str(raw.get("order_id", "")),
            "store_id": store_id,
            "status": _ELEME_STATUS_MAP.get(status_code, "pending"),
            "items": raw.get("food_list", []),
            "total_fen": int(raw.get("order_amount", 0)),
            "customer_phone": str(raw.get("phone", "")),
            "delivery_address": str(raw.get("address", "")),
            "expected_time": str(raw.get("expected_delivery_time", "")),
            "notes": str(raw.get("remark", "")),
            "created_at": _now_utc().isoformat(),
        }
        _save_order(tenant_id, store_id, order)

        auto_result = await _try_auto_accept(store_id, tenant_id, order)
        if auto_result:
            order["status"] = "confirmed"
            order["auto_accepted"] = True

        synced.append(order)

    logger.info(
        "eleme_orders_synced",
        store_id=store_id,
        tenant_id=tenant_id,
        synced_count=len(synced),
    )
    return {"synced_count": len(synced), "orders": synced}


async def accept_order(
    platform: str,
    order_id: str,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """接单（自动/手动）

    Args:
        platform: meituan / eleme
        order_id: 平台订单ID
        tenant_id: 租户ID

    Returns:
        {order_id, platform, status, accepted_at}
    """
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(f"不支持的平台: {platform}")

    logger.info("accept_order", platform=platform, order_id=order_id, tenant_id=tenant_id)

    if platform == "meituan":
        result = await _meituan_client.confirm_order(order_id)
    else:
        result = await _eleme_client.confirm_order(order_id)

    accepted_at = _now_utc().isoformat()

    # 更新本地状态
    _update_order_status_local(tenant_id, order_id, "confirmed")

    logger.info(
        "order_accepted",
        platform=platform,
        order_id=order_id,
        tenant_id=tenant_id,
    )

    return {
        "order_id": order_id,
        "platform": platform,
        "status": "confirmed",
        "accepted_at": accepted_at,
        "platform_result": result,
    }


async def reject_order(
    platform: str,
    order_id: str,
    reason: str,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """拒单

    Args:
        platform: meituan / eleme
        order_id: 平台订单ID
        reason: 拒单原因
        tenant_id: 租户ID

    Returns:
        {order_id, platform, status, reason, rejected_at}
    """
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(f"不支持的平台: {platform}")

    logger.info(
        "reject_order",
        platform=platform,
        order_id=order_id,
        reason=reason,
        tenant_id=tenant_id,
    )

    # 使用通用拒单原因码
    reason_code = 1  # 门店原因

    if platform == "meituan":
        result = await _meituan_client.cancel_order(order_id, reason_code, reason)
    else:
        result = await _eleme_client.cancel_order(order_id, reason_code, reason)

    _update_order_status_local(tenant_id, order_id, "cancelled")

    rejected_at = _now_utc().isoformat()

    logger.info(
        "order_rejected",
        platform=platform,
        order_id=order_id,
        reason=reason,
        tenant_id=tenant_id,
    )

    return {
        "order_id": order_id,
        "platform": platform,
        "status": "cancelled",
        "reason": reason,
        "rejected_at": rejected_at,
        "platform_result": result,
    }


async def sync_stockout_to_platforms(
    store_id: str,
    sold_out_ids: list[str],
    tenant_id: str,
    db: Any = None,
) -> dict:
    """沽清同步到外卖平台 — 门店沽清自动同步到美团+饿了么

    Args:
        store_id: 门店ID
        sold_out_ids: 沽清菜品ID列表
        tenant_id: 租户ID

    Returns:
        {synced_count, results: [{platform, food_id, status}]}
    """
    logger.info(
        "sync_stockout_to_platforms",
        store_id=store_id,
        sold_out_count=len(sold_out_ids),
        tenant_id=tenant_id,
    )

    results: list[dict] = []

    for food_id in sold_out_ids:
        # 同步到美团
        try:
            await _meituan_client.sold_out_food(poi_id=store_id, food_id=food_id)
            results.append(
                {
                    "platform": "meituan",
                    "food_id": food_id,
                    "status": "synced",
                }
            )
        except (ConnectionError, TimeoutError, ValueError) as e:
            logger.error(
                "meituan_stockout_failed",
                food_id=food_id,
                error=str(e),
                tenant_id=tenant_id,
            )
            results.append(
                {
                    "platform": "meituan",
                    "food_id": food_id,
                    "status": "failed",
                    "error": str(e),
                }
            )

        # 同步到饿了么
        try:
            await _eleme_client.sold_out_food(shop_id=store_id, food_id=food_id)
            results.append(
                {
                    "platform": "eleme",
                    "food_id": food_id,
                    "status": "synced",
                }
            )
        except (ConnectionError, TimeoutError, ValueError) as e:
            logger.error(
                "eleme_stockout_failed",
                food_id=food_id,
                error=str(e),
                tenant_id=tenant_id,
            )
            results.append(
                {
                    "platform": "eleme",
                    "food_id": food_id,
                    "status": "failed",
                    "error": str(e),
                }
            )

    synced_count = sum(1 for r in results if r["status"] == "synced")

    logger.info(
        "stockout_sync_completed",
        store_id=store_id,
        total=len(results),
        synced=synced_count,
        tenant_id=tenant_id,
    )

    return {
        "store_id": store_id,
        "synced_count": synced_count,
        "total_count": len(results),
        "results": results,
    }


async def update_delivery_status(
    order_id: str,
    status: str,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """配送状态更新

    Args:
        order_id: 内部订单ID
        status: 新状态 (preparing / delivering / completed / cancelled)
        tenant_id: 租户ID

    Returns:
        {order_id, status, updated_at}
    """
    valid_statuses = ("pending", "confirmed", "preparing", "delivering", "completed", "cancelled")
    if status not in valid_statuses:
        raise ValueError(f"无效状态: {status}，可选: {valid_statuses}")

    logger.info(
        "update_delivery_status",
        order_id=order_id,
        status=status,
        tenant_id=tenant_id,
    )

    _update_order_status_local(tenant_id, order_id, status)

    updated_at = _now_utc().isoformat()

    return {
        "order_id": order_id,
        "status": status,
        "updated_at": updated_at,
    }


async def get_takeaway_dashboard(
    store_id: str,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """外卖仪表盘 — 待接/制作中/配送中/已完成

    Returns:
        {store_id, pending, preparing, delivering, completed, total, orders_by_platform}
    """
    logger.info(
        "get_takeaway_dashboard",
        store_id=store_id,
        tenant_id=tenant_id,
    )

    orders = _get_orders(tenant_id, store_id)

    pending = []
    preparing = []
    delivering = []
    completed = []

    for order in orders.values():
        s = order.get("status", "pending")
        if s == "pending":
            pending.append(order)
        elif s in ("confirmed", "preparing"):
            preparing.append(order)
        elif s == "delivering":
            delivering.append(order)
        elif s == "completed":
            completed.append(order)

    # 按平台分组统计
    platform_stats: dict[str, int] = {}
    for order in orders.values():
        p = order.get("platform", "unknown")
        platform_stats[p] = platform_stats.get(p, 0) + 1

    return {
        "store_id": store_id,
        "pending_count": len(pending),
        "preparing_count": len(preparing),
        "delivering_count": len(delivering),
        "completed_count": len(completed),
        "total": len(orders),
        "orders_by_platform": platform_stats,
        "pending": pending,
        "preparing": preparing,
        "delivering": delivering,
        "completed": completed,
    }


async def get_platform_reconciliation(
    store_id: str,
    platform: str,
    date: str,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """平台对账 — 对比平台账单与内部订单

    Args:
        store_id: 门店ID
        platform: meituan / eleme
        date: 日期 YYYY-MM-DD
        tenant_id: 租户ID

    Returns:
        {platform, date, platform_total_fen, internal_total_fen, diff_fen, orders}
    """
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(f"不支持的平台: {platform}")

    logger.info(
        "get_platform_reconciliation",
        store_id=store_id,
        platform=platform,
        date=date,
        tenant_id=tenant_id,
    )

    # 从平台拉取账单
    if platform == "meituan":
        platform_bill = await _meituan_client.get_bill(poi_id=store_id, date_str=date)
    else:
        platform_bill = await _eleme_client.get_bill(shop_id=store_id, date_str=date)

    platform_total_fen = int(platform_bill.get("total_fen", 0))
    platform_commission_fen = int(platform_bill.get("commission_fen", 0))

    # 从内部订单计算
    orders = _get_orders(tenant_id, store_id)
    internal_total_fen = 0
    matched_orders: list[dict] = []
    for order in orders.values():
        if order.get("platform") == platform and order.get("status") == "completed":
            order_date = order.get("created_at", "")[:10]
            if order_date == date:
                internal_total_fen += order.get("total_fen", 0)
                matched_orders.append(
                    {
                        "order_id": order["order_id"],
                        "platform_order_id": order.get("platform_order_id", ""),
                        "total_fen": order.get("total_fen", 0),
                    }
                )

    diff_fen = platform_total_fen - internal_total_fen

    return {
        "store_id": store_id,
        "platform": platform,
        "date": date,
        "platform_total_fen": platform_total_fen,
        "platform_commission_fen": platform_commission_fen,
        "internal_total_fen": internal_total_fen,
        "diff_fen": diff_fen,
        "is_matched": diff_fen == 0,
        "order_count": len(matched_orders),
        "orders": matched_orders,
    }


async def manage_online_menu(
    store_id: str,
    platform: str,
    actions: list[dict],
    tenant_id: str,
    db: Any = None,
) -> dict:
    """外卖菜品上下架

    Args:
        store_id: 门店ID
        platform: meituan / eleme
        actions: [{food_id, action: "on_sale" | "sold_out"}]
        tenant_id: 租户ID

    Returns:
        {platform, results: [{food_id, action, status}]}
    """
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(f"不支持的平台: {platform}")

    logger.info(
        "manage_online_menu",
        store_id=store_id,
        platform=platform,
        action_count=len(actions),
        tenant_id=tenant_id,
    )

    results: list[dict] = []

    for action_item in actions:
        food_id = action_item.get("food_id", "")
        action = action_item.get("action", "")

        if action not in ("on_sale", "sold_out"):
            results.append(
                {
                    "food_id": food_id,
                    "action": action,
                    "status": "failed",
                    "error": f"无效操作: {action}",
                }
            )
            continue

        try:
            if platform == "meituan":
                if action == "on_sale":
                    await _meituan_client.on_sale_food(poi_id=store_id, food_id=food_id)
                else:
                    await _meituan_client.sold_out_food(poi_id=store_id, food_id=food_id)
            else:
                if action == "on_sale":
                    await _eleme_client.on_sale_food(shop_id=store_id, food_id=food_id)
                else:
                    await _eleme_client.sold_out_food(shop_id=store_id, food_id=food_id)

            results.append(
                {
                    "food_id": food_id,
                    "action": action,
                    "status": "success",
                }
            )
        except (ConnectionError, TimeoutError, ValueError) as e:
            logger.error(
                "menu_action_failed",
                food_id=food_id,
                action=action,
                error=str(e),
                tenant_id=tenant_id,
            )
            results.append(
                {
                    "food_id": food_id,
                    "action": action,
                    "status": "failed",
                    "error": str(e),
                }
            )

    success_count = sum(1 for r in results if r["status"] == "success")

    return {
        "store_id": store_id,
        "platform": platform,
        "success_count": success_count,
        "total_count": len(results),
        "results": results,
    }


async def set_auto_accept_rules(
    store_id: str,
    rules: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """设置自动接单规则

    Args:
        store_id: 门店ID
        rules: {
            mode: "all" | "daytime" | "off",
            daytime_start: "09:00",  # 仅 daytime 模式
            daytime_end: "22:00",    # 仅 daytime 模式
            max_order_amount_fen: 100000,  # 超过此金额不自动接单（可选）
            platforms: ["meituan", "eleme"],  # 适用平台（可选，默认全部）
        }
        tenant_id: 租户ID

    Returns:
        {store_id, rules, updated_at}
    """
    mode = rules.get("mode", AUTO_ACCEPT_MODE_OFF)
    if mode not in (AUTO_ACCEPT_MODE_ALL, AUTO_ACCEPT_MODE_DAYTIME, AUTO_ACCEPT_MODE_OFF):
        raise ValueError(f"无效的自动接单模式: {mode}")

    logger.info(
        "set_auto_accept_rules",
        store_id=store_id,
        mode=mode,
        tenant_id=tenant_id,
    )

    # 存储规则
    tenant_rules = _auto_accept_rules.setdefault(tenant_id, {})
    tenant_rules[store_id] = {
        "mode": mode,
        "daytime_start": rules.get("daytime_start", "09:00"),
        "daytime_end": rules.get("daytime_end", "22:00"),
        "max_order_amount_fen": rules.get("max_order_amount_fen"),
        "platforms": rules.get("platforms", list(SUPPORTED_PLATFORMS)),
        "updated_at": _now_utc().isoformat(),
    }

    return {
        "store_id": store_id,
        "rules": tenant_rules[store_id],
        "updated_at": tenant_rules[store_id]["updated_at"],
    }


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _update_order_status_local(tenant_id: str, order_id: str, status: str) -> None:
    """更新内存中的订单状态"""
    for store_orders in _orders_store.get(tenant_id, {}).values():
        if order_id in store_orders:
            store_orders[order_id]["status"] = status
            return
    # 也可能是按 platform_order_id 查找
    for store_orders in _orders_store.get(tenant_id, {}).values():
        for oid, order in store_orders.items():
            if order.get("platform_order_id") == order_id:
                order["status"] = status
                return


async def _try_auto_accept(
    store_id: str,
    tenant_id: str,
    order: dict,
) -> bool:
    """根据自动接单规则决定是否自动接单

    Returns:
        True 表示已自动接单
    """
    rules = _auto_accept_rules.get(tenant_id, {}).get(store_id)
    if not rules:
        return False

    mode = rules.get("mode", AUTO_ACCEPT_MODE_OFF)

    if mode == AUTO_ACCEPT_MODE_OFF:
        return False

    # 检查平台是否在自动接单范围内
    allowed_platforms = rules.get("platforms", list(SUPPORTED_PLATFORMS))
    if order.get("platform") not in allowed_platforms:
        return False

    # 检查金额上限
    max_amount = rules.get("max_order_amount_fen")
    if max_amount and order.get("total_fen", 0) > max_amount:
        logger.info(
            "auto_accept_skip_amount",
            order_id=order["order_id"],
            total_fen=order.get("total_fen"),
            max_amount=max_amount,
            tenant_id=tenant_id,
        )
        return False

    if mode == AUTO_ACCEPT_MODE_DAYTIME:
        now = _now_utc()
        start_str = rules.get("daytime_start", "09:00")
        end_str = rules.get("daytime_end", "22:00")
        try:
            start_time = dtime.fromisoformat(start_str)
            end_time = dtime.fromisoformat(end_str)
        except (ValueError, TypeError):
            start_time = _DEFAULT_DAYTIME_START
            end_time = _DEFAULT_DAYTIME_END

        # 使用 UTC+8 判断白天（中国时区）
        china_time = now + timedelta(hours=8)
        current_time = china_time.time()
        if not (start_time <= current_time <= end_time):
            logger.info(
                "auto_accept_skip_outside_daytime",
                order_id=order["order_id"],
                current_time=current_time.isoformat(),
                tenant_id=tenant_id,
            )
            return False

    # 执行自动接单
    platform = order.get("platform", "")
    platform_order_id = order.get("platform_order_id", "")

    try:
        await accept_order(
            platform=platform,
            order_id=platform_order_id,
            tenant_id=tenant_id,
        )
        logger.info(
            "order_auto_accepted",
            order_id=order["order_id"],
            platform=platform,
            mode=mode,
            tenant_id=tenant_id,
        )
        return True
    except (ConnectionError, TimeoutError, ValueError) as e:
        logger.error(
            "auto_accept_failed",
            order_id=order["order_id"],
            error=str(e),
            tenant_id=tenant_id,
        )
        return False
