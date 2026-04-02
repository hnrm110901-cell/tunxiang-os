"""新品机会发现 Agent — P1 | 云端

新品趋势扫描、新品可行性评估、新品定价建议、新品试销方案、竞品新品跟踪、新品上线评估。
扩展：发现建议时自动登记 draft 试点、待决策试点列表。
"""
import uuid
from datetime import date, timedelta
from typing import Any

from ..base import AgentResult, SkillAgent

# 菜品品类
DISH_CATEGORIES = ["凉菜", "热菜", "汤品", "主食", "甜品", "饮品", "小吃", "季节限定"]

# 可行性评估维度
FEASIBILITY_DIMENSIONS = ["原料可得性", "厨师技能匹配度", "设备兼容性", "目标客群匹配", "毛利率预估", "差异化程度"]


class NewProductScoutAgent(SkillAgent):
    agent_id = "new_product_scout"
    agent_name = "新品机会发现"
    description = "新品趋势扫描、可行性评估、定价建议、试销方案、竞品新品跟踪、上线评估"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "scan_new_product_trends",
            "assess_feasibility",
            "suggest_pricing",
            "plan_trial_sale",
            "track_competitor_new_products",
            "evaluate_launch_readiness",
            "register_scouted_pilot",
            "get_scouted_pending_pilots",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "scan_new_product_trends": self._scan_trends,
            "assess_feasibility": self._assess_feasibility,
            "suggest_pricing": self._suggest_pricing,
            "plan_trial_sale": self._plan_trial,
            "track_competitor_new_products": self._track_competitor_np,
            "evaluate_launch_readiness": self._evaluate_launch,
            "register_scouted_pilot": self._register_scouted_pilot,
            "get_scouted_pending_pilots": self._get_scouted_pending_pilots,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _scan_trends(self, params: dict) -> AgentResult:
        """新品趋势扫描"""
        trend_data = params.get("trend_data", [])
        our_menu = params.get("our_menu", [])

        opportunities = []
        for item in trend_data:
            name = item.get("name", "")
            category = item.get("category", "其他")
            popularity = item.get("popularity_score", 0)
            growth = item.get("growth_pct", 0)
            already_have = name in our_menu

            if growth >= 10 or popularity >= 70:
                opportunities.append({
                    "dish_name": name,
                    "category": category,
                    "popularity_score": popularity,
                    "growth_pct": growth,
                    "already_in_menu": already_have,
                    "opportunity_score": round(popularity * 0.6 + growth * 0.4, 1),
                    "source": item.get("source", "市场数据"),
                    "recommendation": "已有菜品，建议主推" if already_have else "建议研发上新",
                })

        opportunities.sort(key=lambda x: x["opportunity_score"], reverse=True)

        return AgentResult(
            success=True, action="scan_new_product_trends",
            data={
                "opportunities": opportunities[:15],
                "total_scanned": len(trend_data),
                "actionable_count": len(opportunities),
                "new_to_develop": sum(1 for o in opportunities if not o["already_in_menu"]),
            },
            reasoning=f"扫描 {len(trend_data)} 个趋势，发现 {len(opportunities)} 个新品机会，"
                      f"需研发 {sum(1 for o in opportunities if not o['already_in_menu'])} 个",
            confidence=0.75,
        )

    async def _assess_feasibility(self, params: dict) -> AgentResult:
        """新品可行性评估"""
        dish_name = params.get("dish_name", "")
        ingredients = params.get("ingredients", [])
        required_skills = params.get("required_skills", [])
        required_equipment = params.get("required_equipment", [])
        target_audience = params.get("target_audience", "全部")
        estimated_cost_fen = params.get("estimated_cost_fen", 0)
        expected_price_fen = params.get("expected_price_fen", 0)

        scores = {}

        # 原料可得性
        available_ingredients = params.get("available_ingredients", [])
        ingredient_match = len(set(ingredients) & set(available_ingredients)) / max(1, len(ingredients))
        scores["原料可得性"] = round(ingredient_match * 100, 0)

        # 厨师技能匹配度
        chef_skills = params.get("chef_skills", [])
        skill_match = len(set(required_skills) & set(chef_skills)) / max(1, len(required_skills))
        scores["厨师技能匹配度"] = round(skill_match * 100, 0)

        # 设备兼容性
        existing_equipment = params.get("existing_equipment", [])
        equip_match = len(set(required_equipment) & set(existing_equipment)) / max(1, len(required_equipment))
        scores["设备兼容性"] = round(equip_match * 100, 0)

        # 毛利率预估
        margin_pct = round((expected_price_fen - estimated_cost_fen) / max(1, expected_price_fen) * 100, 1) if expected_price_fen > 0 else 0
        scores["毛利率预估"] = min(100, max(0, margin_pct * 1.5))

        # 综合评分
        total_score = round(sum(scores.values()) / len(scores), 1)
        feasibility = "高" if total_score >= 75 else "中" if total_score >= 50 else "低"

        return AgentResult(
            success=True, action="assess_feasibility",
            data={
                "dish_name": dish_name,
                "dimension_scores": scores,
                "total_score": total_score,
                "feasibility": feasibility,
                "estimated_margin_pct": margin_pct,
                "missing_ingredients": list(set(ingredients) - set(available_ingredients)),
                "missing_skills": list(set(required_skills) - set(chef_skills)),
                "missing_equipment": list(set(required_equipment) - set(existing_equipment)),
                "recommendation": "建议上线" if feasibility == "高" else "需补齐短板后上线" if feasibility == "中" else "暂不建议",
            },
            reasoning=f"「{dish_name}」可行性评分 {total_score}分（{feasibility}），毛利率 {margin_pct}%",
            confidence=0.8,
        )

    async def _suggest_pricing(self, params: dict) -> AgentResult:
        """新品定价建议"""
        dish_name = params.get("dish_name", "")
        cost_fen = params.get("cost_fen", 0)
        target_margin_pct = params.get("target_margin_pct", 65)
        competitor_prices = params.get("competitor_prices", [])
        category_avg_price_fen = params.get("category_avg_price_fen", 0)

        # 成本加成定价
        cost_plus_price = int(cost_fen / (1 - target_margin_pct / 100))

        # 竞品参考定价
        avg_comp_price = int(sum(p.get("price_fen", 0) for p in competitor_prices) / max(1, len(competitor_prices))) if competitor_prices else 0

        # 综合定价建议
        if avg_comp_price > 0:
            suggested = int((cost_plus_price * 0.5 + avg_comp_price * 0.3 + category_avg_price_fen * 0.2))
        else:
            suggested = cost_plus_price

        actual_margin = round((suggested - cost_fen) / max(1, suggested) * 100, 1)

        return AgentResult(
            success=True, action="suggest_pricing",
            data={
                "dish_name": dish_name,
                "cost_yuan": round(cost_fen / 100, 2),
                "pricing_strategies": {
                    "cost_plus": round(cost_plus_price / 100, 2),
                    "competitor_avg": round(avg_comp_price / 100, 2) if avg_comp_price else None,
                    "category_avg": round(category_avg_price_fen / 100, 2) if category_avg_price_fen else None,
                },
                "suggested_price_yuan": round(suggested / 100, 2),
                "suggested_price_fen": suggested,
                "actual_margin_pct": actual_margin,
                "price_range": {
                    "low_yuan": round(cost_plus_price * 0.9 / 100, 2),
                    "high_yuan": round(cost_plus_price * 1.15 / 100, 2),
                },
            },
            reasoning=f"「{dish_name}」建议定价 ¥{suggested / 100:.0f}，毛利率 {actual_margin}%",
            confidence=0.8,
        )

    async def _plan_trial(self, params: dict) -> AgentResult:
        """新品试销方案"""
        dish_name = params.get("dish_name", "")
        trial_stores = params.get("trial_stores", [])
        trial_days = params.get("trial_days", 14)
        daily_limit = params.get("daily_limit", 30)

        plan = {
            "dish_name": dish_name,
            "trial_stores": [{"store_id": s.get("store_id"), "store_name": s.get("store_name")} for s in trial_stores],
            "trial_days": trial_days,
            "daily_limit": daily_limit,
            "total_expected_portions": daily_limit * trial_days * len(trial_stores),
            "phases": [
                {"phase": 1, "days": "1-3", "goal": "内部品鉴+菜品调优", "action": "员工试吃+厨师调味"},
                {"phase": 2, "days": "4-7", "goal": "小范围测试", "action": "限量供应+收集反馈"},
                {"phase": 3, "days": "8-14", "goal": "放量验证", "action": "正式售卖+数据跟踪"},
            ],
            "success_criteria": {
                "min_daily_orders": 15,
                "min_rating": 4.0,
                "min_reorder_rate_pct": 20,
                "target_margin_pct": 60,
            },
            "data_collection": ["日销量", "顾客评分", "复购率", "出餐时间", "退菜率", "食材损耗率"],
        }

        return AgentResult(
            success=True, action="plan_trial_sale",
            data=plan,
            reasoning=f"「{dish_name}」试销方案: {len(trial_stores)} 家门店，{trial_days}天，日限 {daily_limit} 份",
            confidence=0.85,
        )

    async def _track_competitor_np(self, params: dict) -> AgentResult:
        """竞品新品跟踪"""
        competitor_new_products = params.get("competitor_new_products", [])

        tracked = []
        for p in competitor_new_products:
            tracked.append({
                "competitor": p.get("competitor", ""),
                "dish_name": p.get("dish_name", ""),
                "category": p.get("category", ""),
                "price_yuan": round(p.get("price_fen", 0) / 100, 2),
                "launch_date": p.get("launch_date", ""),
                "estimated_sales": p.get("estimated_daily_sales", 0),
                "customer_rating": p.get("rating", 0),
                "is_hit": p.get("rating", 0) >= 4.5 and p.get("estimated_daily_sales", 0) >= 20,
                "our_response": "需要跟进" if p.get("rating", 0) >= 4.5 else "持续观察",
            })

        hits = [t for t in tracked if t["is_hit"]]
        return AgentResult(
            success=True, action="track_competitor_new_products",
            data={
                "tracked_products": tracked,
                "total": len(tracked),
                "hit_products": len(hits),
                "need_follow_up": sum(1 for t in tracked if t["our_response"] == "需要跟进"),
            },
            reasoning=f"跟踪 {len(tracked)} 个竞品新品，爆品 {len(hits)} 个",
            confidence=0.75,
        )

    async def _evaluate_launch(self, params: dict) -> AgentResult:
        """新品上线评估"""
        dish_name = params.get("dish_name", "")
        trial_data = params.get("trial_data", {})

        avg_daily_sales = trial_data.get("avg_daily_sales", 0)
        avg_rating = trial_data.get("avg_rating", 0)
        reorder_rate = trial_data.get("reorder_rate_pct", 0)
        actual_margin = trial_data.get("actual_margin_pct", 0)
        return_rate = trial_data.get("return_rate_pct", 0)

        # 多维评分
        scores = {
            "销量": min(100, avg_daily_sales / 0.3),
            "评分": avg_rating * 20,
            "复购": reorder_rate * 2,
            "毛利": actual_margin * 1.2,
            "退菜率": max(0, 100 - return_rate * 10),
        }

        total = round(sum(scores.values()) / len(scores), 1)
        decision = "通过" if total >= 70 else "有条件通过" if total >= 50 else "不通过"

        return AgentResult(
            success=True, action="evaluate_launch_readiness",
            data={
                "dish_name": dish_name,
                "dimension_scores": scores,
                "total_score": total,
                "decision": decision,
                "trial_summary": {
                    "avg_daily_sales": avg_daily_sales,
                    "avg_rating": avg_rating,
                    "reorder_rate_pct": reorder_rate,
                    "actual_margin_pct": actual_margin,
                    "return_rate_pct": return_rate,
                },
                "next_steps": {
                    "通过": "全门店上线",
                    "有条件通过": "优化后扩大试点",
                    "不通过": "暂停上线，重新评估",
                }.get(decision, ""),
            },
            reasoning=f"「{dish_name}」上线评估 {total}分，决策: {decision}",
            confidence=0.8,
        )

    async def _register_scouted_pilot(self, params: dict) -> AgentResult:
        """
        在发现新品 / 新原料建议时，将建议登记为 draft 试点计划。

        params 示例：
        {
            "tenant_id": "uuid",
            "dish_name": "麻辣香锅",
            "category": "热菜",
            "opportunity_score": 82.0,
            "source": "趋势扫描",
            "source_ref_id": "uuid",          # 来源情报 ID（可选）
            "suggested_trial_days": 14,
            "target_stores": [{"store_id": "uuid", "store_name": "长沙解放西店"}]
        }
        """
        tenant_id_str = params.get("tenant_id", "")
        dish_name = params.get("dish_name", "")
        source = params.get("source", "trend_signal")
        opportunity_score = params.get("opportunity_score", 0)
        target_stores = params.get("target_stores", [])
        trial_days = params.get("suggested_trial_days", 14)

        if not dish_name:
            return AgentResult(success=False, action="register_scouted_pilot", error="缺少 dish_name")

        today = date.today()
        start_date = (today + timedelta(days=7)).isoformat()
        end_date = (today + timedelta(days=7 + trial_days)).isoformat()

        pilot_draft = {
            "pilot_id": str(uuid.uuid4()),
            "tenant_id": tenant_id_str,
            "name": f"【新品侦察】{dish_name} 试销验证",
            "pilot_type": "new_dish",
            "recommendation_source": "trend_signal",
            "source_ref_id": params.get("source_ref_id"),
            "hypothesis": f"引入{dish_name}可吸引新客群并提升品类丰富度，预期试销期日均销量 ≥ 15 份",
            "target_stores": target_stores,
            "control_stores": [],
            "start_date": start_date,
            "end_date": end_date,
            "status": "draft",
            "success_criteria": [
                {"metric": "total_sales", "operator": "gte", "threshold": 15 * trial_days,
                 "description": f"试销期总销量 ≥ {15 * trial_days} 份"},
            ],
            "opportunity_score": opportunity_score,
            "scout_source": source,
            "note": "由新品侦察 Agent 自动发现，需人工决策后激活",
        }

        return AgentResult(
            success=True, action="register_scouted_pilot",
            data={
                "pilot_draft": pilot_draft,
                "auto_registered": True,
                "next_step": "调用 POST /api/v1/pilots 提交草稿，等待运营团队决策",
            },
            reasoning=f"新品「{dish_name}」（机会评分 {opportunity_score}）已登记试点草稿，"
                      f"建议 {start_date} 至 {end_date} 试销",
            confidence=0.75,
        )

    async def _get_scouted_pending_pilots(self, params: dict) -> AgentResult:
        """
        获取待决策的新品侦察试点建议列表（来源为 trend_signal 的 draft 试点）。

        params: {"draft_pilots": [...]}  — 从 pilot_programs 查询到的 draft 列表
        """
        draft_pilots = params.get("draft_pilots", [])

        # 筛选新品侦察来源
        scouted = [
            p for p in draft_pilots
            if p.get("recommendation_source") in ("trend_signal", "competitor_watch")
        ]
        scouted.sort(key=lambda p: p.get("opportunity_score", 0), reverse=True)

        urgent = [p for p in scouted if p.get("opportunity_score", 0) >= 75]
        watch = [p for p in scouted if p.get("opportunity_score", 0) < 75]

        return AgentResult(
            success=True, action="get_scouted_pending_pilots",
            data={
                "total_pending": len(scouted),
                "urgent_decision": len(urgent),
                "watch_list": len(watch),
                "pilots": scouted[:20],
                "action_required": "请在7天内对高分建议（评分≥75）做出试点决策",
            },
            reasoning=f"待决策新品试点建议 {len(scouted)} 个，"
                      f"其中紧急决策 {len(urgent)} 个（评分≥75）",
            confidence=0.8,
        )
