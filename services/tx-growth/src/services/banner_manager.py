"""营销Banner管理 — 创建/上下线/点击追踪/效果分析

支持位置: home_top(首页顶部) / member_center(会员中心) / menu_top(菜单顶部)
支持链接: activity(活动页) / product(商品) / coupon_pack(券包) / url(外部URL)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

# ── 内存存储 ──────────────────────────────────────────────────

_banners: dict[str, dict] = {}
_banner_clicks: dict[str, list[dict]] = {}  # banner_id -> [click_record]
_banner_impressions: dict[str, int] = {}  # banner_id -> impression_count

VALID_POSITIONS = ("home_top", "member_center", "menu_top")
VALID_LINK_TYPES = ("activity", "product", "coupon_pack", "url")


# ── 工具函数 ──────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_banner_active(banner: dict, now: datetime) -> bool:
    """判断Banner在当前时间是否有效"""
    if banner.get("is_deleted", False):
        return False
    if banner.get("status") != "active":
        return False
    start = banner.get("start_date")
    end = banner.get("end_date")
    if start and now < start:
        return False
    if end and now > end:
        return False
    return True


# ── 服务函数 ──────────────────────────────────────────────────


async def create_banner(
    title: str,
    image_url: str,
    link_type: str,
    link_target: str,
    position: str,
    priority: int,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    tenant_id: str,
    db: Any = None,
) -> dict[str, Any]:
    """创建Banner

    Args:
        title: Banner标题
        image_url: 图片URL
        link_type: 链接类型 (activity/product/coupon_pack/url)
        link_target: 链接目标 (活动ID/商品ID/券包ID/URL)
        position: 展示位置 (home_top/member_center/menu_top)
        priority: 优先级 (数值越大越靠前)
        start_date: 上线时间 (None=立即生效)
        end_date: 下线时间 (None=永久有效)
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"banner_id", "title", "position", "status", "created_at"}
    """
    if position not in VALID_POSITIONS:
        raise ValueError(f"invalid_position:{position}, must be one of {VALID_POSITIONS}")
    if link_type not in VALID_LINK_TYPES:
        raise ValueError(f"invalid_link_type:{link_type}, must be one of {VALID_LINK_TYPES}")

    banner_id = str(uuid.uuid4())
    now = _now_utc()

    banner = {
        "banner_id": banner_id,
        "tenant_id": tenant_id,
        "title": title,
        "image_url": image_url,
        "link_type": link_type,
        "link_target": link_target,
        "position": position,
        "priority": priority,
        "start_date": start_date,
        "end_date": end_date,
        "status": "active",
        "is_deleted": False,
        "created_at": now,
        "updated_at": now,
    }
    _banners[banner_id] = banner
    _banner_clicks[banner_id] = []
    _banner_impressions[banner_id] = 0

    logger.info(
        "banner.created",
        banner_id=banner_id,
        title=title,
        position=position,
        tenant_id=tenant_id,
    )

    return {
        "banner_id": banner_id,
        "title": title,
        "image_url": image_url,
        "link_type": link_type,
        "link_target": link_target,
        "position": position,
        "priority": priority,
        "status": "active",
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "created_at": now.isoformat(),
    }


async def list_active_banners(
    position: str,
    store_id: Optional[str],
    tenant_id: str,
    db: Any = None,
) -> list[dict[str, Any]]:
    """获取当前有效Banner列表（按优先级排序+时间过滤）

    Args:
        position: 展示位置
        store_id: 门店ID (可选, 用于门店级别过滤)
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        有效Banner列表, 按priority降序
    """
    if position not in VALID_POSITIONS:
        raise ValueError(f"invalid_position:{position}")

    now = _now_utc()
    active = []

    for banner in _banners.values():
        if banner["tenant_id"] != tenant_id:
            continue
        if banner["position"] != position:
            continue
        if not _is_banner_active(banner, now):
            continue
        # 门店级过滤
        target_stores = banner.get("target_stores")
        if target_stores and store_id and store_id not in target_stores:
            continue

        # 记录展示次数
        _banner_impressions[banner["banner_id"]] = (
            _banner_impressions.get(banner["banner_id"], 0) + 1
        )

        active.append({
            "banner_id": banner["banner_id"],
            "title": banner["title"],
            "image_url": banner["image_url"],
            "link_type": banner["link_type"],
            "link_target": banner["link_target"],
            "priority": banner["priority"],
        })

    active.sort(key=lambda b: b["priority"], reverse=True)

    logger.info(
        "banner.list_active",
        position=position,
        store_id=store_id,
        count=len(active),
        tenant_id=tenant_id,
    )

    return active


async def track_banner_click(
    banner_id: str,
    customer_id: str,
    tenant_id: str,
    db: Any = None,
) -> dict[str, Any]:
    """点击追踪

    Args:
        banner_id: Banner ID
        customer_id: 客户ID
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"banner_id", "customer_id", "clicked_at", "link_type", "link_target"}
    """
    banner = _banners.get(banner_id)
    if not banner:
        raise ValueError(f"banner_not_found:{banner_id}")
    if banner["tenant_id"] != tenant_id:
        raise ValueError("tenant_mismatch")

    now = _now_utc()
    click_record = {
        "banner_id": banner_id,
        "customer_id": customer_id,
        "clicked_at": now.isoformat(),
    }
    _banner_clicks.setdefault(banner_id, []).append(click_record)

    logger.info(
        "banner.clicked",
        banner_id=banner_id,
        customer_id=customer_id,
        tenant_id=tenant_id,
    )

    return {
        "banner_id": banner_id,
        "customer_id": customer_id,
        "clicked_at": now.isoformat(),
        "link_type": banner["link_type"],
        "link_target": banner["link_target"],
    }


async def get_banner_analytics(
    banner_id: str,
    tenant_id: str,
    db: Any = None,
) -> dict[str, Any]:
    """Banner效果分析（展示次数/点击率/转化）

    Args:
        banner_id: Banner ID
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"banner_id", "title", "impressions", "clicks", "ctr",
         "unique_clickers", "click_details"}
    """
    banner = _banners.get(banner_id)
    if not banner:
        raise ValueError(f"banner_not_found:{banner_id}")
    if banner["tenant_id"] != tenant_id:
        raise ValueError("tenant_mismatch")

    impressions = _banner_impressions.get(banner_id, 0)
    clicks = _banner_clicks.get(banner_id, [])
    click_count = len(clicks)
    unique_clickers = len(set(c["customer_id"] for c in clicks))
    ctr = round(click_count / max(impressions, 1), 4)

    logger.info(
        "banner.analytics",
        banner_id=banner_id,
        impressions=impressions,
        clicks=click_count,
        ctr=ctr,
        tenant_id=tenant_id,
    )

    return {
        "banner_id": banner_id,
        "title": banner["title"],
        "position": banner["position"],
        "impressions": impressions,
        "clicks": click_count,
        "ctr": ctr,
        "unique_clickers": unique_clickers,
        "status": banner["status"],
        "start_date": banner["start_date"].isoformat() if banner["start_date"] else None,
        "end_date": banner["end_date"].isoformat() if banner["end_date"] else None,
    }


# ── 管理函数 ──────────────────────────────────────────────────


async def disable_banner(
    banner_id: str,
    tenant_id: str,
    db: Any = None,
) -> dict[str, Any]:
    """下线Banner"""
    banner = _banners.get(banner_id)
    if not banner:
        raise ValueError(f"banner_not_found:{banner_id}")
    if banner["tenant_id"] != tenant_id:
        raise ValueError("tenant_mismatch")

    banner["status"] = "disabled"
    banner["updated_at"] = _now_utc()

    logger.info("banner.disabled", banner_id=banner_id, tenant_id=tenant_id)
    return {"banner_id": banner_id, "status": "disabled"}


def clear_all_banners() -> None:
    """清空所有Banner数据 (仅测试用)"""
    _banners.clear()
    _banner_clicks.clear()
    _banner_impressions.clear()
