"""电视拼接点菜墙服务 (TV Menu Wall) — v2 (规则模板智能布局)

融合全球最佳实践:
- 日本回转寿司屏: 单品独立展示+新鲜度
- 韩国BBQ数字菜单: 食材分区+触控直连POS
- 美国Eatsa: LED动效+个性化推荐
- 新加坡Hawker: 实时沽清+等候时间
- 海底捞智慧餐厅: 投影互动概念

支持2-12块屏拼接,实时库存同步,规则驱动智能排版,基于时段/天气切换。

约束 (CLAUDE.md §13):
- 不调用 Claude API 实时排版（成本过高），改用基于规则的模板引擎
- 所有查询带 tenant_id (RLS)
- 禁止 broad except
- 金额全部用分（整数）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

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
    "rainy": {"prefer_tags": ["汤品", "火锅", "煲仔", "暖饮"], "label": "雨天暖心推荐"},
    "hot": {"prefer_tags": ["凉菜", "冷饮", "刺身", "沙拉"], "label": "清凉消暑"},
    "cold": {"prefer_tags": ["火锅", "煲汤", "热饮", "羊肉"], "label": "冬日暖胃"},
    "snowy": {"prefer_tags": ["火锅", "热汤", "羊肉", "热饮"], "label": "雪天暖胃"},
    "windy": {"prefer_tags": ["热汤", "煲仔饭"], "label": "大风暖身"},
    "normal": {"prefer_tags": [], "label": "今日推荐"},
}

# ─── 节日主题 ───

FESTIVAL_THEMES = {
    "spring_festival": {"color": "#FF2D2D", "label": "新春特惠", "bg": "red_gold"},
    "mid_autumn": {"color": "#FFB800", "label": "中秋团圆", "bg": "gold_moon"},
    "valentines": {"color": "#FF69B4", "label": "浪漫晚餐", "bg": "pink_hearts"},
    "christmas": {"color": "#2ECC71", "label": "圣诞特供", "bg": "green_red"},
    "dragon_boat": {"color": "#4CAF50", "label": "端午粽香", "bg": "bamboo"},
    "national_day": {"color": "#FF0000", "label": "国庆同庆", "bg": "red_star"},
    "normal": {"color": "#FF6B35", "label": "经典菜单", "bg": "default"},
}


# ═══════════════════════════════════════════════════════════════════
# 旧端点：保留原有 11 个 service 函数
# ═══════════════════════════════════════════════════════════════════


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
    logger.info("tv_menu.layout", store_id=store_id, tenant_id=tenant_id, screens=screen_count, zones=len(layout))
    # 同时返回前端 camelCase 字段，便于直接消费
    screens_payload = []
    for idx, zone in enumerate(layout):
        screens_payload.append(
            {
                "screenId": idx,
                "zone": zone["zone"],
                "dishes": [],
                "gridCols": 4,
                "gridRows": 3,
                "refreshInterval": 30,
            }
        )
    return {
        "store_id": store_id,
        "screen_count": screen_count,
        "zones": layout,
        "supported_counts": supported,
        "refresh_interval_s": 30,
        # camelCase 镜像，前端 MenuWallLayout 直接可用
        "storeId": store_id,
        "storeName": f"门店 {store_id}",
        "screens": screens_payload,
        "brandColor": "#FF6B35",
    }


async def get_screen_content(
    store_id: str,
    screen_id: int,
    zone_type: str,
    tenant_id: str,
    db: Any,
) -> dict:
    """获取单块屏幕内容(mock, 接入菜品库后替换)"""
    logger.info(
        "tv_menu.screen_content",
        store_id=store_id,
        tenant_id=tenant_id,
        screen_id=screen_id,
        zone=zone_type,
    )
    return {
        "screen_id": screen_id,
        "screenId": screen_id,
        "zone_type": zone_type,
        "zone": zone_type,
        "dishes": [],
        "layout": "grid_3x4" if zone_type not in ("hero", "seafood") else "hero_banner",
        "gridCols": 3 if zone_type in ("hero", "seafood") else 4,
        "gridRows": 1 if zone_type == "hero" else 3,
        "animation": "fade",
        "refresh_interval_s": 30,
        "refreshInterval": 30,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def get_realtime_status(store_id: str, tenant_id: str, db: Any) -> dict:
    """实时状态：沽清+变价（前端 RealtimeStatus 兼容）"""
    soldout = list(_soldout_marks.get((tenant_id, store_id), set()))
    return {
        "store_id": store_id,
        "sold_out_count": len(soldout),
        "low_stock_count": 0,
        "active_dishes": 0,
        "last_sync": datetime.now(timezone.utc).isoformat(),
        # 前端契约 (camelCase)
        "soldOutIds": soldout,
        "updatedPrices": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
    logger.info(
        "tv_menu.time_recommend",
        store_id=store_id,
        tenant_id=tenant_id,
        slot=slot["slot"],
    )
    return {
        "store_id": store_id,
        "time_slot": slot["slot"],
        "label": slot["label"],
        "prefer_tags": slot["tags"],
        "dishes": [],
        # camelCase
        "timeSlot": slot["slot"],
        "dishIds": [],
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
        "dishIds": [],
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
    score = (
        margin_rate * 0.4
        + min(sales_count / 100, 1.0) * 0.3
        + (rating / 5.0) * 0.2
        + (0.1 if is_new else 0.0)
    )
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
    """规则模板智能布局（不调 Claude API）

    输入：门店候选菜品（mock，接入 tx-menu 后替换）
    规则：
      1. 按时段过滤（早/午/下午茶/晚/宵夜）
      2. 按天气过滤（如雨天加权汤品）
      3. 售罄菜品自动隐藏
      4. 高毛利 + 高销量加权排序
      5. 按得分百分位决定 hero/medium/small/text
    """
    candidates = _mock_candidate_dishes()
    slot = _get_current_time_slot()
    layout, reason = apply_smart_layout_rules(
        candidates,
        time_slot=slot["slot"],
        weather="normal",
        soldout_ids=set(),
    )
    return {
        "store_id": store_id,
        "algorithm": "rule_based_v2 (margin0.4+sales0.3+rating0.2+new0.1) × time × weather",
        "reason": reason,
        "dishes": [d for screen in layout for d in screen["dishes"]],
        "layout": layout,
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
    logger.info(
        "tv_menu.order",
        store_id=store_id,
        tenant_id=tenant_id,
        table_id=table_id,
        items=len(items),
    )
    return {
        "order_id": order_id,
        "source": "tv_menu_wall",
        "store_id": store_id,
        "table_id": table_id,
        "item_count": len(items),
        "status": "submitted",
    }


# ═══════════════════════════════════════════════════════════════════
# 屏幕注册中心（in-memory，生产应替换为 Redis/PG）
# 注：key 包含 tenant_id 实现租户隔离
# ═══════════════════════════════════════════════════════════════════

_screen_registry: dict[tuple[str, str], list[dict]] = {}
_screen_heartbeats: dict[tuple[str, str, str], datetime] = {}
_soldout_marks: dict[tuple[str, str], set[str]] = {}


async def register_screen(
    store_id: str,
    screen_id: str,
    ip: str,
    position: str,
    size_inches: int,
    tenant_id: str,
    db: Any,
) -> dict:
    """注册屏幕（带 tenant 隔离）"""
    info = {
        "screen_id": screen_id,
        "screenId": screen_id,
        "ip": ip,
        "position": position,
        "size_inches": size_inches,
        "sizeInches": size_inches,
        "store_id": store_id,
        "status": "online",
        "zone": "signature",
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    key = (tenant_id, store_id)
    bucket = _screen_registry.setdefault(key, [])
    # 同一 screen_id 重复注册 → 覆盖
    bucket = [s for s in bucket if s["screen_id"] != screen_id]
    bucket.append(info)
    _screen_registry[key] = bucket
    _screen_heartbeats[(tenant_id, store_id, screen_id)] = datetime.now(timezone.utc)
    logger.info(
        "tv_menu.screen_registered",
        store_id=store_id,
        tenant_id=tenant_id,
        screen_id=screen_id,
        ip=ip,
    )
    return info


async def get_screen_group_config(store_id: str, tenant_id: str, db: Any) -> dict:
    """获取门店屏幕组配置"""
    screens = _screen_registry.get((tenant_id, store_id), [])
    return {
        "store_id": store_id,
        "screen_count": len(screens),
        "screens": screens,
    }


async def get_seafood_price_board(store_id: str, tenant_id: str, db: Any) -> dict:
    """海鲜时价板(类股票行情)"""
    items = _mock_seafood_items()
    return {
        "store_id": store_id,
        "board_type": "seafood_price",
        "items": items,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "last_update": datetime.now(timezone.utc).isoformat(),
    }


async def get_ranking_board(store_id: str, metric: str, tenant_id: str, db: Any) -> dict:
    """排行榜"""
    valid_metrics = ["hot_sales", "best_rated", "repeat_order", "repeat_buy"]
    if metric not in valid_metrics:
        raise ValueError(f"无效的排行指标: {metric}, 支持: {valid_metrics}")
    items = _mock_ranking_items(metric)
    return {
        "store_id": store_id,
        "metric": metric,
        "metricLabel": _ranking_label(metric),
        "items": items,
        "top_dishes": items,
    }


# ═══════════════════════════════════════════════════════════════════
# 14 个新端点：service 实现
# ═══════════════════════════════════════════════════════════════════


async def get_waitlist_current(store_id: str, tenant_id: str, db: Any) -> dict:
    """1. 当前叫号 — QueueDisplayPage 用"""
    logger.info("tv_menu.waitlist_current", store_id=store_id, tenant_id=tenant_id)
    # mock，后续接入 waitlist_router 真实数据
    return {
        "current_number": "A025",
        "waiting_tables": 8,
        "recent_numbers": ["A019", "A020", "A021", "A022", "A023", "A024", "A025"],
        "store_name": f"门店 {store_id}",
        "estimated_minutes": 25,
    }


async def get_waitlist_detailed(store_id: str, tenant_id: str, db: Any) -> dict:
    """2. 等位详情（小/中/大桌） — WaitingDisplayPage 用"""
    logger.info("tv_menu.waitlist_detailed", store_id=store_id, tenant_id=tenant_id)
    return {
        "store_name": f"门店 {store_id}",
        "current_call": "A038",
        "queues": [
            {"label": "小桌 (2人)", "current_number": "A038", "waiting_count": 5},
            {"label": "中桌 (4人)", "current_number": "B021", "waiting_count": 8},
            {"label": "大桌 (8人)", "current_number": "C012", "waiting_count": 3},
        ],
    }


async def get_categories(store_id: str, tenant_id: str, db: Any) -> list[dict]:
    """3. 菜单分类列表 — MenuDisplayPage 用"""
    logger.info("tv_menu.categories", store_id=store_id, tenant_id=tenant_id)
    return [
        {"id": "1", "name": "招牌菜品"},
        {"id": "2", "name": "海鲜精选"},
        {"id": "3", "name": "家常小炒"},
        {"id": "4", "name": "汤羹炖品"},
        {"id": "5", "name": "主食面点"},
        {"id": "6", "name": "时令蔬菜"},
        {"id": "7", "name": "荤素凉菜"},
        {"id": "8", "name": "精酿饮品"},
    ]


async def get_dishes_by_category(
    store_id: str,
    category_id: str,
    is_available: bool,
    tenant_id: str,
    db: Any,
) -> list[dict]:
    """4. 按分类获取菜品 — MenuDisplayPage 用"""
    logger.info(
        "tv_menu.dishes_by_cat",
        store_id=store_id,
        tenant_id=tenant_id,
        category_id=category_id,
    )
    soldout = _soldout_marks.get((tenant_id, store_id), set())
    dishes = _mock_candidate_dishes()
    filtered = [d for d in dishes if d.get("category_id") == category_id or category_id == "0"]
    if is_available:
        filtered = [d for d in filtered if not d["is_soldout"]]
    # 注入门店级沽清
    for d in filtered:
        if d["id"] in soldout:
            d["is_soldout"] = True
    return filtered


async def get_sales_today(store_id: str, tenant_id: str, db: Any) -> dict:
    """5. 今日营业数据 — SalesDisplayPage 用"""
    logger.info("tv_menu.sales_today", store_id=store_id, tenant_id=tenant_id)
    return {
        "store_name": f"门店 {store_id}",
        "overview": {
            "revenue": 68520,
            "revenue_change": 12.5,
            "order_count": 186,
            "avg_ticket": 368,
            "turnover_rate": 2.8,
        },
        "top_dishes": [
            {"rank": 1, "name": "蒜蓉粉丝蒸扇贝", "sold": 62},
            {"rank": 2, "name": "清蒸石斑鱼", "sold": 55},
            {"rank": 3, "name": "避风塘炒蟹", "sold": 48},
            {"rank": 4, "name": "白灼基围虾", "sold": 41},
            {"rank": 5, "name": "椒盐皮皮虾", "sold": 37},
        ],
        "payment_shares": [
            {"method": "微信支付", "percent": 45, "color": "#07C160"},
            {"method": "支付宝", "percent": 30, "color": "#1677FF"},
            {"method": "现金", "percent": 10, "color": "#FFD700"},
            {"method": "银行卡", "percent": 10, "color": "#C0C0C0"},
            {"method": "会员余额", "percent": 5, "color": "#FF6B35"},
        ],
        "hourly_revenue": [
            {"hour": h, "amount": amt}
            for h, amt in zip(
                range(10, 22),
                [1200, 8500, 18200, 12800, 4500, 2100, 3200, 6800, 15600, 19200, 14500, 8200],
            )
        ],
        "recent_orders": [
            {"id": f"T20260504-{200 - i}", "time": f"20:{35 - i * 3:02d}", "items": "示例 等3道", "amount": 528 - i * 30}
            for i in range(8)
        ],
        "reviews": [
            {"text": '"石斑鱼超级新鲜，肉质嫩滑！" —— 微信用户'},
            {"text": '"服务态度很好，上菜速度也快" —— 大众点评'},
            {"text": '"环境优雅，适合家庭聚餐" —— 美团用户'},
        ],
    }


async def get_combo_showcase(store_id: str, tenant_id: str, db: Any) -> dict:
    """6. 套餐展示 — ComboShowcase 用"""
    logger.info("tv_menu.combo", store_id=store_id, tenant_id=tenant_id)
    return {
        "items": [
            {
                "id": "combo-1",
                "name": "家庭欢享 4 人套餐",
                "price": 39800,
                "image": "",
                "servesCount": "4 人",
                "description": "精选招牌菜搭配，超值畅享",
                "dishes": [
                    {"name": "蒜蓉龙虾", "quantity": 1},
                    {"name": "清蒸鲈鱼", "quantity": 1},
                    {"name": "避风塘炒蟹", "quantity": 1},
                    {"name": "白灼基围虾", "quantity": 1},
                ],
            },
            {
                "id": "combo-2",
                "name": "商务宴请 8 人套餐",
                "price": 88800,
                "image": "",
                "servesCount": "8 人",
                "description": "高端食材，宴请首选",
                "dishes": [
                    {"name": "葱烧海参", "quantity": 1},
                    {"name": "清蒸石斑鱼", "quantity": 1},
                    {"name": "蒸汽海鲜锅", "quantity": 1},
                    {"name": "招牌剁椒鱼头", "quantity": 1},
                ],
            },
        ]
    }


async def get_festival_theme(store_id: str, tenant_id: str, db: Any) -> dict:
    """7. 节日主题（基于当前日期返回主题色） — TV 顶栏用"""
    festival = _detect_festival(datetime.now())
    theme = FESTIVAL_THEMES.get(festival, FESTIVAL_THEMES["normal"])
    return {
        "store_id": store_id,
        "festival": festival,
        "theme": theme,
    }


async def get_weather_mock(city: str) -> dict:
    """8. Mock 天气 — 替代真实天气 API（按城市哈希返回稳定值）

    生产可接入：和风天气 API / 高德天气 API。
    现在用 mock 是因为：
      1. 演示稳定可复现
      2. 避免外部依赖导致 P99 抖动
      3. Tier 2 任务，先打通链路
    """
    code_pool = ["normal", "rainy", "hot", "cold", "snowy", "windy"]
    # 用 city + 当前小时 hash 出稳定 weather code
    seed = (hash(city) + datetime.now().hour) % len(code_pool)
    weather = code_pool[seed]
    return {
        "city": city,
        "weather": weather,
        "temperature_c": 5 + (hash(city) % 30),
        "label": WEATHER_RECOMMENDATIONS[weather]["label"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "mock",
    }


async def screen_heartbeat(
    store_id: str,
    screen_id: str,
    tenant_id: str,
    db: Any,
) -> dict:
    """9. 屏幕心跳 — 用于检测掉线"""
    key = (tenant_id, store_id, screen_id)
    _screen_heartbeats[key] = datetime.now(timezone.utc)
    logger.info(
        "tv_menu.screen_heartbeat",
        store_id=store_id,
        tenant_id=tenant_id,
        screen_id=screen_id,
    )
    return {
        "screen_id": screen_id,
        "status": "ok",
        "received_at": datetime.now(timezone.utc).isoformat(),
    }


async def screen_unregister(
    store_id: str,
    screen_id: str,
    tenant_id: str,
    db: Any,
) -> dict:
    """10. 屏幕注销"""
    key = (tenant_id, store_id)
    bucket = _screen_registry.get(key, [])
    new_bucket = [s for s in bucket if s["screen_id"] != screen_id]
    if len(new_bucket) == len(bucket):
        return {"screen_id": screen_id, "removed": False}
    _screen_registry[key] = new_bucket
    _screen_heartbeats.pop((tenant_id, store_id, screen_id), None)
    logger.info(
        "tv_menu.screen_unregistered",
        store_id=store_id,
        tenant_id=tenant_id,
        screen_id=screen_id,
    )
    return {"screen_id": screen_id, "removed": True}


async def mark_sold_out(
    store_id: str,
    dish_ids: list[str],
    tenant_id: str,
    db: Any,
) -> dict:
    """11. 手动标记沽清"""
    key = (tenant_id, store_id)
    bucket = _soldout_marks.setdefault(key, set())
    for did in dish_ids:
        bucket.add(did)
    logger.info(
        "tv_menu.mark_soldout",
        store_id=store_id,
        tenant_id=tenant_id,
        count=len(dish_ids),
    )
    return {
        "store_id": store_id,
        "marked_count": len(dish_ids),
        "total_soldout": len(bucket),
    }


async def get_sold_out_list(store_id: str, tenant_id: str, db: Any) -> dict:
    """12. 沽清菜品列表"""
    key = (tenant_id, store_id)
    return {
        "store_id": store_id,
        "soldOutIds": list(_soldout_marks.get(key, set())),
        "count": len(_soldout_marks.get(key, set())),
    }


async def get_timeslot_switch(store_id: str, tenant_id: str, db: Any) -> dict:
    """13. 按时段切换菜单组 — 比 /recommend 更明确：返回应该展示哪一组菜单

    规则：
      breakfast/lunch/dinner/supper 各对应不同的 zone 集合，TV 按此切屏。
    """
    slot = _get_current_time_slot()
    # 按时段决定主推 zone 集合
    zone_map = {
        "breakfast": ["signature", "rice"],
        "lunch": ["signature", "hot", "rice"],
        "afternoon": ["drink", "cold"],
        "dinner": ["signature", "seafood", "hot", "drink"],
        "supper": ["hot", "drink"],
    }
    return {
        "store_id": store_id,
        "current_slot": slot["slot"],
        "label": slot["label"],
        "active_zones": zone_map.get(slot["slot"], ["signature"]),
        "switched_at": datetime.now(timezone.utc).isoformat(),
        "next_switch_in_min": _minutes_to_next_slot(slot),
    }


async def get_health() -> dict:
    """14. 服务健康/版本"""
    return {
        "service": "tx-trade.tv-menu",
        "version": "v2.0",
        "status": "healthy",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "registered_screens": sum(len(v) for v in _screen_registry.values()),
        "soldout_buckets": len(_soldout_marks),
    }


# ═══════════════════════════════════════════════════════════════════
# 规则模板布局引擎 (核心算法)
# ═══════════════════════════════════════════════════════════════════


def apply_smart_layout_rules(
    candidates: list[dict],
    time_slot: str,
    weather: str,
    soldout_ids: set[str],
    max_screens: int = 4,
    per_screen: int = 6,
) -> tuple[list[dict], str]:
    """规则驱动的布局算法（不调 Claude API）

    步骤：
      1. 过滤售罄
      2. 按时段 tags 加权
      3. 按天气 tags 加权
      4. 按毛利+销量+评分综合得分排序
      5. 按得分百分位划分 hero/medium/small/text
      6. 切片到 max_screens 个屏幕

    返回：(screens_list, reason)
    """
    # 1. 过滤售罄（Tier 2 — 售罄菜品自动隐藏）
    visible = [d for d in candidates if d["id"] not in soldout_ids and not d.get("is_soldout")]

    # 2. 时段加权（早餐时段提升点心权重等）
    time_tags = {s["slot"]: s["tags"] for s in TIME_SLOTS}.get(time_slot, [])
    weather_tags = WEATHER_RECOMMENDATIONS.get(weather, WEATHER_RECOMMENDATIONS["normal"])["prefer_tags"]

    for d in visible:
        score = compute_dish_display_score(
            margin_rate=d.get("margin_rate", 0.5),
            sales_count=d.get("sales_count", 0),
            rating=d.get("rating", 4.0),
            is_new=d.get("is_new", False),
        )
        # 时段命中加 0.15
        if any(t in d.get("tags", []) for t in time_tags):
            score += 0.15
        # 天气命中加 0.10
        if any(t in d.get("tags", []) for t in weather_tags):
            score += 0.10
        d["_score"] = round(score, 4)

    visible.sort(key=lambda x: x["_score"], reverse=True)

    # 3. 切片到屏幕，前几名给大图，后面降级
    screens: list[dict] = []
    total = min(len(visible), max_screens * per_screen)
    if total == 0:
        return [], f"无可用菜品（time={time_slot}, weather={weather}, sold_out={len(soldout_ids)}）"

    for screen_idx in range(max_screens):
        start = screen_idx * per_screen
        end = start + per_screen
        screen_dishes = visible[start:end]
        if not screen_dishes:
            break
        # 第一屏全 hero，后续逐级降级
        for i, d in enumerate(screen_dishes):
            percentile = 1.0 - ((start + i) / total)
            d["display_size"] = classify_display_size(d["_score"], percentile)
        screens.append(
            {
                "screenId": screen_idx,
                "zone": "smart",
                "gridCols": 3 if screen_idx == 0 else 4,
                "gridRows": 2 if screen_idx == 0 else 3,
                "refreshInterval": 30,
                "dishes": screen_dishes,
            }
        )

    reason = (
        f"规则模板: time={time_slot}({len(time_tags)}tags) × "
        f"weather={weather}({len(weather_tags)}tags), "
        f"沽清隐藏 {len(soldout_ids)} 道, "
        f"展示 {sum(len(s['dishes']) for s in screens)}/{len(visible)} 道"
    )
    return screens, reason


# ═══════════════════════════════════════════════════════════════════
# 内部 mock 数据（接入 tx-menu/tx-analytics 后替换）
# ═══════════════════════════════════════════════════════════════════


def _mock_candidate_dishes() -> list[dict]:
    """候选菜品 mock — 接入 tx-menu 后替换为 SQL 查询"""
    base = [
        ("d1", "招牌剁椒鱼头", "1", 8800, 0.62, 220, 4.7, ["招牌", "辣"]),
        ("d2", "蒜蓉龙虾", "2", 28800, 0.48, 88, 4.8, ["海鲜", "时价"]),
        ("d3", "清蒸多宝鱼", "2", 12800, 0.55, 56, 4.6, ["海鲜", "蒸"]),
        ("d4", "避风塘炒蟹", "2", 15800, 0.50, 75, 4.5, ["海鲜", "炒", "辣"]),
        ("d5", "白灼基围虾", "2", 9800, 0.58, 132, 4.7, ["海鲜", "蒸"]),
        ("d6", "椒盐皮皮虾", "2", 5800, 0.60, 109, 4.4, ["海鲜", "炸"]),
        ("d7", "蒜蓉粉丝蒸扇贝", "2", 4800, 0.65, 168, 4.8, ["海鲜", "蒸", "招牌"]),
        ("d8", "红烧大黄鱼", "1", 8800, 0.52, 60, 4.5, ["招牌", "烧"]),
        ("d9", "广式早茶虾饺", "5", 2800, 0.70, 320, 4.6, ["点心", "蒸"]),
        ("d10", "肠粉", "5", 1800, 0.72, 410, 4.5, ["肠粉", "点心"]),
        ("d11", "皮蛋瘦肉粥", "4", 1800, 0.68, 280, 4.4, ["粥品", "汤品"]),
        ("d12", "羊肉煲", "4", 6800, 0.55, 90, 4.6, ["煲汤", "羊肉", "火锅"]),
        ("d13", "凉拌青瓜", "7", 1200, 0.75, 180, 4.2, ["凉菜", "刺身"]),
        ("d14", "招牌冰粉", "8", 1500, 0.80, 200, 4.7, ["甜品", "冷饮"]),
        ("d15", "商务套餐A", "3", 5800, 0.50, 150, 4.5, ["商务套餐", "快餐"]),
    ]
    return [
        {
            "id": did,
            "name": name,
            "category_id": cat,
            "price_fen": price,
            "price": price / 100,
            "spec": "例",
            "is_soldout": False,
            "isSoldOut": False,
            "isRecommended": rating >= 4.7,
            "isMarketPrice": "时价" in tags,
            "image": "",
            "category": cat,
            "tags": tags,
            "margin_rate": margin,
            "sales_count": sales,
            "salesCount": sales,
            "rating": rating,
            "is_new": False,
        }
        for did, name, cat, price, margin, sales, rating, tags in base
    ]


def _mock_seafood_items() -> list[dict]:
    base = [
        ("波士顿龙虾", 268, 258, "alive"),
        ("帝王蟹", 588, 598, "alive"),
        ("澳洲龙虾", 888, 888, "alive"),
        ("东星斑", 368, 348, "alive"),
        ("多宝鱼", 128, 138, "alive"),
        ("基围虾", 88, 88, "alive"),
        ("皮皮虾", 98, 108, "weak"),
        ("花甲", 38, 38, "alive"),
        ("生蚝(打)", 68, 58, "alive"),
        ("扇贝", 48, 48, "alive"),
        ("鲍鱼(只)", 38, 42, "alive"),
        ("大闸蟹", 168, 168, "sold_out"),
    ]
    return [
        {
            "id": f"sf-{i}",
            "name": name,
            "price": price,
            "previousPrice": prev,
            "unit": "元/斤",
            "status": status,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
        for i, (name, price, prev, status) in enumerate(base)
    ]


def _ranking_label(metric: str) -> str:
    return {
        "hot_sales": "本周热销",
        "best_rated": "好评最多",
        "repeat_order": "回头客最爱",
        "repeat_buy": "回头客最爱",
    }.get(metric, metric)


def _mock_ranking_items(metric: str) -> list[dict]:
    dishes_pool = {
        "hot_sales": [
            ("d7", "蒜蓉粉丝蒸扇贝", 168),
            ("d5", "白灼基围虾", 132),
            ("d6", "椒盐皮皮虾", 109),
            ("d4", "避风塘炒蟹", 75),
            ("d2", "蒜蓉龙虾", 88),
            ("d1", "招牌剁椒鱼头", 220),
            ("d3", "清蒸多宝鱼", 56),
            ("d8", "红烧大黄鱼", 60),
            ("d9", "广式早茶虾饺", 320),
            ("d10", "肠粉", 410),
        ],
        "best_rated": [
            ("d7", "蒜蓉粉丝蒸扇贝", 4.8),
            ("d2", "蒜蓉龙虾", 4.8),
            ("d14", "招牌冰粉", 4.7),
            ("d1", "招牌剁椒鱼头", 4.7),
            ("d5", "白灼基围虾", 4.7),
            ("d3", "清蒸多宝鱼", 4.6),
            ("d12", "羊肉煲", 4.6),
            ("d9", "广式早茶虾饺", 4.6),
            ("d4", "避风塘炒蟹", 4.5),
            ("d10", "肠粉", 4.5),
        ],
    }
    items = dishes_pool.get(metric, dishes_pool["hot_sales"])
    label = "份" if metric == "hot_sales" else ("分" if metric == "best_rated" else "次")
    return [
        {"rank": i + 1, "dishId": did, "name": name, "value": val, "label": label}
        for i, (did, name, val) in enumerate(items)
    ]


def _detect_festival(now: datetime) -> str:
    """简单的节日检测（按月日近似匹配）"""
    md = (now.month, now.day)
    if (1, 20) <= md <= (2, 15):
        return "spring_festival"
    if (9, 10) <= md <= (9, 25):
        return "mid_autumn"
    if md == (2, 14):
        return "valentines"
    if md == (12, 25) or (12, 23) <= md <= (12, 25):
        return "christmas"
    if (5, 28) <= md <= (6, 15):
        return "dragon_boat"
    if md == (10, 1) or (10, 1) <= md <= (10, 7):
        return "national_day"
    return "normal"


def _minutes_to_next_slot(current_slot: dict) -> int:
    """距离下一个时段切换还有多少分钟"""
    now = datetime.now()
    end_hour = current_slot["end"]
    if end_hour >= 24:
        end_hour -= 24
    next_change = now.replace(hour=end_hour % 24, minute=0, second=0, microsecond=0)
    if next_change <= now:
        # 已过当天该时段终点，next is +1 day
        delta_min = (24 * 60) + (next_change.hour * 60) - (now.hour * 60 + now.minute)
    else:
        delta_min = int((next_change - now).total_seconds() // 60)
    return max(delta_min, 0)
