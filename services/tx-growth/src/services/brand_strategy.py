"""品牌策略引擎 — 把品牌定位变成系统可调用的策略资产

将品牌调性、目标客群、价格带、禁忌用语等转化为结构化策略卡，
供内容引擎、优惠引擎、渠道引擎消费。

金额单位：分(fen)
"""
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


# ---------------------------------------------------------------------------
# 内存存储（生产环境替换为 PostgreSQL + RLS）
# ---------------------------------------------------------------------------

_brand_strategies: dict[str, dict] = {}
_city_strategies: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# BrandStrategyService
# ---------------------------------------------------------------------------

class BrandStrategyService:
    """品牌策略引擎 — 把品牌定位变成系统可调用的策略资产"""

    def create_brand_strategy(
        self,
        brand_id: str,
        positioning: str,
        tone: str,
        target_audience: list[str],
        price_range: dict,
        signature_dishes: list[dict],
        seasonal_plans: list[dict],
        promo_boundaries: dict,
        forbidden_expressions: list[str],
    ) -> dict:
        """创建品牌策略

        Args:
            brand_id: 品牌ID
            positioning: 品牌定位（如"社区家庭中餐领导者"）
            tone: 品牌调性（如"温暖、亲切、有品质感"）
            target_audience: 目标客群列表（如["家庭聚餐", "商务宴请"]）
            price_range: 价格带 {"min_fen": 5000, "max_fen": 15000, "avg_fen": 8000}
            signature_dishes: 招牌菜列表 [{"name": "剁椒鱼头", "price_fen": 12800, "story": "..."}]
            seasonal_plans: 季节计划 [{"season": "spring", "theme": "...", "dishes": [...]}]
            promo_boundaries: 促销边界 {"max_discount_pct": 30, "margin_floor_pct": 45}
            forbidden_expressions: 禁用表达 ["最低价", "全网最便宜", "免费送"]
        """
        now = datetime.now(timezone.utc).isoformat()
        strategy = {
            "brand_id": brand_id,
            "positioning": positioning,
            "tone": tone,
            "target_audience": target_audience,
            "price_range": price_range,
            "signature_dishes": signature_dishes,
            "seasonal_plans": seasonal_plans,
            "promo_boundaries": promo_boundaries,
            "forbidden_expressions": forbidden_expressions,
            "created_at": now,
            "updated_at": now,
        }
        _brand_strategies[brand_id] = strategy
        return strategy

    def get_brand_strategy(self, brand_id: str) -> dict:
        """获取品牌策略"""
        strategy = _brand_strategies.get(brand_id)
        if not strategy:
            return {"error": f"品牌策略不存在: {brand_id}"}
        return strategy

    def update_brand_strategy(self, brand_id: str, updates: dict) -> dict:
        """更新品牌策略（部分更新）"""
        strategy = _brand_strategies.get(brand_id)
        if not strategy:
            return {"error": f"品牌策略不存在: {brand_id}"}

        allowed_fields = {
            "positioning", "tone", "target_audience", "price_range",
            "signature_dishes", "seasonal_plans", "promo_boundaries",
            "forbidden_expressions",
        }
        for key, value in updates.items():
            if key in allowed_fields:
                strategy[key] = value

        strategy["updated_at"] = datetime.now(timezone.utc).isoformat()
        _brand_strategies[brand_id] = strategy
        return strategy

    def create_city_strategy(
        self,
        brand_id: str,
        city: str,
        district_strategies: list[dict],
    ) -> dict:
        """创建城市级策略

        Args:
            brand_id: 品牌ID
            city: 城市名称
            district_strategies: 区域策略列表
                [{"district": "岳麓区", "competitor_density": "high",
                  "price_adjustment_pct": -5, "focus_segments": ["高校学生", "家庭"]}]
        """
        strategy_id = f"{brand_id}_{city}"
        now = datetime.now(timezone.utc).isoformat()
        city_strategy = {
            "strategy_id": strategy_id,
            "brand_id": brand_id,
            "city": city,
            "district_strategies": district_strategies,
            "created_at": now,
            "updated_at": now,
        }
        _city_strategies[strategy_id] = city_strategy
        return city_strategy

    def get_seasonal_calendar(self, brand_id: str) -> list[dict]:
        """获取品牌季节日历"""
        strategy = _brand_strategies.get(brand_id)
        if not strategy:
            return []

        calendar: list[dict] = []
        for plan in strategy.get("seasonal_plans", []):
            calendar.append({
                "brand_id": brand_id,
                "season": plan.get("season", ""),
                "theme": plan.get("theme", ""),
                "dishes": plan.get("dishes", []),
                "start_date": plan.get("start_date", ""),
                "end_date": plan.get("end_date", ""),
                "marketing_focus": plan.get("marketing_focus", ""),
            })
        return calendar

    def validate_content_against_brand(self, brand_id: str, content_text: str) -> dict:
        """校验内容是否符合品牌策略

        检查：禁用表达、品牌调性匹配度、价格带一致性
        """
        strategy = _brand_strategies.get(brand_id)
        if not strategy:
            return {"valid": False, "errors": [f"品牌策略不存在: {brand_id}"]}

        errors: list[str] = []
        warnings: list[str] = []

        # 检查禁用表达
        forbidden = strategy.get("forbidden_expressions", [])
        for expr in forbidden:
            if expr in content_text:
                errors.append(f"包含禁用表达「{expr}」")

        # 检查调性关键词（简化：检查是否包含负面调性词汇）
        tone = strategy.get("tone", "")
        negative_tone_words = ["低价", "便宜", "清仓", "甩卖", "白送", "跳楼价"]
        if "品质" in tone or "高端" in tone:
            for word in negative_tone_words:
                if word in content_text:
                    warnings.append(f"品牌调性为「{tone}」，不宜使用「{word}」")

        # 检查是否提到了价格且超出价格带
        price_range = strategy.get("price_range", {})
        price_pattern = r"(\d+)\s*元"
        matches = re.findall(price_pattern, content_text)
        for price_str in matches:
            price_fen = int(price_str) * 100
            max_fen = price_range.get("max_fen", 999999)
            if price_fen > max_fen * 2:
                warnings.append(f"提及价格 {price_str}元 超出品牌价格带上限")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "checked_rules": {
                "forbidden_expressions": len(forbidden),
                "tone_check": True,
                "price_range_check": True,
            },
        }

    def generate_strategy_card(self, brand_id: str) -> dict:
        """生成结构化策略卡，供其他引擎调用

        返回一张精简的策略摘要卡，包含其他引擎决策所需的关键信息。
        """
        strategy = _brand_strategies.get(brand_id)
        if not strategy:
            return {"error": f"品牌策略不存在: {brand_id}"}

        promo = strategy.get("promo_boundaries", {})
        dishes = strategy.get("signature_dishes", [])
        price_range = strategy.get("price_range", {})

        return {
            "brand_id": brand_id,
            "positioning": strategy.get("positioning", ""),
            "tone": strategy.get("tone", ""),
            "target_audience": strategy.get("target_audience", []),
            "price_range_yuan": {
                "min": price_range.get("min_fen", 0) / 100,
                "max": price_range.get("max_fen", 0) / 100,
                "avg": price_range.get("avg_fen", 0) / 100,
            },
            "top_dishes": [d.get("name", "") for d in dishes[:5]],
            "max_discount_pct": promo.get("max_discount_pct", 0),
            "margin_floor_pct": promo.get("margin_floor_pct", 0),
            "forbidden_expressions": strategy.get("forbidden_expressions", []),
            "current_season": _get_current_season_plan(strategy),
        }


def _get_current_season_plan(strategy: dict) -> Optional[dict]:
    """获取当前季节的营销计划"""
    now = datetime.now(timezone.utc)
    month = now.month
    season_map = {
        "spring": [3, 4, 5],
        "summer": [6, 7, 8],
        "autumn": [9, 10, 11],
        "winter": [12, 1, 2],
    }
    current_season = ""
    for season, months in season_map.items():
        if month in months:
            current_season = season
            break

    for plan in strategy.get("seasonal_plans", []):
        if plan.get("season") == current_season:
            return {
                "season": current_season,
                "theme": plan.get("theme", ""),
                "focus_dishes": plan.get("dishes", []),
            }
    return None
