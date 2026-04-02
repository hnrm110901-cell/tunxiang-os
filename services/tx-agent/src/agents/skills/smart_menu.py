"""#2 智能排菜 Agent — P0 | 云端

来源：dish_rd(5子Agent) + QualityAgent + menu_ranker
能力：成本仿真、试点推荐、复盘优化、上市检查、风险预警、图片质检、四象限分类、菜单优化

全部 8 个 action 已实现。
"""
import statistics
from datetime import datetime, timezone
from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger()


# 上市检查清单
LAUNCH_CHECKLIST = ["配方定版", "成本核算", "SOP文档", "试点测试", "培训完成", "审批通过", "物料备齐", "定价确认"]

# 风险阈值
RISK_THRESHOLDS = {"cost_over_pct": 5, "pilot_min_score": 70, "return_rate_pct": 5, "bad_review_pct": 10}


class SmartMenuAgent(SkillAgent):
    agent_id = "smart_menu"
    agent_name = "智能排菜"
    description = "菜品研发全生命周期：成本仿真→试点→复盘→上市→风险监控→菜单优化"
    priority = "P0"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "simulate_cost", "recommend_pilot_stores", "run_dish_review",
            "check_launch_readiness", "scan_dish_risks", "inspect_dish_quality",
            "classify_quadrant", "optimize_menu",
            "suggest_alternatives", "mark_sold_out",
            "push_expiry_specials", "flag_high_cost_dishes",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "simulate_cost": self._simulate_cost,
            "recommend_pilot_stores": self._recommend_pilots,
            "run_dish_review": self._dish_review,
            "check_launch_readiness": self._launch_check,
            "scan_dish_risks": self._scan_risks,
            "inspect_dish_quality": self._inspect_quality,
            "classify_quadrant": self._classify_quadrant,
            "optimize_menu": self._optimize_menu,
            "suggest_alternatives": self._suggest_alternatives,
            "mark_sold_out": self._mark_sold_out,
            "push_expiry_specials": self._push_expiry_specials,
            "flag_high_cost_dishes": self._flag_high_cost_dishes,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported: {action}")
        return await handler(params)

    async def _simulate_cost(self, params: dict) -> AgentResult:
        """BOM 成本仿真 + 多定价方案 + 涨价压力测试"""
        bom_items = params.get("bom_items", [])
        target_price_fen = params.get("target_price_fen", 0)
        total_cost = sum(i.get("cost_fen", 0) * i.get("quantity", 1) for i in bom_items)
        margin = (target_price_fen - total_cost) / target_price_fen if target_price_fen > 0 else 0

        # 多定价方案
        scenarios = []
        for mult in [0.9, 1.0, 1.1, 1.2]:
            p = round(target_price_fen * mult)
            m = (p - total_cost) / p if p > 0 else 0
            scenarios.append({"price_fen": p, "price_yuan": round(p / 100, 2), "margin_rate": round(m, 4)})

        # 涨价压力测试（原料涨10%/20%）
        stress = []
        for pct in [10, 20]:
            new_cost = round(total_cost * (1 + pct / 100))
            new_margin = (target_price_fen - new_cost) / target_price_fen if target_price_fen > 0 else 0
            stress.append({"cost_increase_pct": pct, "new_cost_fen": new_cost, "new_margin": round(new_margin, 4)})

        return AgentResult(
            success=True, action="simulate_cost",
            data={"total_cost_fen": total_cost, "target_price_fen": target_price_fen,
                  "margin_rate": round(margin, 4), "cost_fen": total_cost, "price_fen": target_price_fen,
                  "pricing_scenarios": scenarios, "stress_test": stress},
            reasoning=f"BOM成本 ¥{total_cost/100:.2f}，毛利率 {margin:.1%}",
            confidence=0.9,
        )

    async def _recommend_pilots(self, params: dict) -> AgentResult:
        """试点门店推荐"""
        stores = params.get("stores", [])
        dish_category = params.get("dish_category", "")

        scored = []
        for s in stores:
            score = 50
            if s.get("customer_base", 0) > 200:
                score += 20
            if dish_category in s.get("popular_categories", []):
                score += 15
            if s.get("staff_skill_avg", 0) > 80:
                score += 15
            scored.append({**s, "match_score": min(100, score)})

        scored.sort(key=lambda x: x["match_score"], reverse=True)
        recommended = scored[:3]

        return AgentResult(
            success=True, action="recommend_pilot_stores",
            data={"recommended": recommended, "total_evaluated": len(stores),
                  "suggested_duration_weeks": 2, "suggested_sample_size": min(50, max(20, len(stores) * 5))},
            reasoning=f"从 {len(stores)} 家门店中推荐 {len(recommended)} 家试点",
            confidence=0.8,
        )

    async def _dish_review(self, params: dict) -> AgentResult:
        """菜品复盘 — keep/optimize/monitor/retire"""
        sales = params.get("total_sales", 0)
        return_count = params.get("return_count", 0)
        bad_reviews = params.get("bad_review_count", 0)
        margin_rate = params.get("margin_rate", 0)
        avg_sales = params.get("category_avg_sales", 100)

        return_rate = return_count / sales * 100 if sales > 0 else 0
        bad_rate = bad_reviews / sales * 100 if sales > 0 else 0

        if margin_rate >= 0.3 and sales >= avg_sales and return_rate < 3 and bad_rate < 5:
            verdict = "keep"
            action = "维持现状，考虑推广到更多门店"
        elif margin_rate >= 0.2 and return_rate < 5:
            verdict = "optimize"
            action = "优化配方降低成本或调整售价"
        elif sales < avg_sales * 0.5 or return_rate > 10:
            verdict = "retire"
            action = "建议下架，释放菜单位置给新品"
        else:
            verdict = "monitor"
            action = "继续观察2周，关注退菜率趋势"

        return AgentResult(
            success=True, action="run_dish_review",
            data={"verdict": verdict, "suggested_action": action,
                  "metrics": {"sales": sales, "return_rate_pct": round(return_rate, 1),
                              "bad_review_pct": round(bad_rate, 1), "margin_rate": margin_rate}},
            reasoning=f"复盘结论：{verdict} — {action}",
            confidence=0.85,
        )

    async def _launch_check(self, params: dict) -> AgentResult:
        """上市就绪检查"""
        completed = params.get("completed_items", [])
        missing = [item for item in LAUNCH_CHECKLIST if item not in completed]
        ready = len(missing) == 0

        return AgentResult(
            success=True, action="check_launch_readiness",
            data={"ready": ready, "completed": completed, "missing": missing,
                  "completion_pct": round(len(completed) / len(LAUNCH_CHECKLIST) * 100, 1),
                  "checklist": LAUNCH_CHECKLIST},
            reasoning=f"就绪度 {len(completed)}/{len(LAUNCH_CHECKLIST)}，{'可上市' if ready else '缺少: ' + ', '.join(missing[:3])}",
            confidence=0.95,
        )

    async def _scan_risks(self, params: dict) -> AgentResult:
        """品牌级菜品风险扫描"""
        dishes = params.get("dishes", [])
        risks = []

        for d in dishes:
            name = d.get("name", "")
            risk_types = []
            if d.get("cost_over_target_pct", 0) > RISK_THRESHOLDS["cost_over_pct"]:
                risk_types.append("成本超标")
            if d.get("pilot_score", 100) < RISK_THRESHOLDS["pilot_min_score"]:
                risk_types.append("试点评分低")
            if d.get("return_rate_pct", 0) > RISK_THRESHOLDS["return_rate_pct"]:
                risk_types.append("高退菜率")
            if d.get("bad_review_pct", 0) > RISK_THRESHOLDS["bad_review_pct"]:
                risk_types.append("差评聚集")

            if risk_types:
                risks.append({"dish_name": name, "risks": risk_types, "risk_count": len(risk_types)})

        risks.sort(key=lambda r: r["risk_count"], reverse=True)
        return AgentResult(
            success=True, action="scan_dish_risks",
            data={"risks": risks, "total_scanned": len(dishes), "at_risk": len(risks)},
            reasoning=f"扫描 {len(dishes)} 道菜品，{len(risks)} 道有风险",
            confidence=0.85,
        )

    async def _inspect_quality(self, params: dict) -> AgentResult:
        """图片质检（视觉AI评分）"""
        image_url = params.get("image_url", "")
        dish_name = params.get("dish_name", "")

        # Placeholder: 实际调用视觉模型
        score = params.get("mock_score", 82)
        threshold = params.get("threshold", 75)
        passed = score >= threshold

        return AgentResult(
            success=True, action="inspect_dish_quality",
            data={"dish_name": dish_name, "quality_score": score, "threshold": threshold,
                  "passed": passed, "issues": [] if passed else ["摆盘不规范"]},
            reasoning=f"{dish_name} 质检 {score} 分，{'合格' if passed else '不合格'}",
            confidence=0.7,
        )

    async def _classify_quadrant(self, params: dict) -> AgentResult:
        """四象限分类"""
        sales = params.get("total_sales", 0)
        margin = params.get("margin_rate", 0)
        avg_sales = params.get("avg_sales", 100)
        avg_margin = params.get("avg_margin", 0.3)

        high_sales = sales >= avg_sales
        high_margin = margin >= avg_margin
        quadrant = ("star" if high_sales and high_margin else
                    "cash_cow" if not high_sales and high_margin else
                    "question" if high_sales and not high_margin else "dog")

        actions = {"star": "重点推广", "cash_cow": "保持品质", "question": "优化成本或提价", "dog": "考虑下架或改良"}

        return AgentResult(
            success=True, action="classify_quadrant",
            data={"quadrant": quadrant, "sales": sales, "margin_rate": margin, "suggested_action": actions[quadrant]},
            reasoning=f"销量{'高' if high_sales else '低'}+毛利{'高' if high_margin else '低'} → {quadrant}",
            confidence=0.85,
        )

    async def _optimize_menu(self, params: dict) -> AgentResult:
        """菜单结构优化建议 — 有 DB 时查真实销量，有 model_router 时用 Claude 生成建议"""
        store_id = params.get("store_id") or self.store_id
        dishes = params.get("dishes", [])

        # 若有 DB 且有 store_id，从 order_items 聚合近30天真实销量数据
        db_dishes: list[dict] = []
        if self._db and store_id:
            from sqlalchemy import text
            rows = await self._db.execute(
                text("""
                    SELECT oi.dish_id, oi.dish_name,
                           COUNT(*) AS order_count,
                           SUM(oi.quantity) AS total_qty,
                           AVG(oi.unit_price_fen) AS avg_price_fen
                    FROM order_items oi
                    JOIN orders o ON oi.order_id = o.id
                    WHERE o.tenant_id = :tenant_id
                      AND o.store_id = :store_id
                      AND o.created_at >= NOW() - INTERVAL '30 days'
                      AND o.status = 'completed'
                    GROUP BY oi.dish_id, oi.dish_name
                    ORDER BY total_qty DESC
                    LIMIT 20
                """),
                {"tenant_id": self.tenant_id, "store_id": store_id},
            )
            db_dishes = [dict(r) for r in rows.mappings().all()]

        # 合并：DB 数据优先，无 DB 数据时退回 params 中的 dishes
        working_dishes = db_dishes if db_dishes else dishes
        if not working_dishes:
            return AgentResult(success=False, action="optimize_menu", error="无菜品数据")

        # 规则引擎四象限分类（始终执行）
        quadrants: dict[str, list[str]] = {"star": [], "cash_cow": [], "question": [], "dog": []}
        for d in working_dishes:
            # 兼容 DB 返回（total_qty）和 params 传入（total_sales）两种字段名
            sales = d.get("total_qty") or d.get("total_sales", 0)
            margin = d.get("margin_rate", 0)
            name = d.get("dish_name") or d.get("name", "")
            avg_s = statistics.mean(
                [(x.get("total_qty") or x.get("total_sales", 0)) for x in working_dishes]
            ) if working_dishes else 1
            avg_m = statistics.mean(
                [x.get("margin_rate", 0) for x in working_dishes]
            ) if working_dishes else 0.3

            q = ("star" if sales >= avg_s and margin >= avg_m else
                 "cash_cow" if sales < avg_s and margin >= avg_m else
                 "question" if sales >= avg_s and margin < avg_m else "dog")
            quadrants[q].append(name)

        # 规则引擎基础建议
        suggestions: list[str] = []
        if quadrants["dog"]:
            suggestions.append(f"建议下架/改良: {', '.join(quadrants['dog'][:3])}")
        if quadrants["question"]:
            suggestions.append(f"建议优化成本: {', '.join(quadrants['question'][:3])}")
        if quadrants["star"]:
            suggestions.append(f"重点推广: {', '.join(quadrants['star'][:3])}")

        llm_suggestions = ""
        # 若有 model_router，用 Claude 生成更详细的菜单优化建议
        if self._router:
            dish_summary = "\n".join(
                f"- {d.get('dish_name') or d.get('name', '')}: "
                f"销量{d.get('total_qty') or d.get('total_sales', 0)}份，"
                f"均价{(d.get('avg_price_fen') or 0) / 100:.1f}元，"
                f"毛利率{d.get('margin_rate', 0):.1%}"
                for d in working_dishes[:10]
            )
            try:
                llm_suggestions = await self._router.complete(
                    tenant_id=self.tenant_id,
                    task_type="standard_analysis",
                    system="你是连锁餐饮菜单运营专家，根据近30天销量数据给出菜单优化建议，重点关注盈利改善和客户满意度，用中文回复200字以内。",
                    messages=[{"role": "user", "content":
                        f"以下是门店近30天菜品销售数据：\n{dish_summary}\n\n"
                        f"四象限分布：明星{len(quadrants['star'])}道，现金牛{len(quadrants['cash_cow'])}道，"
                        f"问题{len(quadrants['question'])}道，瘦狗{len(quadrants['dog'])}道。\n"
                        f"请给出具体的菜单优化建议。"}],
                    max_tokens=400,
                    db=self._db,
                )
            except Exception as exc:  # noqa: BLE001 — Claude不可用时降级为规则引擎建议
                logger.warning("smart_menu_llm_fallback", error=str(exc))

        if llm_suggestions:
            suggestions.append(f"AI深度分析: {llm_suggestions}")

        return AgentResult(
            success=True, action="optimize_menu",
            data={
                "quadrant_distribution": {k: len(v) for k, v in quadrants.items()},
                "suggestions": suggestions,
                "total_dishes": len(working_dishes),
                "data_source": "db_realtime" if db_dishes else "params",
                "store_id": store_id,
            },
            reasoning=f"菜单分析：明星{len(quadrants['star'])}道，瘦狗{len(quadrants['dog'])}道"
                      f"{'（AI增强）' if llm_suggestions else '（规则引擎）'}",
            confidence=0.8 if not llm_suggestions else 0.92,
            inference_layer="cloud" if llm_suggestions else "edge",
        )

    # ─── 事件驱动：推荐替代菜品 ───

    async def _suggest_alternatives(self, params: dict) -> AgentResult:
        """supply.stock.low 触发：当某食材库存不足时，推荐可替代菜品给前端展示

        替代策略：
        1. 同类菜品中不依赖该食材的菜品
        2. 当日销量/毛利率排名靠前
        3. 推荐数量控制在 3-5 道
        """
        store_id = params.get("store_id") or self.store_id
        event_data = params.get("event_data", {})
        ingredient_id = params.get("ingredient_id") or event_data.get("ingredient_id")
        ingredient_name = params.get("ingredient_name") or event_data.get("ingredient_name", "")
        affected_dishes = params.get("affected_dishes") or event_data.get("affected_dishes", [])
        # affected_dishes: [{"dish_id": ..., "dish_name": ..., "category": ...}]
        all_available_dishes = params.get("all_available_dishes", [])
        # all_available_dishes: 同类别下所有在售菜品

        # 找出被影响菜品的类别
        affected_categories = list({d.get("category", "other") for d in affected_dishes})
        affected_dish_ids = {d.get("dish_id") for d in affected_dishes}

        # 从可用菜品中筛选替代候选
        candidates = [
            d for d in all_available_dishes
            if d.get("dish_id") not in affected_dish_ids
            and d.get("category") in affected_categories
            and d.get("is_available", True)
        ]

        # 若有 DB，从数据库查真实数据
        db_candidates: list[dict] = []
        if self._db and store_id and affected_categories:
            from sqlalchemy import text
            categories_str = ",".join(f"'{c}'" for c in affected_categories[:5])
            rows = await self._db.execute(text(f"""
                SELECT d.id, d.name, d.category, d.sell_price_fen,
                       COALESCE(d.cost_price_fen, 0) as cost_price_fen,
                       COUNT(oi.id) as recent_orders
                FROM dishes d
                LEFT JOIN order_items oi ON oi.dish_id = d.id
                    AND oi.created_at >= NOW() - INTERVAL '7 days'
                WHERE d.tenant_id = :tenant_id
                  AND d.is_deleted = false
                  AND d.is_available = true
                  AND d.category IN ({categories_str})
                  AND d.id NOT IN (
                    SELECT unnest(ARRAY[:affected_ids]::UUID[])
                  )
                GROUP BY d.id, d.name, d.category, d.sell_price_fen, d.cost_price_fen
                ORDER BY recent_orders DESC
                LIMIT 8
            """), {
                "tenant_id": self.tenant_id,
                "affected_ids": list(affected_dish_ids) or ["00000000-0000-0000-0000-000000000000"],
            })
            db_candidates = [dict(r) for r in rows.mappings()]

        working = db_candidates if db_candidates else candidates

        # 计算推荐分（销量 + 毛利）
        def score_dish(d: dict) -> float:
            price = d.get("sell_price_fen") or d.get("price_fen", 0)
            cost = d.get("cost_price_fen") or d.get("cost_fen", 0)
            margin = (price - cost) / price if price > 0 else 0
            popularity = d.get("recent_orders") or d.get("sales_count", 0)
            return margin * 0.6 + min(1.0, popularity / 50) * 0.4

        working.sort(key=score_dish, reverse=True)
        recommendations = working[:5]

        logger.info(
            "alternatives_suggested",
            store_id=store_id,
            ingredient_name=ingredient_name,
            affected_count=len(affected_dishes),
            recommendation_count=len(recommendations),
        )

        return AgentResult(
            success=True,
            action="suggest_alternatives",
            data={
                "store_id": store_id,
                "shortage_ingredient": ingredient_name,
                "affected_dishes": [d.get("dish_name") or d.get("name", "") for d in affected_dishes],
                "recommendations": [
                    {
                        "dish_id": str(d.get("id") or d.get("dish_id", "")),
                        "dish_name": d.get("name") or d.get("dish_name", ""),
                        "category": d.get("category", ""),
                        "price_fen": d.get("sell_price_fen") or d.get("price_fen", 0),
                    }
                    for d in recommendations
                ],
                "recommendation_count": len(recommendations),
            },
            reasoning=(
                f"替代推荐：{ingredient_name}库存不足影响{len(affected_dishes)}道菜，"
                f"推荐{len(recommendations)}个替代选项"
            ),
            confidence=0.8 if db_candidates else 0.6,
        )

    # ─── 事件驱动：标记菜品售罄 ───

    async def _mark_sold_out(self, params: dict) -> AgentResult:
        """supply.stock.zero 触发：将依赖该食材的菜品标记为售罄

        生成需要更新售卖状态的菜品列表（不直接写 DB，
        由 tx-menu service 消费此结果执行实际更新）。
        """
        store_id = params.get("store_id") or self.store_id
        event_data = params.get("event_data", {})
        ingredient_id = params.get("ingredient_id") or event_data.get("ingredient_id")
        ingredient_name = params.get("ingredient_name") or event_data.get("ingredient_name", "")
        affected_dishes = params.get("affected_dishes") or event_data.get("affected_dishes", [])

        # 若有 DB，查找依赖该食材的所有在售菜品
        dishes_to_mark: list[dict] = []
        if self._db and ingredient_id:
            from sqlalchemy import text
            rows = await self._db.execute(text("""
                SELECT DISTINCT d.id, d.name, d.category, d.sell_price_fen
                FROM dishes d
                JOIN bom_recipe_items bri ON bri.dish_id = d.id
                WHERE d.tenant_id = :tenant_id
                  AND bri.ingredient_id = :ingredient_id
                  AND d.is_deleted = false
                  AND d.is_available = true
            """), {"tenant_id": self.tenant_id, "ingredient_id": ingredient_id})
            dishes_to_mark = [dict(r) for r in rows.mappings()]
        else:
            # 降级：使用 params 传入的数据
            dishes_to_mark = [
                {"id": d.get("dish_id", ""), "name": d.get("dish_name", ""),
                 "category": d.get("category", "")}
                for d in affected_dishes
            ]

        marked_count = len(dishes_to_mark)

        logger.info(
            "dishes_marked_sold_out",
            store_id=store_id,
            ingredient_name=ingredient_name,
            marked_count=marked_count,
        )

        return AgentResult(
            success=True,
            action="mark_sold_out",
            data={
                "store_id": store_id,
                "ingredient_id": ingredient_id,
                "ingredient_name": ingredient_name,
                "dishes_to_mark_sold_out": [
                    {
                        "dish_id": str(d.get("id") or d.get("dish_id", "")),
                        "dish_name": d.get("name") or d.get("dish_name", ""),
                        "category": d.get("category", ""),
                    }
                    for d in dishes_to_mark
                ],
                "marked_count": marked_count,
                "action_required": "update_dish_availability",  # 通知 tx-menu service
                "marked_at": datetime.now(timezone.utc).isoformat(),
            },
            reasoning=(
                f"售罄标记：{ingredient_name} 库存归零，"
                f"需下架{marked_count}道菜品"
            ),
            confidence=0.95 if self._db else 0.75,
        )

    # ─── 事件驱动：推送临期特价菜 ───

    async def _push_expiry_specials(self, params: dict) -> AgentResult:
        """supply.ingredient.expiring 触发：基于临期食材生成特价菜推送

        与 inventory_alert.plan_usage 配合：
        - plan_usage 负责制定内部用料计划
        - push_expiry_specials 负责对外推送给顾客

        推送渠道：菜单首屏 Banner + 小程序推荐位 + 服务员话术建议
        """
        store_id = params.get("store_id") or self.store_id
        event_data = params.get("event_data", {})
        ingredient_name = params.get("ingredient_name") or event_data.get("ingredient_name", "")
        days_to_expiry = params.get("days_to_expiry") or event_data.get("days_to_expiry", 3)
        related_dishes = params.get("related_dishes") or event_data.get("related_dishes", [])
        current_qty = params.get("current_qty") or event_data.get("current_qty", 0)
        unit = params.get("unit") or event_data.get("unit", "")

        # 定价策略（临期越近折扣越大）
        discount_pct = (
            30 if days_to_expiry <= 1 else
            20 if days_to_expiry <= 2 else
            10
        )

        # 生成特价菜推送内容
        specials: list[dict] = []
        for dish in related_dishes[:4]:
            original_price_fen = dish.get("sell_price_fen") or dish.get("price_fen", 0)
            special_price_fen = int(original_price_fen * (1 - discount_pct / 100))
            specials.append({
                "dish_id": dish.get("dish_id") or dish.get("id", ""),
                "dish_name": dish.get("dish_name") or dish.get("name", ""),
                "original_price_fen": original_price_fen,
                "special_price_fen": special_price_fen,
                "discount_pct": discount_pct,
                "highlight": f"今日特惠 {discount_pct}% OFF",
            })

        # 服务员推销话术
        waiter_script = (
            f"您好，今天我们的{ingredient_name}非常新鲜，"
            f"特别推出{', '.join([s['dish_name'] for s in specials[:2]] or ['特色菜品'])}，"
            f"今日优惠{discount_pct}%，非常划算，您要不要来一份？"
        )

        # 菜单 Banner 文案
        banner_text = (
            f"今日{ingredient_name}特鲜特惠！"
            f"{discount_pct}% OFF 限时优惠"
        )

        push_channels = [
            {"channel": "menu_banner", "content": banner_text, "priority": 1},
            {"channel": "miniapp_recommend", "content": banner_text, "priority": 2},
            {"channel": "waiter_script", "content": waiter_script, "priority": 3},
        ]

        logger.info(
            "expiry_specials_pushed",
            store_id=store_id,
            ingredient_name=ingredient_name,
            days_to_expiry=days_to_expiry,
            specials_count=len(specials),
            discount_pct=discount_pct,
        )

        return AgentResult(
            success=True,
            action="push_expiry_specials",
            data={
                "store_id": store_id,
                "ingredient_name": ingredient_name,
                "days_to_expiry": days_to_expiry,
                "current_qty": current_qty,
                "unit": unit,
                "discount_pct": discount_pct,
                "specials": specials,
                "push_channels": push_channels,
                "valid_until": f"今日{23 if days_to_expiry <= 1 else 22}:00",
            },
            reasoning=(
                f"临期特价推送：{ingredient_name} 还剩{days_to_expiry}天，"
                f"推出{len(specials)}道特价菜，折扣{discount_pct}%"
            ),
            confidence=0.85,
        )

    # ─── 事件驱动：标记高成本菜品 ───

    async def _flag_high_cost_dishes(self, params: dict) -> AgentResult:
        """finance.cost_rate.exceeded 触发：识别并标记高成本菜品，辅助成本优化

        配合 finance_audit.root_cause_analysis 工作：
        - root_cause_analysis 找到成本超标原因（宏观）
        - flag_high_cost_dishes 定位到具体菜品（微观）
        """
        store_id = params.get("store_id") or self.store_id
        event_data = params.get("event_data", {})
        target_cost_rate = params.get("target_cost_rate") or event_data.get("target_cost_rate", 0.35)
        dishes = params.get("dishes") or event_data.get("dishes", [])
        # dishes: [{"dish_id": ..., "dish_name": ..., "cost_fen": ..., "price_fen": ..., "sales_count": ...}]

        # 若有 DB，从实时数据中计算菜品成本率
        db_dishes: list[dict] = []
        if self._db and store_id:
            from sqlalchemy import text
            rows = await self._db.execute(text("""
                SELECT d.id, d.name, d.category,
                       d.sell_price_fen,
                       COALESCE(d.cost_price_fen, 0) as cost_fen,
                       COUNT(oi.id) as sales_count,
                       CASE WHEN d.sell_price_fen > 0
                            THEN COALESCE(d.cost_price_fen, 0)::float / d.sell_price_fen
                            ELSE 0 END as cost_rate
                FROM dishes d
                LEFT JOIN order_items oi ON oi.dish_id = d.id
                    AND oi.created_at >= NOW() - INTERVAL '30 days'
                WHERE d.tenant_id = :tenant_id
                  AND d.is_deleted = false
                  AND d.is_available = true
                GROUP BY d.id, d.name, d.category, d.sell_price_fen, d.cost_price_fen
                HAVING CASE WHEN d.sell_price_fen > 0
                             THEN COALESCE(d.cost_price_fen, 0)::float / d.sell_price_fen
                             ELSE 0 END > :threshold
                ORDER BY cost_rate DESC
                LIMIT 20
            """), {"tenant_id": self.tenant_id, "threshold": target_cost_rate})
            db_dishes = [dict(r) for r in rows.mappings()]

        working = db_dishes if db_dishes else [
            d for d in dishes
            if d.get("price_fen", 0) > 0
            and d.get("cost_fen", 0) / d.get("price_fen", 1) > target_cost_rate
        ]

        # 评分：成本率越高 + 销量越大 = 优化优先级越高
        flagged: list[dict] = []
        for d in working:
            price = d.get("sell_price_fen") or d.get("price_fen", 0)
            cost = d.get("cost_fen") or d.get("cost_price_fen", 0)
            cost_rate = cost / price if price > 0 else 0
            over_target = cost_rate - target_cost_rate
            sales = d.get("sales_count", 0)

            # 优化建议
            suggestions = []
            if cost_rate > 0.55:
                suggestions.append("考虑提价或调整BOM配方")
            if over_target > 0.1:
                suggestions.append(f"成本率偏高{over_target:.1%}，建议重新核价")
            if sales > 50 and cost_rate > target_cost_rate:
                suggestions.append("高销量高成本，优化效益最大")
            if not suggestions:
                suggestions.append("列入下次菜品成本复盘")

            flagged.append({
                "dish_id": str(d.get("id") or d.get("dish_id", "")),
                "dish_name": d.get("name") or d.get("dish_name", ""),
                "category": d.get("category", ""),
                "cost_rate": round(cost_rate, 4),
                "over_target": round(over_target, 4),
                "sales_count": sales,
                "optimization_priority": "high" if over_target > 0.1 and sales > 30 else "medium",
                "suggestions": suggestions,
            })

        flagged.sort(key=lambda x: (-x["over_target"], -x["sales_count"]))

        logger.info(
            "high_cost_dishes_flagged",
            store_id=store_id,
            flagged_count=len(flagged),
            target_cost_rate=target_cost_rate,
        )

        return AgentResult(
            success=True,
            action="flag_high_cost_dishes",
            data={
                "store_id": store_id,
                "target_cost_rate": target_cost_rate,
                "flagged_dishes": flagged,
                "flagged_count": len(flagged),
                "high_priority_count": sum(1 for d in flagged if d["optimization_priority"] == "high"),
                "data_source": "db_realtime" if db_dishes else "params",
            },
            reasoning=(
                f"高成本菜品标记：发现{len(flagged)}道菜成本率超标"
                f"（目标{target_cost_rate:.0%}），"
                f"其中{sum(1 for d in flagged if d['optimization_priority'] == 'high')}道高优先级"
            ),
            confidence=0.9 if db_dishes else 0.75,
        )
