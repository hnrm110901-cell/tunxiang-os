"""菜单优化建议 Agent — P1 | 云端

菜品四象限分析、菜单结构诊断、定价优化、上下架建议、套餐组合优化、菜单AB测试。
"""
from typing import Any

from ..base import AgentResult, SkillAgent

# 四象限定义
QUADRANTS = {
    "star": {"name": "明星菜品", "desc": "高销量高毛利", "action": "主推维护"},
    "cash_cow": {"name": "利润菜品", "desc": "低销量高毛利", "action": "提升曝光"},
    "traffic": {"name": "引流菜品", "desc": "高销量低毛利", "action": "适当提价或优化成本"},
    "dog": {"name": "淘汰候选", "desc": "低销量低毛利", "action": "考虑下架或改良"},
}


class MenuAdvisorAgent(SkillAgent):
    agent_id = "menu_advisor"
    agent_name = "菜单优化建议"
    description = "菜品四象限分析、菜单结构诊断、定价优化、上下架建议、套餐优化、AB测试"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "analyze_dish_quadrant",
            "diagnose_menu_structure",
            "optimize_pricing",
            "suggest_dish_changes",
            "optimize_combo",
            "design_ab_test",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "analyze_dish_quadrant": self._analyze_quadrant,
            "diagnose_menu_structure": self._diagnose_structure,
            "optimize_pricing": self._optimize_pricing,
            "suggest_dish_changes": self._suggest_changes,
            "optimize_combo": self._optimize_combo,
            "design_ab_test": self._design_ab_test,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _analyze_quadrant(self, params: dict) -> AgentResult:
        """菜品四象限分析"""
        dishes = params.get("dishes", [])
        if not dishes:
            return AgentResult(success=False, action="analyze_dish_quadrant", error="无菜品数据")

        # 计算中位数
        sales = [d.get("monthly_sales", 0) for d in dishes]
        margins = [d.get("margin_pct", 0) for d in dishes]
        sales_median = sorted(sales)[len(sales) // 2]
        margin_median = sorted(margins)[len(margins) // 2]

        quadrant_results = {"star": [], "cash_cow": [], "traffic": [], "dog": []}

        for d in dishes:
            s = d.get("monthly_sales", 0)
            m = d.get("margin_pct", 0)

            if s >= sales_median and m >= margin_median:
                q = "star"
            elif s < sales_median and m >= margin_median:
                q = "cash_cow"
            elif s >= sales_median and m < margin_median:
                q = "traffic"
            else:
                q = "dog"

            quadrant_results[q].append({
                "dish_name": d.get("dish_name", ""),
                "monthly_sales": s,
                "margin_pct": m,
                "revenue_yuan": round(d.get("revenue_fen", 0) / 100, 2),
                "quadrant": q,
                "quadrant_name": QUADRANTS[q]["name"],
                "action": QUADRANTS[q]["action"],
            })

        return AgentResult(
            success=True, action="analyze_dish_quadrant",
            data={
                "quadrants": {k: {"count": len(v), "dishes": v[:10], "info": QUADRANTS[k]}
                             for k, v in quadrant_results.items()},
                "total_dishes": len(dishes),
                "sales_median": sales_median,
                "margin_median": margin_median,
            },
            reasoning=f"四象限分析: 明星{len(quadrant_results['star'])}、利润{len(quadrant_results['cash_cow'])}、"
                      f"引流{len(quadrant_results['traffic'])}、淘汰{len(quadrant_results['dog'])}",
            confidence=0.85,
        )

    async def _diagnose_structure(self, params: dict) -> AgentResult:
        """菜单结构诊断"""
        categories = params.get("categories", [])
        total_dishes = params.get("total_dishes", 0)

        diagnostics = []
        issues = []

        for cat in categories:
            name = cat.get("name", "")
            count = cat.get("dish_count", 0)
            avg_margin = cat.get("avg_margin_pct", 0)
            contribution_pct = cat.get("revenue_contribution_pct", 0)

            pct = round(count / max(1, total_dishes) * 100, 1)
            diagnostics.append({
                "category": name,
                "dish_count": count,
                "share_pct": pct,
                "avg_margin_pct": avg_margin,
                "revenue_contribution_pct": contribution_pct,
                "efficiency": round(contribution_pct / max(0.1, pct), 2),
            })

            if pct > 30:
                issues.append({"category": name, "issue": "品类占比过高", "suggestion": f"精简至{count // 2}道以内"})
            if pct < 5 and contribution_pct < 3:
                issues.append({"category": name, "issue": "品类存在感低", "suggestion": "考虑合并或加强推广"})
            if avg_margin < 50:
                issues.append({"category": name, "issue": "品类毛利偏低", "suggestion": "优化配方或调整定价"})

        # 总体指标
        ideal_count_range = (40, 80) if total_dishes > 30 else (20, 50)
        too_many = total_dishes > ideal_count_range[1]
        too_few = total_dishes < ideal_count_range[0]

        if too_many:
            issues.insert(0, {"category": "整体", "issue": f"菜品总数偏多({total_dishes}道)", "suggestion": f"精简至{ideal_count_range[1]}道以内"})
        if too_few:
            issues.insert(0, {"category": "整体", "issue": f"菜品总数偏少({total_dishes}道)", "suggestion": f"补充至{ideal_count_range[0]}道以上"})

        return AgentResult(
            success=True, action="diagnose_menu_structure",
            data={
                "diagnostics": diagnostics,
                "total_dishes": total_dishes,
                "total_categories": len(categories),
                "issues": issues,
                "health_score": max(0, 100 - len(issues) * 15),
            },
            reasoning=f"菜单诊断: {total_dishes}道菜，{len(categories)}个品类，{len(issues)}个问题",
            confidence=0.8,
        )

    async def _optimize_pricing(self, params: dict) -> AgentResult:
        """定价优化"""
        dishes = params.get("dishes", [])
        target_margin_pct = params.get("target_margin_pct", 65)

        suggestions = []
        for d in dishes:
            current_price_fen = d.get("price_fen", 0)
            cost_fen = d.get("cost_fen", 0)
            current_margin = round((current_price_fen - cost_fen) / max(1, current_price_fen) * 100, 1)
            category_avg_fen = d.get("category_avg_price_fen", current_price_fen)

            optimal_price = int(cost_fen / (1 - target_margin_pct / 100))
            price_change = optimal_price - current_price_fen
            change_pct = round(price_change / max(1, current_price_fen) * 100, 1)

            # 不建议变动幅度超过20%
            if abs(change_pct) > 20:
                optimal_price = int(current_price_fen * (1 + 0.2 * (1 if change_pct > 0 else -1)))
                change_pct = round((optimal_price - current_price_fen) / max(1, current_price_fen) * 100, 1)

            if abs(change_pct) >= 3:
                suggestions.append({
                    "dish_name": d.get("dish_name", ""),
                    "current_price_yuan": round(current_price_fen / 100, 2),
                    "suggested_price_yuan": round(optimal_price / 100, 2),
                    "change_pct": change_pct,
                    "current_margin_pct": current_margin,
                    "target_margin_pct": target_margin_pct,
                    "category_avg_yuan": round(category_avg_fen / 100, 2),
                    "direction": "提价" if change_pct > 0 else "降价",
                    "priority": "高" if abs(change_pct) >= 10 else "中",
                })

        suggestions.sort(key=lambda x: abs(x["change_pct"]), reverse=True)

        return AgentResult(
            success=True, action="optimize_pricing",
            data={
                "suggestions": suggestions[:20],
                "total_adjustments": len(suggestions),
                "increase_count": sum(1 for s in suggestions if s["direction"] == "提价"),
                "decrease_count": sum(1 for s in suggestions if s["direction"] == "降价"),
                "target_margin_pct": target_margin_pct,
            },
            reasoning=f"定价优化: {len(suggestions)} 道菜需调价，提价 {sum(1 for s in suggestions if s['direction'] == '提价')} 道",
            confidence=0.8,
        )

    async def _suggest_changes(self, params: dict) -> AgentResult:
        """上下架建议"""
        dishes = params.get("dishes", [])
        season = params.get("season", "")

        to_add = []
        to_remove = []
        to_improve = []

        for d in dishes:
            sales = d.get("monthly_sales", 0)
            margin = d.get("margin_pct", 0)
            rating = d.get("avg_rating", 5)
            trend = d.get("sales_trend", "持平")

            if sales <= 5 and margin < 50 and rating < 4.0:
                to_remove.append({
                    "dish_name": d.get("dish_name", ""),
                    "reason": f"月销{sales}份、毛利{margin}%、评分{rating}",
                    "priority": "高",
                })
            elif sales <= 10 and (margin < 45 or rating < 3.5):
                to_improve.append({
                    "dish_name": d.get("dish_name", ""),
                    "issue": "低销量" if sales <= 10 else "低毛利" if margin < 45 else "低评分",
                    "suggestion": "优化配方" if rating < 3.5 else "调整定价" if margin < 45 else "加强推广",
                })

        # 季节性建议
        seasonal_add = []
        if season == "夏":
            seasonal_add = [{"dish_name": "凉面", "reason": "夏季热销"}, {"dish_name": "绿豆汤", "reason": "消暑饮品"}]
        elif season == "冬":
            seasonal_add = [{"dish_name": "羊肉汤", "reason": "冬季暖身"}, {"dish_name": "火锅套餐", "reason": "冬季热销"}]

        return AgentResult(
            success=True, action="suggest_dish_changes",
            data={
                "to_remove": to_remove[:10],
                "to_improve": to_improve[:10],
                "to_add_seasonal": seasonal_add,
                "summary": {
                    "remove_count": len(to_remove),
                    "improve_count": len(to_improve),
                    "add_count": len(seasonal_add),
                },
            },
            reasoning=f"菜单调整建议: 下架{len(to_remove)}道、改良{len(to_improve)}道、新增{len(seasonal_add)}道",
            confidence=0.75,
        )

    async def _optimize_combo(self, params: dict) -> AgentResult:
        """套餐组合优化"""
        dishes = params.get("dishes", [])
        target_price_fen = params.get("target_price_fen", 10000)
        target_margin_pct = params.get("target_margin_pct", 60)

        # 选择高毛利+高人气菜品组合
        sorted_by_popularity = sorted(dishes, key=lambda x: x.get("monthly_sales", 0), reverse=True)
        high_margin = [d for d in dishes if d.get("margin_pct", 0) >= 60]

        combos = []
        # 组合1：人气套餐
        if len(sorted_by_popularity) >= 3:
            popular_combo = sorted_by_popularity[:3]
            total_cost = sum(d.get("cost_fen", 0) for d in popular_combo)
            combo_price = int(target_price_fen)
            margin = round((combo_price - total_cost) / max(1, combo_price) * 100, 1)
            combos.append({
                "combo_name": "人气畅销套餐",
                "dishes": [d.get("dish_name", "") for d in popular_combo],
                "original_total_yuan": round(sum(d.get("price_fen", 0) for d in popular_combo) / 100, 2),
                "combo_price_yuan": round(combo_price / 100, 2),
                "margin_pct": margin,
                "discount_pct": round((1 - combo_price / max(1, sum(d.get("price_fen", 0) for d in popular_combo))) * 100, 1),
            })

        # 组合2：高毛利套餐
        if len(high_margin) >= 3:
            margin_combo = high_margin[:3]
            total_cost = sum(d.get("cost_fen", 0) for d in margin_combo)
            combo_price = int(total_cost / (1 - target_margin_pct / 100))
            margin = round((combo_price - total_cost) / max(1, combo_price) * 100, 1)
            combos.append({
                "combo_name": "精选超值套餐",
                "dishes": [d.get("dish_name", "") for d in margin_combo],
                "original_total_yuan": round(sum(d.get("price_fen", 0) for d in margin_combo) / 100, 2),
                "combo_price_yuan": round(combo_price / 100, 2),
                "margin_pct": margin,
                "discount_pct": round((1 - combo_price / max(1, sum(d.get("price_fen", 0) for d in margin_combo))) * 100, 1),
            })

        return AgentResult(
            success=True, action="optimize_combo",
            data={
                "combos": combos,
                "total_combos": len(combos),
                "target_margin_pct": target_margin_pct,
            },
            reasoning=f"优化 {len(combos)} 个套餐组合，目标毛利 {target_margin_pct}%",
            confidence=0.75,
        )

    async def _design_ab_test(self, params: dict) -> AgentResult:
        """菜单AB测试"""
        test_type = params.get("test_type", "pricing")
        dish_name = params.get("dish_name", "")
        variant_a = params.get("variant_a", {})
        variant_b = params.get("variant_b", {})
        test_duration_days = params.get("test_duration_days", 7)
        test_stores = params.get("test_stores", [])

        test_plan = {
            "test_type": test_type,
            "dish_name": dish_name,
            "variant_a": variant_a,
            "variant_b": variant_b,
            "duration_days": test_duration_days,
            "stores": {
                "group_a": test_stores[:len(test_stores) // 2],
                "group_b": test_stores[len(test_stores) // 2:],
            },
            "metrics_to_track": ["日销量", "客单价", "毛利率", "顾客满意度"],
            "min_sample_size": 100,
            "statistical_significance": 0.95,
            "success_criteria": {
                "pricing": "B组收入提升≥5%且毛利率不低于A组",
                "naming": "B组点击率提升≥10%",
                "photo": "B组点击率提升≥15%",
            }.get(test_type, "B组核心指标优于A组"),
        }

        return AgentResult(
            success=True, action="design_ab_test",
            data=test_plan,
            reasoning=f"设计菜单AB测试: {dish_name}，{test_type}维度，{test_duration_days}天，"
                      f"{len(test_stores)}家门店",
            confidence=0.8,
        )
