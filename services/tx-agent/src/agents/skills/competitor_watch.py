"""竞对动态监测 Agent — P1 | 云端

扫描竞对最新动态、检测价格变动、检测新品上线、检测营销活动、生成威胁预警、对比品牌定位、生成周报。
"""
from typing import Any
from ..base import SkillAgent, AgentResult


# 竞对监测维度
MONITOR_DIMENSIONS = ["价格", "新品", "营销活动", "门店扩张", "服务变化", "评分变化"]

# 威胁等级
THREAT_LEVELS = {
    "critical": {"name": "严重威胁", "response_hours": 24},
    "high": {"name": "高度关注", "response_hours": 48},
    "medium": {"name": "一般关注", "response_hours": 168},
    "low": {"name": "持续跟踪", "response_hours": 336},
}


class CompetitorWatchAgent(SkillAgent):
    agent_id = "competitor_watch"
    agent_name = "竞对动态监测"
    description = "竞对动态扫描、价格变动检测、新品上线检测、营销活动检测、威胁预警、品牌定位对比、竞对周报"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "scan_competitor_updates",
            "detect_price_change",
            "detect_new_product",
            "detect_campaign",
            "generate_threat_alert",
            "compare_positioning",
            "summarize_weekly",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "scan_competitor_updates": self._scan_updates,
            "detect_price_change": self._detect_price_change,
            "detect_new_product": self._detect_new_product,
            "detect_campaign": self._detect_campaign,
            "generate_threat_alert": self._generate_alert,
            "compare_positioning": self._compare_positioning,
            "summarize_weekly": self._summarize_weekly,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _scan_updates(self, params: dict) -> AgentResult:
        """扫描竞对最新动态"""
        competitors = params.get("competitors", [])
        updates = []

        for comp in competitors:
            name = comp.get("name", "")
            events = comp.get("recent_events", [])
            for event in events:
                updates.append({
                    "competitor": name,
                    "event_type": event.get("type", "other"),
                    "title": event.get("title", ""),
                    "detail": event.get("detail", ""),
                    "source": event.get("source", "公开渠道"),
                    "date": event.get("date", ""),
                    "impact_level": self._assess_impact(event),
                })

        updates.sort(key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x["impact_level"], 4))

        return AgentResult(
            success=True, action="scan_competitor_updates",
            data={
                "updates": updates[:30],
                "total": len(updates),
                "competitors_scanned": len(competitors),
                "critical_count": sum(1 for u in updates if u["impact_level"] == "critical"),
            },
            reasoning=f"扫描 {len(competitors)} 个竞对，发现 {len(updates)} 条动态，"
                      f"严重 {sum(1 for u in updates if u['impact_level'] == 'critical')} 条",
            confidence=0.75,
        )

    @staticmethod
    def _assess_impact(event: dict) -> str:
        event_type = event.get("type", "")
        if event_type in ("price_drop_major", "store_expansion", "aggressive_campaign"):
            return "critical"
        if event_type in ("price_drop", "new_product_hit", "campaign"):
            return "high"
        if event_type in ("new_product", "service_change", "rating_change"):
            return "medium"
        return "low"

    async def _detect_price_change(self, params: dict) -> AgentResult:
        """检测竞对价格变动"""
        competitor_prices = params.get("competitor_prices", [])
        our_prices = params.get("our_prices", {})
        alerts = []

        for cp in competitor_prices:
            competitor = cp.get("competitor", "")
            dish = cp.get("dish", "")
            old_price = cp.get("old_price_fen", 0)
            new_price = cp.get("new_price_fen", 0)

            if old_price <= 0:
                continue
            change_pct = round((new_price - old_price) / old_price * 100, 1)

            our_price = our_prices.get(dish, 0)
            price_gap_pct = round((our_price - new_price) / max(1, new_price) * 100, 1) if our_price else 0

            if abs(change_pct) >= 5:
                alerts.append({
                    "competitor": competitor,
                    "dish": dish,
                    "old_price_yuan": round(old_price / 100, 2),
                    "new_price_yuan": round(new_price / 100, 2),
                    "change_pct": change_pct,
                    "our_price_yuan": round(our_price / 100, 2) if our_price else None,
                    "price_gap_pct": price_gap_pct,
                    "direction": "降价" if change_pct < 0 else "涨价",
                    "threat": "高" if change_pct <= -15 and price_gap_pct > 20 else "中" if change_pct <= -10 else "低",
                })

        alerts.sort(key=lambda x: x["change_pct"])

        return AgentResult(
            success=True, action="detect_price_change",
            data={"alerts": alerts, "total": len(alerts),
                  "price_drops": sum(1 for a in alerts if a["direction"] == "降价"),
                  "price_increases": sum(1 for a in alerts if a["direction"] == "涨价")},
            reasoning=f"检测到 {len(alerts)} 个竞对价格变动，降价 {sum(1 for a in alerts if a['direction'] == '降价')} 个",
            confidence=0.8,
        )

    async def _detect_new_product(self, params: dict) -> AgentResult:
        """检测竞对新品上线"""
        competitor_products = params.get("competitor_products", [])
        our_menu = params.get("our_menu", [])

        new_products = []
        for cp in competitor_products:
            if cp.get("is_new"):
                overlap = cp.get("dish_name", "") in our_menu
                new_products.append({
                    "competitor": cp.get("competitor", ""),
                    "dish_name": cp.get("dish_name", ""),
                    "category": cp.get("category", ""),
                    "price_yuan": round(cp.get("price_fen", 0) / 100, 2),
                    "launch_date": cp.get("launch_date", ""),
                    "popularity": cp.get("popularity", "未知"),
                    "we_have_similar": overlap,
                    "recommendation": "跟进研发" if not overlap and cp.get("popularity") == "热卖" else "持续观察",
                })

        return AgentResult(
            success=True, action="detect_new_product",
            data={"new_products": new_products, "total": len(new_products),
                  "hot_items": sum(1 for p in new_products if p["popularity"] == "热卖"),
                  "need_follow_up": sum(1 for p in new_products if p["recommendation"] == "跟进研发")},
            reasoning=f"检测到 {len(new_products)} 个竞对新品，{sum(1 for p in new_products if p['popularity'] == '热卖')} 个热卖",
            confidence=0.75,
        )

    async def _detect_campaign(self, params: dict) -> AgentResult:
        """检测竞对营销活动"""
        campaigns = params.get("competitor_campaigns", [])
        detected = []

        for c in campaigns:
            detected.append({
                "competitor": c.get("competitor", ""),
                "campaign_name": c.get("name", ""),
                "type": c.get("type", "促销"),
                "channels": c.get("channels", []),
                "estimated_discount": c.get("discount_pct", 0),
                "start_date": c.get("start_date", ""),
                "end_date": c.get("end_date", ""),
                "target_audience": c.get("target", "全部"),
                "threat_level": "high" if c.get("discount_pct", 0) >= 30 else "medium" if c.get("discount_pct", 0) >= 15 else "low",
            })

        return AgentResult(
            success=True, action="detect_campaign",
            data={"campaigns": detected, "total": len(detected),
                  "high_threat": sum(1 for d in detected if d["threat_level"] == "high")},
            reasoning=f"检测到 {len(detected)} 个竞对营销活动，高威胁 {sum(1 for d in detected if d['threat_level'] == 'high')} 个",
            confidence=0.7,
        )

    async def _generate_alert(self, params: dict) -> AgentResult:
        """生成竞争威胁预警"""
        events = params.get("events", [])
        alerts = []

        for e in events:
            threat = e.get("threat_level", "low")
            threat_info = THREAT_LEVELS.get(threat, THREAT_LEVELS["low"])
            alerts.append({
                "competitor": e.get("competitor", ""),
                "event": e.get("event", ""),
                "threat_level": threat,
                "threat_name": threat_info["name"],
                "response_deadline_hours": threat_info["response_hours"],
                "suggested_response": e.get("suggested_response", "持续观察"),
                "affected_stores": e.get("affected_stores", []),
            })

        alerts.sort(key=lambda x: THREAT_LEVELS.get(x["threat_level"], {}).get("response_hours", 999))

        return AgentResult(
            success=True, action="generate_threat_alert",
            data={"alerts": alerts, "total": len(alerts),
                  "critical_count": sum(1 for a in alerts if a["threat_level"] == "critical")},
            reasoning=f"生成 {len(alerts)} 条竞争预警，严重 {sum(1 for a in alerts if a['threat_level'] == 'critical')} 条",
            confidence=0.75,
        )

    async def _compare_positioning(self, params: dict) -> AgentResult:
        """对比品牌定位差异"""
        our_brand = params.get("our_brand", {})
        competitors = params.get("competitors", [])

        comparisons = []
        for comp in competitors:
            comparison = {
                "competitor": comp.get("name", ""),
                "dimensions": {
                    "avg_ticket_yuan": {
                        "ours": round(our_brand.get("avg_ticket_fen", 0) / 100, 2),
                        "theirs": round(comp.get("avg_ticket_fen", 0) / 100, 2),
                    },
                    "rating": {
                        "ours": our_brand.get("rating", 0),
                        "theirs": comp.get("rating", 0),
                    },
                    "store_count": {
                        "ours": our_brand.get("store_count", 0),
                        "theirs": comp.get("store_count", 0),
                    },
                    "review_count": {
                        "ours": our_brand.get("review_count", 0),
                        "theirs": comp.get("review_count", 0),
                    },
                },
                "positioning_gap": comp.get("positioning", "同级竞品"),
            }
            # 计算综合优势
            advantages = 0
            for dim, val in comparison["dimensions"].items():
                if val["ours"] > val["theirs"]:
                    advantages += 1
            comparison["our_advantage_count"] = advantages
            comparison["competitive_status"] = "领先" if advantages >= 3 else "均势" if advantages >= 2 else "落后"
            comparisons.append(comparison)

        return AgentResult(
            success=True, action="compare_positioning",
            data={"comparisons": comparisons, "total_competitors": len(comparisons)},
            reasoning=f"对比 {len(comparisons)} 个竞品定位，"
                      f"领先 {sum(1 for c in comparisons if c['competitive_status'] == '领先')} 个",
            confidence=0.7,
        )

    async def _summarize_weekly(self, params: dict) -> AgentResult:
        """生成竞对周报摘要"""
        week_data = params.get("week_data", {})
        price_changes = week_data.get("price_changes", [])
        new_products = week_data.get("new_products", [])
        campaigns = week_data.get("campaigns", [])
        store_changes = week_data.get("store_changes", [])

        summary_points = []
        if price_changes:
            summary_points.append(f"价格变动: {len(price_changes)} 项，"
                                 f"降价 {sum(1 for p in price_changes if p.get('direction') == '降价')} 项")
        if new_products:
            summary_points.append(f"新品上线: {len(new_products)} 个")
        if campaigns:
            summary_points.append(f"营销活动: {len(campaigns)} 场")
        if store_changes:
            summary_points.append(f"门店变动: {len(store_changes)} 处")

        return AgentResult(
            success=True, action="summarize_weekly",
            data={
                "summary_points": summary_points,
                "price_changes_count": len(price_changes),
                "new_products_count": len(new_products),
                "campaigns_count": len(campaigns),
                "store_changes_count": len(store_changes),
                "overall_threat": "升高" if len(price_changes) + len(campaigns) >= 5 else "平稳",
                "top_actions": [
                    "关注竞对降价菜品的毛利对比" if price_changes else None,
                    "评估竞对新品是否需要跟进" if new_products else None,
                    "制定应对竞对营销的策略" if campaigns else None,
                ],
            },
            reasoning=f"竞对周报: {', '.join(summary_points) if summary_points else '本周无重大动态'}",
            confidence=0.8,
        )
