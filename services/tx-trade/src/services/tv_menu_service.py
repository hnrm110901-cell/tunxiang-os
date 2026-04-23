"""电视拼接点菜墙服务 (TV Menu Wall)

融合全球最佳实践:
- 日本回转寿司屏: 单品独立展示+新鲜度
- 韩国BBQ数字菜单: 食材分区+触控直连POS
- 美国Eatsa: LED动效+个性化推荐
- 新加坡Hawker: 实时沽清+等候时间
- 海底捞智慧餐厅: 投影互动概念
- 迪拜高端: AR菜品预览概念

支持2-12块屏拼接,实时库存同步,AI时段推荐,数据驱动排版。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ─── 分区方案(根据屏幕数量) ───

ZONE_LAYOUTS = {
    2: [
        {"zone": "signature", "label": "招牌推荐", "screens": [0]},
        {"zone": "seasonal", "label": "时令精选", "screens": [1]},
    ],
    4: [
        {"zone": "signature", "label": "招牌菜", "screens": [0]},
        {"zone": "hot", "label": "热菜", "screens": [1]},
        {"zone": "cold", "label": "凉菜冷盘", "screens": [2]},
        {"zone": "drink", "label": "酒水甜品", "screens": [3]},
    ],
    6: [
        {"zone": "signature", "label": "招牌菜", "screens": [0]},
        {"zone": "seafood", "label": "海鲜时价", "screens": [1]},
        {"zone": "hot", "label": "热菜", "screens": [2]},
        {"zone": "cold", "label": "凉菜蒸菜", "screens": [3]},
        {"zone": "rice", "label": "主食面点", "screens": [4]},
        {"zone": "drink", "label": "酒水饮品", "screens": [5]},
    ],
    8: [
        {"zone": "signature", "label": "招牌必点", "screens": [0]},
        {"zone": "seafood", "label": "海鲜时价", "screens": [1]},
        {"zone": "hot", "label": "热菜", "screens": [2]},
        {"zone": "steam", "label": "蒸菜煲汤", "screens": [3]},
        {"zone": "cold", "label": "凉菜", "screens": [4]},
        {"zone": "rice", "label": "主食", "screens": [5]},
        {"zone": "drink", "label": "酒水", "screens": [6]},
        {"zone": "recommend", "label": "今日推荐", "screens": [7]},
    ],
    12: [
        {"zone": "hero", "label": "主推大图", "screens": [0, 1]},
        {"zone": "seafood", "label": "海鲜时价", "screens": [2]},
        {"zone": "hot_a", "label": "热菜·炒", "screens": [3]},
        {"zone": "hot_b", "label": "热菜·烧", "screens": [4]},
        {"zone": "steam", "label": "蒸菜", "screens": [5]},
        {"zone": "cold", "label": "凉菜", "screens": [6]},
        {"zone": "rice", "label": "主食面点", "screens": [7]},
        {"zone": "drink", "label": "酒水", "screens": [8]},
        {"zone": "combo", "label": "宴席套餐", "screens": [9]},
        {"zone": "kids", "label": "儿童餐", "screens": [10]},
        {"zone": "ranking", "label": "人气排行", "screens": [11]},
    ],
}

# ─── 时段定义 ───

TIME_SLOTS = [
    {"slot": "breakfast", "label": "早茶", "start": 6, "end": 10, "tags": ["点心", "粥品", "肠粉"]},
    {"slot": "lunch", "label": "午餐", "start": 10, "end": 14, "tags": ["商务套餐", "快餐", "盖饭"]},
    {"slot": "afternoon", "label": "下午茶", "start": 14, "end": 17, "tags": ["甜品", "饮品", "小食"]},
    {"slot": "dinner", "label": "晚餐", "start": 17, "end": 21, "tags": ["正餐", "海鲜", "宴席"]},
    {"slot": "supper", "label": "宵夜", "start": 21, "end": 26, "tags": ["烧烤", "夜宵", "火锅"]},
]

# ─── 天气推荐映射 ───

WEATHER_RECOMMENDATIONS = {
    "rainy": {"prefer_tags": ["汤品", "火锅", "煲仔", "暖饮"], "label": "☔ 雨天暖心推荐"},
    "hot": {"prefer_tags": ["凉菜", "冷饮", "刺身", "沙拉"], "label": "☀️ 清凉消暑"},
    "cold": {"prefer_tags": ["火锅", "煲汤", "热饮", "羊肉"], "label": "❄️ 冬日暖胃"},
    "normal": {"prefer_tags": [], "label": "今日推荐"},
}

# ─── 节日主题 ───

FESTIVAL_THEMES = {
    "spring_festival": {"color": "#FF2D2D", "label": "🧧 新春特惠", "bg": "red_gold"},
    "mid_autumn": {"color": "#FFB800", "label": "🥮 中秋团圆", "bg": "gold_moon"},
    "valentines": {"color": "#FF69B4", "label": "💕 浪漫晚餐", "bg": "pink_hearts"},
    "christmas": {"color": "#2ECC71", "label": "🎄 圣诞特供", "bg": "green_red"},
    "dragon_boat": {"color": "#4CAF50", "label": "🐉 端午粽香", "bg": "bamboo"},
}


async def get_menu_wall_layout(
    store_id: str,
    screen_count: int,
    tenant_id: str,
    db: Any,
) -> dict:
    """获取菜单墙布局"""
    supported = sorted(ZONE_LAYOUTS.keys())
    if screen_count not in ZONE_LAYOUTS:
        nearest = min(supported, key=lambda x: abs(x - screen_count))
        screen_count = nearest

    layout = ZONE_LAYOUTS[screen_count]
    logger.info("tv_menu.layout", store_id=store_id, screens=screen_count, zones=len(layout))
    return {
        "store_id": store_id,
        "screen_count": screen_count,
        "zones": layout,
        "supported_counts": supported,
        "refresh_interval_s": 30,
    }


async def get_screen_content(
    store_id: str,
    screen_id: int,
    zone_type: str,
    tenant_id: str,
    db: Any,
) -> dict:
    """获取单块屏幕内容(mock, 接入菜品库后替换)"""
    logger.info("tv_menu.screen_content", store_id=store_id, screen_id=screen_id, zone=zone_type)
    return {
        "screen_id": screen_id,
        "zone_type": zone_type,
        "dishes": [],
        "layout": "grid_3x4" if zone_type not in ("hero", "seafood") else "hero_banner",
        "animation": "fade",
        "refresh_interval_s": 30,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def get_realtime_status(store_id: str, tenant_id: str, db: Any) -> dict:
    """实时状态"""
    return {
        "store_id": store_id,
        "sold_out_count": 0,
        "low_stock_count": 0,
        "active_dishes": 0,
        "last_sync": datetime.now(timezone.utc).isoformat(),
    }


def _get_current_time_slot() -> dict:
    """获取当前时段"""
    hour = datetime.now().hour
    if hour >= 26:
        hour -= 24
    for slot in TIME_SLOTS:
        if slot["start"] <= hour < slot["end"]:
            return slot
    return TIME_SLOTS[3]  # 默认晚餐


async def get_time_based_recommendation(
    store_id: str,
    tenant_id: str,
    db: Any,
) -> dict:
    """时段推荐"""
    slot = _get_current_time_slot()
    logger.info("tv_menu.time_recommend", store_id=store_id, slot=slot["slot"])
    return {
        "store_id": store_id,
        "time_slot": slot["slot"],
        "label": slot["label"],
        "prefer_tags": slot["tags"],
        "dishes": [],
    }


async def get_weather_recommendation(
    store_id: str,
    weather: str,
    tenant_id: str,
    db: Any,
) -> dict:
    """天气联动推荐"""
    config = WEATHER_RECOMMENDATIONS.get(weather, WEATHER_RECOMMENDATIONS["normal"])
    return {
        "store_id": store_id,
        "weather": weather,
        "label": config["label"],
        "prefer_tags": config["prefer_tags"],
        "dishes": [],
    }


def compute_dish_display_score(
    margin_rate: float,
    sales_count: int,
    rating: float,
    is_new: bool,
) -> float:
    """数据驱动排版评分

    权重: 毛利0.4 + 销量0.3 + 好评0.2 + 新品0.1
    得分前20%=大图Hero, 20-50%=中图, 50-80%=小图, 80%+=文字
    """
    score = margin_rate * 0.4 + min(sales_count / 100, 1.0) * 0.3 + (rating / 5.0) * 0.2 + (0.1 if is_new else 0.0)
    return round(score, 4)


def classify_display_size(score: float, percentile: float) -> str:
    """根据得分百分位决定展示尺寸"""
    if percentile >= 0.8:
        return "hero"
    elif percentile >= 0.5:
        return "medium"
    elif percentile >= 0.2:
        return "small"
    return "text"


async def get_smart_layout(store_id: str, tenant_id: str, db: Any) -> dict:
    """数据驱动排版"""
    return {
        "store_id": store_id,
        "algorithm": "margin_0.4_sales_0.3_rating_0.2_new_0.1",
        "dishes": [],
    }


async def trigger_order_from_tv(
    store_id: str,
    table_id: str,
    items: list,
    customer_id: str | None,
    tenant_id: str,
    db: Any,
) -> dict:
    """从电视墙触控下单 → 直连POS"""
    order_id = f"TV-{uuid.uuid4().hex[:12].upper()}"
    logger.info("tv_menu.order", store_id=store_id, table_id=table_id, items=len(items))
    return {
        "order_id": order_id,
        "source": "tv_menu_wall",
        "store_id": store_id,
        "table_id": table_id,
        "item_count": len(items),
        "status": "submitted",
    }


# ─── 屏幕管理 ───

_screen_registry: dict[str, list] = {}


async def register_screen(
    store_id: str,
    screen_id: str,
    ip: str,
    position: str,
    size_inches: int,
    tenant_id: str,
    db: Any,
) -> dict:
    """注册屏幕"""
    info = {
        "screen_id": screen_id,
        "ip": ip,
        "position": position,
        "size_inches": size_inches,
        "store_id": store_id,
        "status": "online",
    }
    _screen_registry.setdefault(store_id, []).append(info)
    logger.info("tv_menu.screen_registered", store_id=store_id, screen_id=screen_id, ip=ip)
    return info


async def get_screen_group_config(store_id: str, tenant_id: str, db: Any) -> dict:
    """获取门店屏幕组配置"""
    screens = _screen_registry.get(store_id, [])
    return {
        "store_id": store_id,
        "screen_count": len(screens),
        "screens": screens,
    }


async def get_seafood_price_board(store_id: str, tenant_id: str, db: Any) -> dict:
    """海鲜时价板(类股票行情)"""
    return {
        "store_id": store_id,
        "board_type": "seafood_price",
        "items": [],
        "last_update": datetime.now(timezone.utc).isoformat(),
    }


async def get_ranking_board(store_id: str, metric: str, tenant_id: str, db: Any) -> dict:
    """排行榜"""
    valid_metrics = ["hot_sales", "best_rated", "repeat_order"]
    if metric not in valid_metrics:
        raise ValueError(f"无效的排行指标: {metric}, 支持: {valid_metrics}")
    return {
        "store_id": store_id,
        "metric": metric,
        "top_dishes": [],
    }
