"""
菜品5因子动态排名引擎 — 基于真实行为数据持续优化权重
P3-04: 差异化护城河
5因子：销量(volume) / 毛利(margin) / 复购率(reorder) / 满意度(satisfaction) / 热度趋势(trend)
"""
import structlog
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import date, timedelta
import uuid

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/menu/ranking", tags=["dish-ranking"])

# ─── Mock 数据 ──────────────────────────────────────────────────────────────

MOCK_DISHES_RANKING = [
    {
        "dish_id": "dish-001",
        "dish_name": "招牌蒸鱼",
        "category": "主菜",
        "price_fen": 19800,
        "scores": {
            "volume": 0.88,
            "margin": 0.75,
            "reorder": 0.72,
            "satisfaction": 0.93,
            "trend": 0.82,
        },
        "composite_score": 0.826,
        "rank": 1,
        "rank_change": 0,
        "recommendation_tag": "明星菜品",
    },
    {
        "dish_id": "dish-002",
        "dish_name": "白灼虾",
        "category": "海鲜",
        "price_fen": 9800,
        "scores": {
            "volume": 0.91,
            "margin": 0.58,
            "reorder": 0.65,
            "satisfaction": 0.89,
            "trend": 0.74,
        },
        "composite_score": 0.756,
        "rank": 2,
        "rank_change": -1,
        "recommendation_tag": "现金牛",
    },
    {
        "dish_id": "dish-003",
        "dish_name": "清蒸石斑",
        "category": "海鲜",
        "price_fen": 38800,
        "scores": {
            "volume": 0.42,
            "margin": 0.95,
            "reorder": 0.38,
            "satisfaction": 0.88,
            "trend": 0.51,
        },
        "composite_score": 0.618,
        "rank": 5,
        "rank_change": 2,
        "recommendation_tag": "问题菜品",
    },
    {
        "dish_id": "dish-004",
        "dish_name": "蒜蓉粉丝蒸扇贝",
        "category": "海鲜",
        "price_fen": 5800,
        "scores": {
            "volume": 0.79,
            "margin": 0.68,
            "reorder": 0.74,
            "satisfaction": 0.91,
            "trend": 0.88,
        },
        "composite_score": 0.758,
        "rank": 3,
        "rank_change": 3,
        "recommendation_tag": "明星菜品",
    },
    {
        "dish_id": "dish-005",
        "dish_name": "椒盐濑尿虾",
        "category": "海鲜",
        "price_fen": 11800,
        "scores": {
            "volume": 0.65,
            "margin": 0.72,
            "reorder": 0.61,
            "satisfaction": 0.85,
            "trend": 0.62,
        },
        "composite_score": 0.674,
        "rank": 4,
        "rank_change": -1,
        "recommendation_tag": "明星菜品",
    },
    {
        "dish_id": "dish-006",
        "dish_name": "豆腐炖鱼头",
        "category": "主菜",
        "price_fen": 8800,
        "scores": {
            "volume": 0.55,
            "margin": 0.60,
            "reorder": 0.52,
            "satisfaction": 0.78,
            "trend": 0.45,
        },
        "composite_score": 0.562,
        "rank": 6,
        "rank_change": -2,
        "recommendation_tag": "现金牛",
    },
    {
        "dish_id": "dish-007",
        "dish_name": "椰汁芋头糕",
        "category": "甜品",
        "price_fen": 2800,
        "scores": {
            "volume": 0.38,
            "margin": 0.82,
            "reorder": 0.29,
            "satisfaction": 0.75,
            "trend": 0.31,
        },
        "composite_score": 0.489,
        "rank": 7,
        "rank_change": 1,
        "recommendation_tag": "问题菜品",
    },
    {
        "dish_id": "dish-008",
        "dish_name": "干炒牛河",
        "category": "主食",
        "price_fen": 3800,
        "scores": {
            "volume": 0.72,
            "margin": 0.45,
            "reorder": 0.68,
            "satisfaction": 0.82,
            "trend": 0.58,
        },
        "composite_score": 0.625,
        "rank": 8,
        "rank_change": 0,
        "recommendation_tag": "现金牛",
    },
    {
        "dish_id": "dish-009",
        "dish_name": "煲仔饭（腊肉）",
        "category": "主食",
        "price_fen": 2800,
        "scores": {
            "volume": 0.68,
            "margin": 0.78,
            "reorder": 0.72,
            "satisfaction": 0.88,
            "trend": 0.65,
        },
        "composite_score": 0.714,
        "rank": 9,
        "rank_change": 2,
        "recommendation_tag": "明星菜品",
    },
    {
        "dish_id": "dish-010",
        "dish_name": "酸辣汤",
        "category": "汤羹",
        "price_fen": 1800,
        "scores": {
            "volume": 0.58,
            "margin": 0.62,
            "reorder": 0.48,
            "satisfaction": 0.70,
            "trend": 0.38,
        },
        "composite_score": 0.553,
        "rank": 10,
        "rank_change": -3,
        "recommendation_tag": "现金牛",
    },
    {
        "dish_id": "dish-011",
        "dish_name": "佛跳墙",
        "category": "主菜",
        "price_fen": 68800,
        "scores": {
            "volume": 0.22,
            "margin": 0.92,
            "reorder": 0.18,
            "satisfaction": 0.95,
            "trend": 0.28,
        },
        "composite_score": 0.451,
        "rank": 11,
        "rank_change": -1,
        "recommendation_tag": "问题菜品",
    },
    {
        "dish_id": "dish-012",
        "dish_name": "烤乳猪（半只）",
        "category": "主菜",
        "price_fen": 48800,
        "scores": {
            "volume": 0.28,
            "margin": 0.88,
            "reorder": 0.22,
            "satisfaction": 0.90,
            "trend": 0.35,
        },
        "composite_score": 0.478,
        "rank": 12,
        "rank_change": 1,
        "recommendation_tag": "问题菜品",
    },
    {
        "dish_id": "dish-013",
        "dish_name": "白切鸡",
        "category": "主菜",
        "price_fen": 6800,
        "scores": {
            "volume": 0.82,
            "margin": 0.55,
            "reorder": 0.75,
            "satisfaction": 0.87,
            "trend": 0.70,
        },
        "composite_score": 0.722,
        "rank": 13,
        "rank_change": -1,
        "recommendation_tag": "现金牛",
    },
    {
        "dish_id": "dish-014",
        "dish_name": "豆苗炒虾仁",
        "category": "炒菜",
        "price_fen": 4800,
        "scores": {
            "volume": 0.61,
            "margin": 0.58,
            "reorder": 0.55,
            "satisfaction": 0.82,
            "trend": 0.52,
        },
        "composite_score": 0.590,
        "rank": 14,
        "rank_change": 0,
        "recommendation_tag": "现金牛",
    },
    {
        "dish_id": "dish-015",
        "dish_name": "冬瓜海鲜羹",
        "category": "汤羹",
        "price_fen": 3200,
        "scores": {
            "volume": 0.45,
            "margin": 0.70,
            "reorder": 0.40,
            "satisfaction": 0.78,
            "trend": 0.42,
        },
        "composite_score": 0.522,
        "rank": 15,
        "rank_change": -2,
        "recommendation_tag": "现金牛",
    },
    {
        "dish_id": "dish-016",
        "dish_name": "陈皮鸭",
        "category": "主菜",
        "price_fen": 8800,
        "scores": {
            "volume": 0.18,
            "margin": 0.78,
            "reorder": 0.15,
            "satisfaction": 0.72,
            "trend": 0.20,
        },
        "composite_score": 0.312,
        "rank": 16,
        "rank_change": -3,
        "recommendation_tag": "瘦狗",
    },
    {
        "dish_id": "dish-017",
        "dish_name": "皮蛋豆腐",
        "category": "凉菜",
        "price_fen": 1800,
        "scores": {
            "volume": 0.48,
            "margin": 0.72,
            "reorder": 0.42,
            "satisfaction": 0.80,
            "trend": 0.48,
        },
        "composite_score": 0.558,
        "rank": 17,
        "rank_change": 1,
        "recommendation_tag": "现金牛",
    },
    {
        "dish_id": "dish-018",
        "dish_name": "芒果糯米饭",
        "category": "甜品",
        "price_fen": 2200,
        "scores": {
            "volume": 0.35,
            "margin": 0.65,
            "reorder": 0.30,
            "satisfaction": 0.85,
            "trend": 0.68,
        },
        "composite_score": 0.496,
        "rank": 18,
        "rank_change": 4,
        "recommendation_tag": "潜力菜品",
    },
    {
        "dish_id": "dish-019",
        "dish_name": "腊肠炒荷兰豆",
        "category": "炒菜",
        "price_fen": 3800,
        "scores": {
            "volume": 0.12,
            "margin": 0.60,
            "reorder": 0.10,
            "satisfaction": 0.65,
            "trend": 0.15,
        },
        "composite_score": 0.248,
        "rank": 19,
        "rank_change": -2,
        "recommendation_tag": "瘦狗",
    },
    {
        "dish_id": "dish-020",
        "dish_name": "翡翠虾饺",
        "category": "点心",
        "price_fen": 3200,
        "scores": {
            "volume": 0.52,
            "margin": 0.68,
            "reorder": 0.58,
            "satisfaction": 0.88,
            "trend": 0.76,
        },
        "composite_score": 0.634,
        "rank": 20,
        "rank_change": 5,
        "recommendation_tag": "潜力菜品",
    },
]

