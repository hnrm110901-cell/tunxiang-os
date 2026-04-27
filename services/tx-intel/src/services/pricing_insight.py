"""价格带与套餐洞察引擎

分析品类价格带分布、竞对定价、套餐趋势，
给出定价建议和价值感知差距分析。

所有金额单位：分（fen）。
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()


# ─── 常量 ───

PRICE_BANDS = {
    "economy": {"label": "经济型", "range_fen": (0, 5000)},
    "mid_range": {"label": "中端", "range_fen": (5000, 8000)},
    "mid_premium": {"label": "中高端", "range_fen": (8000, 12000)},
    "premium": {"label": "高端", "range_fen": (12000, 20000)},
    "luxury": {"label": "奢华", "range_fen": (20000, 999999)},
}

# ─── 市场价格数据（模拟） ───

_MARKET_PRICE_DATA: dict[str, dict] = {
    "湘菜": {
        "长沙": {
            "economy": {"market_share_pct": 25, "avg_spend_fen": 3800, "brands": ["小炒之家", "湘味轩"]},
            "mid_range": {"market_share_pct": 45, "avg_spend_fen": 6500, "brands": ["费大厨", "望湘园", "屯象品牌"]},
            "mid_premium": {"market_share_pct": 20, "avg_spend_fen": 9500, "brands": ["炊烟时代", "火宫殿"]},
            "premium": {"market_share_pct": 8, "avg_spend_fen": 15000, "brands": ["徐记海鲜"]},
            "luxury": {"market_share_pct": 2, "avg_spend_fen": 25000, "brands": ["高端私厨"]},
        },
        "深圳": {
            "economy": {"market_share_pct": 15, "avg_spend_fen": 4500, "brands": ["各种快餐湘菜"]},
            "mid_range": {"market_share_pct": 40, "avg_spend_fen": 7500, "brands": ["费大厨", "屯象品牌"]},
            "mid_premium": {"market_share_pct": 30, "avg_spend_fen": 10500, "brands": ["望湘园", "炊烟时代"]},
            "premium": {"market_share_pct": 12, "avg_spend_fen": 16000, "brands": ["徐记海鲜"]},
            "luxury": {"market_share_pct": 3, "avg_spend_fen": 28000, "brands": ["高端湘菜私厨"]},
        },
    },
    "火锅": {
        "长沙": {
            "economy": {"market_share_pct": 20, "avg_spend_fen": 4000, "brands": ["自助小火锅"]},
            "mid_range": {"market_share_pct": 35, "avg_spend_fen": 7000, "brands": ["呷哺呷哺"]},
            "mid_premium": {"market_share_pct": 25, "avg_spend_fen": 10000, "brands": ["巴奴"]},
            "premium": {"market_share_pct": 15, "avg_spend_fen": 13500, "brands": ["海底捞"]},
            "luxury": {"market_share_pct": 5, "avg_spend_fen": 22000, "brands": ["高端火锅"]},
        },
    },
}

# ─── 竞对定价数据 ───

_COMPETITOR_PRICING: dict[str, dict] = {
    "费大厨辣椒炒肉": {
        "辣椒炒肉": 5800,
        "小炒黄牛肉": 6800,
        "剁椒鱼头": 8800,
        "酸汤肥牛": 5800,
        "午市套餐": 3900,
        "双人套餐": 12800,
    },
    "望湘园": {
        "辣椒炒肉": 6200,
        "小炒黄牛肉": 7200,
        "剁椒鱼头": 9800,
        "红烧肉": 5800,
        "午市套餐": 4500,
        "双人套餐": 15800,
    },
    "海底捞": {
        "经典锅底": 7800,
        "牛肉拼盘": 6800,
        "虾滑": 4800,
        "午市套餐": 5800,
        "双人套餐": 16800,
    },
    "太二酸菜鱼": {
        "酸菜鱼(标准)": 6800,
        "酸菜鱼(大份)": 8800,
        "午市套餐": 3990,
        "双人套餐": 11800,
    },
}

# ─── 我方定价 ───

_OUR_PRICING: dict[str, int] = {
    "辣椒炒肉": 5500,
    "小炒黄牛肉": 6500,
    "剁椒鱼头": 8500,
    "酸汤肥牛": 5200,
    "口味虾": 8800,
    "腊味合蒸": 5800,
    "午市套餐": 3500,
    "双人套餐": 11800,
    "家庭套餐": 19800,
}


class PricingInsightService:
    """价格带与套餐洞察引擎"""

    def __init__(self) -> None:
        self._price_adjustments: list[dict] = []
        self._spend_history: list[dict] = self._generate_spend_history()

    def _generate_spend_history(self) -> list[dict]:
        """生成模拟消费趋势数据"""
        history = []
        now = datetime.now(timezone.utc)
        base_spend = 7200
        for i in range(90, 0, -1):
            date = now - timedelta(days=i)
            # 模拟波动
            variation = hash(str(i)) % 1000 - 500
            # 周末略高
            weekend_boost = 800 if date.weekday() >= 5 else 0
            spend = base_spend + variation + weekend_boost + (90 - i) * 5
            history.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "avg_spend_fen": max(5000, spend),
                    "order_count": 150 + (hash(str(i + 1)) % 50),
                    "set_meal_pct": 35 + (hash(str(i + 2)) % 15),
                }
            )
        return history

    # ─── 价格带分析 ───

    def analyze_price_bands(self, category: str, city: Optional[str] = None) -> dict:
        """分析品类价格带分布"""
        cat_data = _MARKET_PRICE_DATA.get(category)
        if not cat_data:
            return {
                "category": category,
                "status": "no_data",
                "message": f"暂无{category}品类的价格带数据",
            }

        if city and city in cat_data:
            city_data = {city: cat_data[city]}
        elif city:
            return {
                "category": category,
                "city": city,
                "status": "no_data",
                "message": f"暂无{city}的{category}价格带数据",
            }
        else:
            city_data = cat_data

        result_cities = {}
        for c, bands in city_data.items():
            band_list = []
            for band_key, band_info in bands.items():
                band_meta = PRICE_BANDS.get(band_key, {})
                band_list.append(
                    {
                        "band": band_key,
                        "label": band_meta.get("label", band_key),
                        "price_range_fen": band_meta.get("range_fen", (0, 0)),
                        "market_share_pct": band_info["market_share_pct"],
                        "avg_spend_fen": band_info["avg_spend_fen"],
                        "key_brands": band_info["brands"],
                    }
                )
            result_cities[c] = band_list

        return {
            "category": category,
            "cities": result_cities,
            "our_position": {
                "band": "mid_range",
                "avg_spend_fen": 7500,
                "insight": f"我方品牌在{category}品类中定位中端价格带",
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ─── 竞对定价对比 ───

    def compare_competitor_pricing(
        self,
        competitor_ids: list[str],
        dish_category: Optional[str] = None,
    ) -> dict:
        """竞对定价对比（使用竞对名称作为 key）"""
        # 简化：直接用名称匹配
        comparison: dict[str, dict] = {}

        for comp_name, prices in _COMPETITOR_PRICING.items():
            comparison[comp_name] = {}
            for dish, price_fen in prices.items():
                our_price = _OUR_PRICING.get(dish)
                if our_price is not None:
                    diff = price_fen - our_price
                    comparison[comp_name][dish] = {
                        "competitor_price_fen": price_fen,
                        "our_price_fen": our_price,
                        "diff_fen": diff,
                        "diff_pct": round(diff / our_price * 100, 1),
                        "position": "我方更低" if diff > 0 else ("我方更高" if diff < 0 else "持平"),
                    }
                else:
                    comparison[comp_name][dish] = {
                        "competitor_price_fen": price_fen,
                        "our_price_fen": None,
                        "note": "我方无对应菜品",
                    }

        return {
            "our_pricing": _OUR_PRICING,
            "competitor_comparison": comparison,
            "summary": self._pricing_summary(comparison),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _pricing_summary(self, comparison: dict) -> str:
        """生成定价对比摘要"""
        lower_count = 0
        higher_count = 0
        for comp_data in comparison.values():
            for dish_data in comp_data.values():
                diff = dish_data.get("diff_fen")
                if diff is not None and isinstance(diff, (int, float)):
                    if diff > 0:
                        lower_count += 1
                    elif diff < 0:
                        higher_count += 1
        total = lower_count + higher_count
        if total == 0:
            return "无可比价格数据"
        return (
            f"在{total}个可比菜品中，我方定价较低的有{lower_count}个，"
            f"较高的有{higher_count}个。整体定价策略偏"
            f"{'亲民' if lower_count > higher_count else '高端'}。"
        )

    # ─── 套餐趋势 ───

    def analyze_set_meal_trends(self, city: Optional[str] = None) -> list[dict]:
        """分析套餐趋势"""
        trends = [
            {
                "trend_name": "一人食套餐",
                "heat_score": 0.90,
                "trend": "rising",
                "typical_price_fen": (2500, 4500),
                "target_scenario": "工作日午市单人用餐",
                "description": "单人份主菜+米饭+饮料/汤，工作日午市刚需，复购率高",
                "our_status": "已有（午市套餐35元）",
                "recommendation": "建议丰富一人食套餐选择，增加至3-5个SKU",
            },
            {
                "trend_name": "闺蜜/好友双人套餐",
                "heat_score": 0.82,
                "trend": "rising",
                "typical_price_fen": (9800, 15800),
                "target_scenario": "朋友聚餐",
                "description": "2荤1素1汤+主食，拍照友好，适合社交分享",
                "our_status": "已有（双人套餐118元）",
                "recommendation": "建议增加'颜值担当'菜品，强化社交属性",
            },
            {
                "trend_name": "家庭亲子套餐",
                "heat_score": 0.85,
                "trend": "rising",
                "typical_price_fen": (16800, 25800),
                "target_scenario": "周末家庭聚餐",
                "description": "3-4人份，含儿童友好菜品，部分品牌附赠儿童小玩具",
                "our_status": "已有（家庭套餐198元）",
                "recommendation": "建议增加儿童友好菜品，考虑赠送小礼物提升体验",
            },
            {
                "trend_name": "商务宴请套餐",
                "heat_score": 0.65,
                "trend": "stable",
                "typical_price_fen": (28800, 58800),
                "target_scenario": "商务宴请",
                "description": "6-8人份，含招牌菜和高端食材，配专属服务",
                "our_status": "暂无",
                "recommendation": "建议开发商务宴请套餐，满足B端客户需求",
            },
            {
                "trend_name": "减脂轻食套餐",
                "heat_score": 0.72,
                "trend": "emerging",
                "typical_price_fen": (2800, 4800),
                "target_scenario": "健身人群午餐",
                "description": "低卡路里、高蛋白，标注营养信息，配沙拉或清汤",
                "our_status": "暂无",
                "recommendation": "建议试点推出，湘菜少油少盐版本有差异化空间",
            },
        ]
        return trends

    # ─── 定价建议 ───

    def suggest_price_adjustment(self, dish_id: str, current_price_fen: int) -> dict:
        """给出定价建议"""
        # 模拟分析逻辑
        competitor_prices: list[int] = []
        for comp_prices in _COMPETITOR_PRICING.values():
            if dish_id in comp_prices:
                competitor_prices.append(comp_prices[dish_id])

        if not competitor_prices:
            return {
                "dish_id": dish_id,
                "current_price_fen": current_price_fen,
                "status": "no_benchmark",
                "message": "无竞对价格基准数据，建议基于成本和毛利目标定价",
            }

        avg_competitor = sum(competitor_prices) / len(competitor_prices)
        min_competitor = min(competitor_prices)
        max_competitor = max(competitor_prices)

        diff_pct = (current_price_fen - avg_competitor) / avg_competitor * 100

        if diff_pct < -15:
            suggestion = "价格明显低于竞对均价，有提价空间"
            suggested_price = int(avg_competitor * 0.95)
            reason = "当前价格低于竞对均价15%以上，建议适度上调至竞对均价95%水平"
        elif diff_pct > 15:
            suggestion = "价格明显高于竞对均价，需关注性价比感知"
            suggested_price = int(avg_competitor * 1.05)
            reason = "当前价格高于竞对均价15%以上，需确保品质感支撑溢价"
        else:
            suggestion = "价格在竞对合理区间内"
            suggested_price = current_price_fen
            reason = "当前价格与竞对均价差异在15%以内，定价合理"

        return {
            "dish_id": dish_id,
            "current_price_fen": current_price_fen,
            "competitor_avg_fen": int(avg_competitor),
            "competitor_min_fen": min_competitor,
            "competitor_max_fen": max_competitor,
            "diff_vs_avg_pct": round(diff_pct, 1),
            "suggestion": suggestion,
            "suggested_price_fen": suggested_price,
            "reason": reason,
        }

    # ─── 客单价趋势 ───

    def analyze_customer_spend_trend(self, days: int = 90) -> dict:
        """分析客单价趋势"""
        data = self._spend_history[-days:]
        if not data:
            return {"status": "no_data", "message": "无消费数据"}

        avg_spend = sum(d["avg_spend_fen"] for d in data) / len(data)
        first_half = data[: len(data) // 2]
        second_half = data[len(data) // 2 :]
        avg_first = sum(d["avg_spend_fen"] for d in first_half) / len(first_half) if first_half else 0
        avg_second = sum(d["avg_spend_fen"] for d in second_half) / len(second_half) if second_half else 0

        trend = (
            "rising" if avg_second > avg_first * 1.02 else ("declining" if avg_second < avg_first * 0.98 else "stable")
        )

        avg_set_meal_pct = sum(d["set_meal_pct"] for d in data) / len(data)

        return {
            "period_days": days,
            "avg_spend_fen": int(avg_spend),
            "trend": trend,
            "first_half_avg_fen": int(avg_first),
            "second_half_avg_fen": int(avg_second),
            "change_pct": round((avg_second - avg_first) / avg_first * 100, 1) if avg_first else 0,
            "avg_set_meal_pct": round(avg_set_meal_pct, 1),
            "data_points": len(data),
            "insight": self._spend_insight(trend, int(avg_spend), round(avg_set_meal_pct, 1)),
        }

    def _spend_insight(self, trend: str, avg_spend: int, set_meal_pct: float) -> str:
        trend_cn = {"rising": "上升", "declining": "下降", "stable": "平稳"}.get(trend, trend)
        return f"近期客单价{trend_cn}，均值¥{avg_spend / 100:.0f}。套餐占比{set_meal_pct:.0f}%。" + (
            "建议关注消费降级风险。"
            if trend == "declining"
            else "消费升级趋势明显，可适度丰富高客单产品。"
            if trend == "rising"
            else "消费稳定，维持当前策略。"
        )

    # ─── 价值感知差距 ───

    def detect_value_perception_gap(self) -> list[dict]:
        """检测价值感知与定位不匹配的情况"""
        gaps = [
            {
                "dish": "剁椒鱼头",
                "our_price_fen": 8500,
                "perceived_value": "high",
                "actual_position": "mid_premium",
                "gap_type": "underpriced",
                "description": "剁椒鱼头作为招牌菜口碑极好，顾客感知价值高于当前定价",
                "recommendation": "建议适度提价至¥92-98区间，或推出升级版（大份/精品鱼头）",
            },
            {
                "dish": "午市套餐",
                "our_price_fen": 3500,
                "perceived_value": "medium",
                "actual_position": "economy",
                "gap_type": "quality_concern",
                "description": "午市套餐价格偏低，部分顾客反馈团购版品质下降",
                "recommendation": "建议保持价格但提升套餐品质一致性，或推出35/45/55三档选择",
            },
            {
                "dish": "口味虾",
                "our_price_fen": 8800,
                "perceived_value": "medium",
                "actual_position": "mid_premium",
                "gap_type": "overpriced",
                "description": "季节性菜品，非旺季性价比感知较低，竞对价格更有竞争力",
                "recommendation": "建议旺季维持价格，淡季推出限时优惠或搭配套餐",
            },
        ]
        return gaps
