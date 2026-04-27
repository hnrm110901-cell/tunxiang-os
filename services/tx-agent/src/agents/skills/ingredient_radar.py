"""新原料雷达 Agent — P1 | 云端

新原料发现、原料趋势分析、原料替代建议、供应商对比、原料成本预测、原料合规检查。
"""

from typing import Any

from ..base import AgentResult, SkillAgent

# 原料品类
INGREDIENT_CATEGORIES = ["肉类", "海鲜", "蔬菜", "调味料", "粮油", "乳制品", "饮品原料", "预制半成品"]

# 合规标准
COMPLIANCE_STANDARDS = ["GB 2762 食品污染物", "GB 2760 食品添加剂", "GB 7718 预包装食品标签", "SC生产许可"]


class IngredientRadarAgent(SkillAgent):
    agent_id = "ingredient_radar"
    agent_name = "新原料雷达"
    description = "新原料发现、趋势分析、替代建议、供应商对比、成本预测、合规检查"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "discover_new_ingredients",
            "analyze_ingredient_trends",
            "suggest_substitutes",
            "compare_suppliers",
            "predict_ingredient_cost",
            "check_compliance",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "discover_new_ingredients": self._discover_new,
            "analyze_ingredient_trends": self._analyze_trends,
            "suggest_substitutes": self._suggest_substitutes,
            "compare_suppliers": self._compare_suppliers,
            "predict_ingredient_cost": self._predict_cost,
            "check_compliance": self._check_compliance,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _discover_new(self, params: dict) -> AgentResult:
        """新原料发现"""
        market_data = params.get("market_data", [])
        current_ingredients = params.get("current_ingredients", [])

        discoveries = []
        for item in market_data:
            name = item.get("name", "")
            if name in current_ingredients:
                continue

            discoveries.append(
                {
                    "ingredient_name": name,
                    "category": item.get("category", "其他"),
                    "origin": item.get("origin", ""),
                    "market_popularity": item.get("popularity_score", 0),
                    "price_per_kg_yuan": round(item.get("price_per_kg_fen", 0) / 100, 2),
                    "seasonality": item.get("season", "全年"),
                    "potential_dishes": item.get("potential_dishes", []),
                    "health_benefits": item.get("health_benefits", []),
                    "novelty_score": item.get("novelty_score", 0),
                }
            )

        discoveries.sort(key=lambda x: x["novelty_score"], reverse=True)

        return AgentResult(
            success=True,
            action="discover_new_ingredients",
            data={
                "discoveries": discoveries[:15],
                "total_scanned": len(market_data),
                "new_count": len(discoveries),
                "top_recommendation": discoveries[0]["ingredient_name"] if discoveries else "无",
            },
            reasoning=f"扫描 {len(market_data)} 种原料，发现 {len(discoveries)} 种新原料机会",
            confidence=0.7,
        )

    async def _analyze_trends(self, params: dict) -> AgentResult:
        """原料趋势分析"""
        ingredients = params.get("ingredients", [])

        trends = []
        for ing in ingredients:
            name = ing.get("name", "")
            price_history = ing.get("price_history", [])
            demand_trend = ing.get("demand_trend", "持平")

            if len(price_history) >= 2:
                price_change = round((price_history[-1] - price_history[0]) / max(1, price_history[0]) * 100, 1)
                volatility = (
                    round(max(price_history) / max(1, min(p for p in price_history if p > 0)) - 1, 2) * 100
                    if price_history
                    else 0
                )
            else:
                price_change = 0
                volatility = 0

            trends.append(
                {
                    "ingredient": name,
                    "category": ing.get("category", ""),
                    "price_change_pct": price_change,
                    "price_volatility_pct": round(volatility, 1),
                    "demand_trend": demand_trend,
                    "supply_status": ing.get("supply_status", "正常"),
                    "risk_level": "高"
                    if abs(price_change) > 20 or demand_trend == "短缺"
                    else "中"
                    if abs(price_change) > 10
                    else "低",
                    "action": "寻找替代/锁价"
                    if price_change > 20
                    else "增加库存"
                    if price_change < -10
                    else "维持现状",
                }
            )

        trends.sort(key=lambda x: abs(x["price_change_pct"]), reverse=True)

        return AgentResult(
            success=True,
            action="analyze_ingredient_trends",
            data={
                "trends": trends[:20],
                "rising_count": sum(1 for t in trends if t["price_change_pct"] > 5),
                "falling_count": sum(1 for t in trends if t["price_change_pct"] < -5),
                "high_risk_count": sum(1 for t in trends if t["risk_level"] == "高"),
            },
            reasoning=f"原料趋势: 涨价 {sum(1 for t in trends if t['price_change_pct'] > 5)} 种，"
            f"降价 {sum(1 for t in trends if t['price_change_pct'] < -5)} 种，"
            f"高风险 {sum(1 for t in trends if t['risk_level'] == '高')} 种",
            confidence=0.75,
        )

    async def _suggest_substitutes(self, params: dict) -> AgentResult:
        """原料替代建议"""
        target_ingredient = params.get("target_ingredient", "")
        reason = params.get("reason", "成本优化")
        current_price_fen = params.get("current_price_per_kg_fen", 0)
        candidates = params.get("candidates", [])

        substitutes = []
        for c in candidates:
            price = c.get("price_per_kg_fen", 0)
            cost_saving = round((current_price_fen - price) / max(1, current_price_fen) * 100, 1)

            substitutes.append(
                {
                    "ingredient": c.get("name", ""),
                    "price_per_kg_yuan": round(price / 100, 2),
                    "cost_saving_pct": cost_saving,
                    "taste_similarity_pct": c.get("taste_similarity", 0),
                    "nutrition_similarity_pct": c.get("nutrition_similarity", 0),
                    "availability": c.get("availability", "充足"),
                    "overall_score": round(
                        cost_saving * 0.3 + c.get("taste_similarity", 0) * 0.4 + c.get("nutrition_similarity", 0) * 0.3,
                        1,
                    ),
                    "notes": c.get("notes", ""),
                }
            )

        substitutes.sort(key=lambda x: x["overall_score"], reverse=True)

        return AgentResult(
            success=True,
            action="suggest_substitutes",
            data={
                "target_ingredient": target_ingredient,
                "reason": reason,
                "current_price_yuan": round(current_price_fen / 100, 2),
                "substitutes": substitutes[:5],
                "best_substitute": substitutes[0]["ingredient"] if substitutes else "无",
            },
            reasoning=f"为「{target_ingredient}」找到 {len(substitutes)} 种替代方案，"
            f"最佳: {substitutes[0]['ingredient'] if substitutes else '无'}",
            confidence=0.7,
        )

    async def _compare_suppliers(self, params: dict) -> AgentResult:
        """供应商对比"""
        ingredient = params.get("ingredient", "")
        suppliers = params.get("suppliers", [])

        compared = []
        for s in suppliers:
            quality_score = s.get("quality_score", 0)
            price_fen = s.get("price_per_kg_fen", 0)
            delivery_days = s.get("avg_delivery_days", 0)
            reliability = s.get("on_time_rate_pct", 0)

            # 综合评分
            overall = round(
                quality_score * 0.3
                + (100 - min(100, price_fen / 100)) * 0.25
                + reliability * 0.25
                + max(0, 100 - delivery_days * 10) * 0.2,
                1,
            )

            compared.append(
                {
                    "supplier_name": s.get("name", ""),
                    "price_per_kg_yuan": round(price_fen / 100, 2),
                    "quality_score": quality_score,
                    "avg_delivery_days": delivery_days,
                    "on_time_rate_pct": reliability,
                    "min_order_kg": s.get("min_order_kg", 0),
                    "payment_terms": s.get("payment_terms", "月结30天"),
                    "overall_score": overall,
                }
            )

        compared.sort(key=lambda x: x["overall_score"], reverse=True)

        return AgentResult(
            success=True,
            action="compare_suppliers",
            data={
                "ingredient": ingredient,
                "suppliers": compared,
                "recommended": compared[0]["supplier_name"] if compared else "无",
                "total_compared": len(compared),
            },
            reasoning=f"对比 {len(compared)} 家「{ingredient}」供应商，推荐 {compared[0]['supplier_name'] if compared else '无'}",
            confidence=0.8,
        )

    async def _predict_cost(self, params: dict) -> AgentResult:
        """原料成本预测"""
        ingredient = params.get("ingredient", "")
        price_history = params.get("price_history_fen", [])
        season = params.get("upcoming_season", "")
        supply_outlook = params.get("supply_outlook", "正常")

        if len(price_history) < 2:
            return AgentResult(success=False, action="predict_ingredient_cost", error="历史数据不足")

        # 简单趋势预测
        recent_avg = sum(price_history[-3:]) / min(3, len(price_history))
        older_avg = sum(price_history[:3]) / min(3, len(price_history))
        trend_pct = round((recent_avg - older_avg) / max(1, older_avg) * 100, 1)

        # 季节因子
        season_factor = 1.0
        if supply_outlook == "紧张":
            season_factor = 1.15
        elif supply_outlook == "充裕":
            season_factor = 0.9

        predicted_fen = int(recent_avg * (1 + trend_pct / 200) * season_factor)

        return AgentResult(
            success=True,
            action="predict_ingredient_cost",
            data={
                "ingredient": ingredient,
                "current_price_yuan": round(price_history[-1] / 100, 2),
                "predicted_price_yuan": round(predicted_fen / 100, 2),
                "change_pct": round((predicted_fen - price_history[-1]) / max(1, price_history[-1]) * 100, 1),
                "trend_direction": "上涨"
                if predicted_fen > price_history[-1] * 1.02
                else "下降"
                if predicted_fen < price_history[-1] * 0.98
                else "持平",
                "supply_outlook": supply_outlook,
                "season": season,
                "confidence_range": {
                    "low_yuan": round(predicted_fen * 0.9 / 100, 2),
                    "high_yuan": round(predicted_fen * 1.1 / 100, 2),
                },
                "recommendation": "提前锁价/囤货"
                if predicted_fen > price_history[-1] * 1.1
                else "等待降价再采购"
                if predicted_fen < price_history[-1] * 0.9
                else "正常采购",
            },
            reasoning=f"「{ingredient}」预测价格 ¥{predicted_fen / 100:.2f}/kg，"
            f"{'上涨' if predicted_fen > price_history[-1] else '下降'} "
            f"{abs(round((predicted_fen - price_history[-1]) / max(1, price_history[-1]) * 100, 1))}%",
            confidence=0.65,
        )

    async def _check_compliance(self, params: dict) -> AgentResult:
        """原料合规检查"""
        ingredient = params.get("ingredient", "")
        certifications = params.get("certifications", [])
        additives = params.get("additives", [])
        origin = params.get("origin", "")
        shelf_life_days = params.get("shelf_life_days", 0)

        issues = []
        passed = []

        # SC许可检查
        if "SC" in certifications or "QS" in certifications:
            passed.append("生产许可证: 通过")
        else:
            issues.append({"check": "生产许可证", "status": "缺失", "severity": "high"})

        # 添加剂检查
        banned_additives = ["苏丹红", "三聚氰胺", "吊白块", "工业明胶"]
        for additive in additives:
            if additive in banned_additives:
                issues.append({"check": f"违禁添加剂: {additive}", "status": "不合规", "severity": "critical"})

        if not any(a in banned_additives for a in additives):
            passed.append("添加剂检查: 通过")

        # 保质期检查
        if shelf_life_days > 0:
            passed.append(f"保质期: {shelf_life_days}天")
        else:
            issues.append({"check": "保质期", "status": "未标注", "severity": "medium"})

        # 产地检查
        if origin:
            passed.append(f"产地: {origin}")
        else:
            issues.append({"check": "产地信息", "status": "缺失", "severity": "medium"})

        all_passed = len(issues) == 0
        has_critical = any(i["severity"] == "critical" for i in issues)

        return AgentResult(
            success=True,
            action="check_compliance",
            data={
                "ingredient": ingredient,
                "overall_status": "不合规" if has_critical else "有风险" if issues else "合规",
                "issues": issues,
                "passed_checks": passed,
                "total_checks": len(issues) + len(passed),
                "critical_issues": sum(1 for i in issues if i["severity"] == "critical"),
                "applicable_standards": COMPLIANCE_STANDARDS,
            },
            reasoning=f"「{ingredient}」合规检查: {'不合规' if has_critical else '有风险' if issues else '合规'}，"
            f"问题 {len(issues)} 项",
            confidence=0.85,
        )