# 当前5因子权重（内存存储，实际生产应持久化至DB）
_CURRENT_WEIGHTS = {
    "volume": 0.30,
    "margin": 0.30,
    "reorder": 0.20,
    "satisfaction": 0.10,
    "trend": 0.10,
}

# 品牌类型推荐权重预设
BRAND_WEIGHT_PRESETS = {
    "seafood": {
        "weights": {"volume": 0.20, "margin": 0.40, "reorder": 0.15, "satisfaction": 0.20, "trend": 0.05},
        "reason": "海鲜酒楼食材成本高，毛利管控是核心。满意度决定复购，需重点关注。销量相对稳定，趋势权重可降低。",
    },
    "quick_service": {
        "weights": {"volume": 0.50, "margin": 0.20, "reorder": 0.10, "satisfaction": 0.05, "trend": 0.15},
        "reason": "快餐依赖高频高量，销量是第一指标。趋势敏感度高（网红款迭代快），需提高趋势权重。",
    },
    "hotpot": {
        "weights": {"volume": 0.35, "margin": 0.25, "reorder": 0.25, "satisfaction": 0.10, "trend": 0.05},
        "reason": "火锅注重复购黏性，复购率权重提升。锅底毛利高但配菜竞争激烈，综合毛利管控适中。",
    },
    "canteen": {
        "weights": {"volume": 0.40, "margin": 0.30, "reorder": 0.15, "satisfaction": 0.10, "trend": 0.05},
        "reason": "食堂以量取胜，销量权重最高。预算制成本管控严，毛利同等重要。趋势稳定，权重最低。",
    },
}


