"""情报周报生成 Agent — P1 | 云端

生成竞对周报、需求变化周报、新品趋势周报、原料趋势周报、商圈情报周报、月度报告、自定义报告。
"""

from typing import Any

from ..base import AgentResult, SkillAgent


class IntelReporterAgent(SkillAgent):
    agent_id = "intel_reporter"
    agent_name = "情报周报生成"
    description = "竞对周报、需求周报、新品周报、原料周报、商圈周报、月度报告、自定义报告"
    priority = "P1"
    run_location = "cloud"

    # Sprint D1 / PR 批次 6：纯情报汇总报告，不触发业务决策，豁免
    constraint_scope = set()
    constraint_waived_reason = (
        "情报周报生成纯数据汇总与报告输出（竞对/需求/新品/原料/商圈），"
        "不直接操作毛利/食安/客户体验三条业务约束维度"
    )

    def get_supported_actions(self) -> list[str]:
        return [
            "generate_competitor_weekly",
            "generate_demand_weekly",
            "generate_product_weekly",
            "generate_ingredient_weekly",
            "generate_district_weekly",
            "generate_monthly_report",
            "generate_custom_report",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "generate_competitor_weekly": self._competitor_weekly,
            "generate_demand_weekly": self._demand_weekly,
            "generate_product_weekly": self._product_weekly,
            "generate_ingredient_weekly": self._ingredient_weekly,
            "generate_district_weekly": self._district_weekly,
            "generate_monthly_report": self._monthly_report,
            "generate_custom_report": self._custom_report,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _competitor_weekly(self, params: dict) -> AgentResult:
        """生成竞对周报"""
        week = params.get("week", "")
        competitors = params.get("competitors", [])
        price_changes = params.get("price_changes", [])
        new_products = params.get("new_products", [])
        campaigns = params.get("campaigns", [])
        store_changes = params.get("store_changes", [])

        sections = []
        sections.append(
            {
                "title": "一、本周竞对动态概览",
                "content": f"本周监测 {len(competitors)} 个竞对品牌，"
                f"发现价格变动 {len(price_changes)} 项、新品上线 {len(new_products)} 个、"
                f"营销活动 {len(campaigns)} 场、门店变动 {len(store_changes)} 处。",
            }
        )

        if price_changes:
            sections.append(
                {
                    "title": "二、价格变动",
                    "content": f"本周 {len(price_changes)} 项价格变动，"
                    f"降价 {sum(1 for p in price_changes if p.get('direction') == '降价')} 项。",
                    "items": price_changes[:5],
                }
            )

        if new_products:
            sections.append(
                {
                    "title": "三、竞对新品",
                    "content": f"本周 {len(new_products)} 个新品上线。",
                    "items": new_products[:5],
                }
            )

        if campaigns:
            sections.append(
                {
                    "title": "四、营销活动",
                    "content": f"本周 {len(campaigns)} 场营销活动。",
                    "items": campaigns[:5],
                }
            )

        sections.append(
            {
                "title": "五、建议行动",
                "content": "根据本周竞对动态，建议重点关注以下事项。",
                "action_items": [
                    "关注竞对降价菜品对我方客流的影响" if price_changes else None,
                    "评估竞对新品是否需要跟进研发" if new_products else None,
                    "制定应对竞对促销的差异化策略" if campaigns else None,
                ],
            }
        )

        return AgentResult(
            success=True,
            action="generate_competitor_weekly",
            data={
                "week": week,
                "title": f"竞对动态周报 — {week}",
                "sections": sections,
                "summary_stats": {
                    "competitors_monitored": len(competitors),
                    "price_changes": len(price_changes),
                    "new_products": len(new_products),
                    "campaigns": len(campaigns),
                },
            },
            reasoning=f"生成竞对周报: {len(competitors)} 个品牌，{len(price_changes) + len(new_products) + len(campaigns)} 条动态",
            confidence=0.85,
        )

    async def _demand_weekly(self, params: dict) -> AgentResult:
        """生成需求变化周报"""
        week = params.get("week", "")
        search_trends = params.get("search_trends", [])
        review_trends = params.get("review_trends", [])
        order_trends = params.get("order_trends", [])

        rising_demands = [t for t in search_trends if t.get("trend") == "上升"]
        falling_demands = [t for t in search_trends if t.get("trend") == "下降"]

        sections = [
            {
                "title": "一、需求热度变化",
                "content": f"本周分析 {len(search_trends)} 个搜索关键词，"
                f"上升 {len(rising_demands)} 个，下降 {len(falling_demands)} 个。",
                "rising": [
                    {"keyword": r.get("keyword"), "growth_pct": r.get("growth_pct")} for r in rising_demands[:5]
                ],
                "falling": [
                    {"keyword": f.get("keyword"), "decline_pct": f.get("decline_pct")} for f in falling_demands[:5]
                ],
            },
            {
                "title": "二、顾客评论趋势",
                "content": f"本周 {len(review_trends)} 个评论主题有变化。",
                "items": review_trends[:5],
            },
            {
                "title": "三、点单偏好变化",
                "content": f"本周 {len(order_trends)} 个菜品点单趋势变化。",
                "items": order_trends[:5],
            },
        ]

        return AgentResult(
            success=True,
            action="generate_demand_weekly",
            data={
                "week": week,
                "title": f"需求变化周报 — {week}",
                "sections": sections,
                "key_insight": f"本周上升最快的需求: {rising_demands[0].get('keyword') if rising_demands else '无'}",
            },
            reasoning=f"生成需求周报: 上升{len(rising_demands)}个需求，下降{len(falling_demands)}个",
            confidence=0.8,
        )

    async def _product_weekly(self, params: dict) -> AgentResult:
        """生成新品趋势周报"""
        week = params.get("week", "")
        new_products = params.get("new_products", [])
        our_pipeline = params.get("our_pipeline", [])

        hot_products = [p for p in new_products if p.get("is_hot")]

        sections = [
            {
                "title": "一、本周新品动态",
                "content": f"市场新品 {len(new_products)} 个，热门 {len(hot_products)} 个。",
                "hot_products": hot_products[:5],
            },
            {
                "title": "二、我方研发进展",
                "content": f"在研新品 {len(our_pipeline)} 个。",
                "pipeline": our_pipeline[:5],
            },
            {
                "title": "三、新品机会建议",
                "content": "基于市场趋势，建议关注以下新品方向。",
                "suggestions": [p.get("dish_name") for p in hot_products if not p.get("we_have_similar")][:3],
            },
        ]

        return AgentResult(
            success=True,
            action="generate_product_weekly",
            data={
                "week": week,
                "title": f"新品趋势周报 — {week}",
                "sections": sections,
                "market_new_products": len(new_products),
                "hot_products": len(hot_products),
            },
            reasoning=f"新品周报: 市场新品 {len(new_products)} 个，热门 {len(hot_products)} 个",
            confidence=0.8,
        )

    async def _ingredient_weekly(self, params: dict) -> AgentResult:
        """生成原料趋势周报"""
        week = params.get("week", "")
        price_changes = params.get("price_changes", [])
        supply_alerts = params.get("supply_alerts", [])
        new_ingredients = params.get("new_ingredients", [])

        rising = [p for p in price_changes if p.get("change_pct", 0) > 0]
        falling = [p for p in price_changes if p.get("change_pct", 0) < 0]

        sections = [
            {
                "title": "一、原料价格变动",
                "content": f"涨价 {len(rising)} 种，降价 {len(falling)} 种。",
                "rising": rising[:5],
                "falling": falling[:5],
            },
            {
                "title": "二、供应预警",
                "content": f"本周 {len(supply_alerts)} 条供应预警。",
                "alerts": supply_alerts[:5],
            },
            {
                "title": "三、新原料信息",
                "content": f"发现 {len(new_ingredients)} 种新原料。",
                "items": new_ingredients[:3],
            },
        ]

        total_cost_impact_fen = sum(p.get("cost_impact_fen", 0) for p in price_changes)

        return AgentResult(
            success=True,
            action="generate_ingredient_weekly",
            data={
                "week": week,
                "title": f"原料趋势周报 — {week}",
                "sections": sections,
                "cost_impact_yuan": round(total_cost_impact_fen / 100, 2),
                "rising_count": len(rising),
                "falling_count": len(falling),
            },
            reasoning=f"原料周报: 涨价{len(rising)}种，降价{len(falling)}种，"
            f"成本影响 ¥{total_cost_impact_fen / 100:.0f}",
            confidence=0.8,
        )

    async def _district_weekly(self, params: dict) -> AgentResult:
        """生成商圈情报周报"""
        week = params.get("week", "")
        districts = params.get("districts", [])

        district_reports = []
        for d in districts:
            district_reports.append(
                {
                    "district_name": d.get("name", ""),
                    "traffic_change_pct": d.get("traffic_change_pct", 0),
                    "new_stores_opened": d.get("new_stores", 0),
                    "stores_closed": d.get("closed_stores", 0),
                    "avg_rating_change": d.get("rating_change", 0),
                    "our_store_rank": d.get("our_rank", 0),
                    "hot_events": d.get("events", []),
                }
            )

        growing = [d for d in district_reports if d["traffic_change_pct"] > 5]
        declining = [d for d in district_reports if d["traffic_change_pct"] < -5]

        return AgentResult(
            success=True,
            action="generate_district_weekly",
            data={
                "week": week,
                "title": f"商圈情报周报 — {week}",
                "districts": district_reports,
                "growing_districts": len(growing),
                "declining_districts": len(declining),
                "total_new_stores": sum(d["new_stores_opened"] for d in district_reports),
                "total_closed": sum(d["stores_closed"] for d in district_reports),
            },
            reasoning=f"商圈周报: {len(districts)}个商圈，增长{len(growing)}个，下降{len(declining)}个",
            confidence=0.8,
        )

    async def _monthly_report(self, params: dict) -> AgentResult:
        """生成月度市场报告"""
        month = params.get("month", "")
        competitor_summary = params.get("competitor_summary", {})
        demand_summary = params.get("demand_summary", {})
        product_summary = params.get("product_summary", {})
        ingredient_summary = params.get("ingredient_summary", {})
        district_summary = params.get("district_summary", {})

        report = {
            "title": f"月度市场情报报告 — {month}",
            "executive_summary": f"本月市场竞争{'加剧' if competitor_summary.get('threat_level') == '升高' else '平稳'}，"
            f"消费需求{demand_summary.get('overall_trend', '持平')}，"
            f"原料成本{ingredient_summary.get('cost_trend', '稳定')}。",
            "sections": [
                {"title": "竞争格局", "data": competitor_summary},
                {"title": "消费需求", "data": demand_summary},
                {"title": "新品动态", "data": product_summary},
                {"title": "原料行情", "data": ingredient_summary},
                {"title": "商圈变化", "data": district_summary},
            ],
            "strategic_recommendations": [
                "根据竞对动态调整定价策略" if competitor_summary.get("price_changes", 0) > 5 else None,
                "跟进市场热门新品研发" if product_summary.get("hot_products", 0) > 3 else None,
                "关注原料成本上涨风险" if ingredient_summary.get("rising_count", 0) > 10 else None,
            ],
        }

        return AgentResult(
            success=True,
            action="generate_monthly_report",
            data={"report": report, "month": month},
            reasoning=f"生成{month}月度市场报告，含5个模块",
            confidence=0.8,
        )

    async def _custom_report(self, params: dict) -> AgentResult:
        """生成自定义专题报告"""
        topic = params.get("topic", "")
        data_sources = params.get("data_sources", [])
        focus_areas = params.get("focus_areas", [])
        time_range = params.get("time_range", "")

        sections = []
        for area in focus_areas:
            matching_data = [d for d in data_sources if d.get("area") == area]
            sections.append(
                {
                    "title": area,
                    "data_points": len(matching_data),
                    "key_findings": [d.get("finding", "") for d in matching_data[:3]],
                    "data": matching_data[:5],
                }
            )

        report = {
            "title": f"专题报告: {topic}",
            "time_range": time_range,
            "sections": sections,
            "total_data_points": len(data_sources),
            "focus_areas": focus_areas,
            "conclusion": f"基于 {len(data_sources)} 个数据点分析，{topic}领域的关键发现如上。",
        }

        return AgentResult(
            success=True,
            action="generate_custom_report",
            data={"report": report},
            reasoning=f"生成专题报告「{topic}」，{len(focus_areas)} 个焦点，{len(data_sources)} 个数据点",
            confidence=0.75,
        )