# ─── Pydantic Models ────────────────────────────────────────────────────────

class WeightConfig(BaseModel):
    volume: float
    margin: float
    reorder: float
    satisfaction: float
    trend: float

    @field_validator("volume", "margin", "reorder", "satisfaction", "trend")
    @classmethod
    def check_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("每个权重因子必须在 0.0 ~ 1.0 之间")
        return round(v, 4)


class CalibrateRequest(BaseModel):
    brand_type: str  # seafood / quick_service / hotpot / canteen
    period_days: int = 30


# ─── 工具函数 ────────────────────────────────────────────────────────────────

def _apply_weights(dish: dict, weights: dict) -> float:
    """根据权重重新计算综合分"""
    s = dish["scores"]
    return round(
        s["volume"] * weights["volume"]
        + s["margin"] * weights["margin"]
        + s["reorder"] * weights["reorder"]
        + s["satisfaction"] * weights["satisfaction"]
        + s["trend"] * weights["trend"],
        4,
    )


def _get_quadrant(volume_score: float, margin_score: float) -> str:
    """根据销量/毛利因子判断四象限"""
    high_volume = volume_score >= 0.50
    high_margin = margin_score >= 0.60
    if high_volume and high_margin:
        return "star"       # 明星菜品
    if high_volume and not high_margin:
        return "cash_cow"   # 现金牛
    if not high_volume and high_margin:
        return "question"   # 问题菜品
    return "dog"            # 瘦狗


QUADRANT_LABELS = {
    "star": "明星菜品",
    "cash_cow": "现金牛",
    "question": "问题菜品",
    "dog": "瘦狗",
}

QUADRANT_ADVICE = {
    "star": "保持核心竞争力，持续推广，可设为招牌菜/必点菜",
    "cash_cow": "销量好但毛利偏低，建议适度提价或调整原料结构",
    "question": "毛利高但销量不足，建议加大营销推广力度或调整摆盘/描述",
    "dog": "销量和毛利双低，建议限时观察，考虑下架或大幅调整",
}


# ─── 端点 ────────────────────────────────────────────────────────────────────

@router.get("/dishes")
async def get_dish_ranking(
    store_id: str = Query(..., description="门店ID"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    category_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """菜品5因子综合排名（基于当前权重配置动态计算）"""
    logger.info("get_dish_ranking", store_id=store_id, date_from=date_from, date_to=date_to)

    dishes = MOCK_DISHES_RANKING
    if category_id:
        # mock: 按 category_id 过滤（此处用 category 字段模拟）
        dishes = [d for d in dishes if d.get("category") == category_id]

    # 按当前权重重新计算综合分并排序
    recalculated = []
    for d in dishes:
        new_score = _apply_weights(d, _CURRENT_WEIGHTS)
        recalculated.append({**d, "composite_score": new_score})

    recalculated.sort(key=lambda x: x["composite_score"], reverse=True)
    for i, item in enumerate(recalculated):
        item["rank"] = i + 1

    return {
        "ok": True,
        "data": {
            "items": recalculated[:limit],
            "total": len(recalculated),
            "weights_applied": _CURRENT_WEIGHTS,
            "date_from": str(date_from or (date.today() - timedelta(days=7))),
            "date_to": str(date_to or date.today()),
        },
    }


@router.get("/matrix")
async def get_dish_matrix(
    store_id: str = Query(..., description="门店ID"),
):
    """四象限矩阵（BCG风格）— 横轴销量/纵轴毛利"""
    logger.info("get_dish_matrix", store_id=store_id)

    quadrants: dict[str, list] = {"star": [], "cash_cow": [], "question": [], "dog": []}

    for d in MOCK_DISHES_RANKING:
        q = _get_quadrant(d["scores"]["volume"], d["scores"]["margin"])
        quadrants[q].append({
            "dish_id": d["dish_id"],
            "dish_name": d["dish_name"],
            "volume_score": d["scores"]["volume"],
            "margin_score": d["scores"]["margin"],
            "composite_score": d["composite_score"],
            "price_fen": d["price_fen"],
        })

    result = {}
    for key, items in quadrants.items():
        result[key] = {
            "label": QUADRANT_LABELS[key],
            "advice": QUADRANT_ADVICE[key],
            "dishes": sorted(items, key=lambda x: x["composite_score"], reverse=True),
            "count": len(items),
        }

    return {"ok": True, "data": result}


@router.get("/trends")
async def get_dish_trends(
    dish_id: str = Query(..., description="菜品ID"),
    days: int = Query(30, ge=7, le=90),
):
    """菜品近N天综合评分趋势（前端折线图数据）"""
    logger.info("get_dish_trends", dish_id=dish_id, days=days)

    dish = next((d for d in MOCK_DISHES_RANKING if d["dish_id"] == dish_id), None)
    if not dish:
        raise HTTPException(status_code=404, detail=f"菜品 {dish_id} 不存在")

    import random
    random.seed(hash(dish_id) % 1000)
    base_score = dish["composite_score"]
    trend_data = []
    for i in range(days, 0, -1):
        day = date.today() - timedelta(days=i)
        # 模拟小幅波动
        delta = random.uniform(-0.08, 0.08)
        score = round(max(0.1, min(1.0, base_score + delta)), 3)
        trend_data.append({
            "date": str(day),
            "composite_score": score,
            "volume": round(max(0.1, min(1.0, dish["scores"]["volume"] + random.uniform(-0.10, 0.10))), 3),
            "margin": round(max(0.1, min(1.0, dish["scores"]["margin"] + random.uniform(-0.05, 0.05))), 3),
            "satisfaction": round(max(0.1, min(1.0, dish["scores"]["satisfaction"] + random.uniform(-0.06, 0.06))), 3),
        })

    return {
        "ok": True,
        "data": {
            "dish_id": dish_id,
            "dish_name": dish["dish_name"],
            "days": days,
            "trend_series": trend_data,
        },
    }


@router.get("/weights")
async def get_weights():
    """获取当前5因子权重配置"""
    return {
        "ok": True,
        "data": {
            "weights": _CURRENT_WEIGHTS,
            "total": round(sum(_CURRENT_WEIGHTS.values()), 4),
            "description": {
                "volume": "销量因子：衡量菜品的绝对销售量（30天订单数标准化）",
                "margin": "毛利因子：毛利率 × 销售额标准化综合评分",
                "reorder": "复购率因子：同一会员N天内再次点此菜的比率",
                "satisfaction": "满意度因子：好评率 + (1-退菜率) 综合推算",
                "trend": "热度趋势因子：近7天 vs 前7天销量增长率",
            },
        },
    }


@router.put("/weights")
async def update_weights(body: WeightConfig):
    """更新5因子权重（5因子之和必须 = 1.0，否则400）"""
    global _CURRENT_WEIGHTS

    total = round(body.volume + body.margin + body.reorder + body.satisfaction + body.trend, 4)
    if abs(total - 1.0) > 0.001:
        raise HTTPException(
            status_code=400,
            detail=f"5因子权重之和必须等于1.0，当前为 {total}",
        )

    _CURRENT_WEIGHTS = {
        "volume": body.volume,
        "margin": body.margin,
        "reorder": body.reorder,
        "satisfaction": body.satisfaction,
        "trend": body.trend,
    }
    logger.info("weights_updated", **_CURRENT_WEIGHTS)

    return {"ok": True, "data": {"weights": _CURRENT_WEIGHTS, "total": total}}


@router.post("/weights/calibrate")
async def calibrate_weights(body: CalibrateRequest):
    """AI辅助权重校准 — 根据品牌类型推荐最优权重"""
    logger.info("calibrate_weights", brand_type=body.brand_type)

    preset = BRAND_WEIGHT_PRESETS.get(body.brand_type)
    if not preset:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的品牌类型: {body.brand_type}，可选: seafood / quick_service / hotpot / canteen",
        )

    return {
        "ok": True,
        "data": {
            "brand_type": body.brand_type,
            "period_days": body.period_days,
            "recommended_weights": preset["weights"],
            "reason": preset["reason"],
            "confidence": 0.82,
            "current_weights": _CURRENT_WEIGHTS,
            "tip": "建议先在测试门店验证2周后再全量生效",
        },
    }


@router.get("/health-report")
async def get_health_report(
    store_id: str = Query(..., description="门店ID"),
):
    """品项健康诊断报告"""
    logger.info("get_health_report", store_id=store_id)

    # 重新按当前权重计算
    dishes_with_scores = []
    for d in MOCK_DISHES_RANKING:
        score = _apply_weights(d, _CURRENT_WEIGHTS)
        dishes_with_scores.append({**d, "composite_score": score})

    # 1. 需要立即关注：综合评分 < 0.3 → 建议下架/调价
    attention_needed = [
        {
            "dish_id": d["dish_id"],
            "dish_name": d["dish_name"],
            "composite_score": d["composite_score"],
            "reason": _build_attention_reason(d),
            "suggestion": "建议下架或大幅调整定价/做法",
        }
        for d in dishes_with_scores
        if d["composite_score"] < 0.30
    ]

    # 2. 值得推广：综合分 > 0.8 但销量低（volume < 0.4）
    worth_promoting = [
        {
            "dish_id": d["dish_id"],
            "dish_name": d["dish_name"],
            "composite_score": d["composite_score"],
            "volume_score": d["scores"]["volume"],
            "reason": "综合品质优秀但曝光不足，营销推广潜力大",
            "suggestion": "建议列为推荐菜/重点陈列，结合社媒推广",
        }
        for d in dishes_with_scores
        if d["composite_score"] > 0.80 and d["scores"]["volume"] < 0.40
    ]

    # 3. 价格洼地：销量好（volume > 0.7）但毛利因子低（margin < 0.5）
    price_depression = [
        {
            "dish_id": d["dish_id"],
            "dish_name": d["dish_name"],
            "volume_score": d["scores"]["volume"],
            "margin_score": d["scores"]["margin"],
            "price_fen": d["price_fen"],
            "reason": f"销量强劲（{d['scores']['volume']:.0%}），但毛利偏低（{d['scores']['margin']:.0%}），存在明显定价空间",
            "suggestion": f"建议尝试调价至 ¥{(d['price_fen'] * 1.15 / 100):.0f}（+15%），预计影响销量 <8%",
        }
        for d in dishes_with_scores
        if d["scores"]["volume"] > 0.70 and d["scores"]["margin"] < 0.50
    ]

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "report_date": str(date.today()),
            "attention_needed": attention_needed,
            "worth_promoting": worth_promoting,
            "price_depression": price_depression,
            "summary": {
                "total_dishes": len(MOCK_DISHES_RANKING),
                "healthy_count": len([d for d in dishes_with_scores if d["composite_score"] >= 0.60]),
                "warning_count": len([d for d in dishes_with_scores if 0.30 <= d["composite_score"] < 0.60]),
                "critical_count": len(attention_needed),
            },
        },
    }


def _build_attention_reason(dish: dict) -> str:
    s = dish["scores"]
    issues = []
    if s["volume"] < 0.25:
        issues.append("销量极低")
    if s["margin"] < 0.40:
        issues.append("毛利偏低")
    if s["satisfaction"] < 0.70:
        issues.append("满意度差")
    if s["trend"] < 0.25:
        issues.append("持续下滑")
    return "、".join(issues) if issues else "综合评分过低"
