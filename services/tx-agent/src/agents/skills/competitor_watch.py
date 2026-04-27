"""竞对动态监测 Agent — P1 | 云端

扫描竞对最新动态、检测价格变动、检测新品上线、检测营销活动、生成威胁预警、对比品牌定位、生成周报。
新增：generate_weekly_intel_report — 整合竞对快照+点评+市场信号生成结构化周报。
"""

from datetime import date, timedelta
from typing import Any

from ..base import AgentResult, SkillAgent

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

    # Sprint D1 / PR Overflow：纯竞对扫描与威胁预警，不触发业务决策，豁免
    constraint_scope = set()
    constraint_waived_reason = (
        "竞对动态监测纯数据扫描与威胁预警报告，输出供市场团队决策参考，不直接操作毛利/食安/客户体验三条业务约束维度"
    )

    def get_supported_actions(self) -> list[str]:
        return [
            "scan_competitor_updates",
            "detect_price_change",
            "detect_new_product",
            "detect_campaign",
            "generate_threat_alert",
            "compare_positioning",
            "summarize_weekly",
            "generate_weekly_intel_report",
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
            "generate_weekly_intel_report": self._generate_weekly_intel_report,
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
                updates.append(
                    {
                        "competitor": name,
                        "event_type": event.get("type", "other"),
                        "title": event.get("title", ""),
                        "detail": event.get("detail", ""),
                        "source": event.get("source", "公开渠道"),
                        "date": event.get("date", ""),
                        "impact_level": self._assess_impact(event),
                    }
                )

        updates.sort(key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x["impact_level"], 4))

        return AgentResult(
            success=True,
            action="scan_competitor_updates",
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
                alerts.append(
                    {
                        "competitor": competitor,
                        "dish": dish,
                        "old_price_yuan": round(old_price / 100, 2),
                        "new_price_yuan": round(new_price / 100, 2),
                        "change_pct": change_pct,
                        "our_price_yuan": round(our_price / 100, 2) if our_price else None,
                        "price_gap_pct": price_gap_pct,
                        "direction": "降价" if change_pct < 0 else "涨价",
                        "threat": "高"
                        if change_pct <= -15 and price_gap_pct > 20
                        else "中"
                        if change_pct <= -10
                        else "低",
                    }
                )

        alerts.sort(key=lambda x: x["change_pct"])

        return AgentResult(
            success=True,
            action="detect_price_change",
            data={
                "alerts": alerts,
                "total": len(alerts),
                "price_drops": sum(1 for a in alerts if a["direction"] == "降价"),
                "price_increases": sum(1 for a in alerts if a["direction"] == "涨价"),
            },
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
                new_products.append(
                    {
                        "competitor": cp.get("competitor", ""),
                        "dish_name": cp.get("dish_name", ""),
                        "category": cp.get("category", ""),
                        "price_yuan": round(cp.get("price_fen", 0) / 100, 2),
                        "launch_date": cp.get("launch_date", ""),
                        "popularity": cp.get("popularity", "未知"),
                        "we_have_similar": overlap,
                        "recommendation": "跟进研发" if not overlap and cp.get("popularity") == "热卖" else "持续观察",
                    }
                )

        return AgentResult(
            success=True,
            action="detect_new_product",
            data={
                "new_products": new_products,
                "total": len(new_products),
                "hot_items": sum(1 for p in new_products if p["popularity"] == "热卖"),
                "need_follow_up": sum(1 for p in new_products if p["recommendation"] == "跟进研发"),
            },
            reasoning=f"检测到 {len(new_products)} 个竞对新品，{sum(1 for p in new_products if p['popularity'] == '热卖')} 个热卖",
            confidence=0.75,
        )

    async def _detect_campaign(self, params: dict) -> AgentResult:
        """检测竞对营销活动"""
        campaigns = params.get("competitor_campaigns", [])
        detected = []

        for c in campaigns:
            detected.append(
                {
                    "competitor": c.get("competitor", ""),
                    "campaign_name": c.get("name", ""),
                    "type": c.get("type", "促销"),
                    "channels": c.get("channels", []),
                    "estimated_discount": c.get("discount_pct", 0),
                    "start_date": c.get("start_date", ""),
                    "end_date": c.get("end_date", ""),
                    "target_audience": c.get("target", "全部"),
                    "threat_level": "high"
                    if c.get("discount_pct", 0) >= 30
                    else "medium"
                    if c.get("discount_pct", 0) >= 15
                    else "low",
                }
            )

        return AgentResult(
            success=True,
            action="detect_campaign",
            data={
                "campaigns": detected,
                "total": len(detected),
                "high_threat": sum(1 for d in detected if d["threat_level"] == "high"),
            },
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
            alerts.append(
                {
                    "competitor": e.get("competitor", ""),
                    "event": e.get("event", ""),
                    "threat_level": threat,
                    "threat_name": threat_info["name"],
                    "response_deadline_hours": threat_info["response_hours"],
                    "suggested_response": e.get("suggested_response", "持续观察"),
                    "affected_stores": e.get("affected_stores", []),
                }
            )

        alerts.sort(key=lambda x: THREAT_LEVELS.get(x["threat_level"], {}).get("response_hours", 999))

        return AgentResult(
            success=True,
            action="generate_threat_alert",
            data={
                "alerts": alerts,
                "total": len(alerts),
                "critical_count": sum(1 for a in alerts if a["threat_level"] == "critical"),
            },
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
            success=True,
            action="compare_positioning",
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
            summary_points.append(
                f"价格变动: {len(price_changes)} 项，"
                f"降价 {sum(1 for p in price_changes if p.get('direction') == '降价')} 项"
            )
        if new_products:
            summary_points.append(f"新品上线: {len(new_products)} 个")
        if campaigns:
            summary_points.append(f"营销活动: {len(campaigns)} 场")
        if store_changes:
            summary_points.append(f"门店变动: {len(store_changes)} 处")

        return AgentResult(
            success=True,
            action="summarize_weekly",
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

    async def _generate_weekly_intel_report(self, params: dict) -> AgentResult:
        """
        整合竞对快照 + 点评情报 + 市场趋势信号，生成结构化竞对情报周报。

        params 结构：
          - tenant_id: str                    — 租户 ID
          - competitor_snapshots: list[dict]  — 本周竞对快照列表（来自 competitor_snapshots 表）
          - own_reviews: list[dict]           — 自家门店本周点评（来自 review_intel 表）
          - competitor_reviews: list[dict]    — 竞对本周点评（来自 review_intel 表）
          - market_trends: list[dict]         — 市场趋势信号（来自 market_trend_signals 表）
          - week_start: str (ISO date)        — 周报开始日期，默认7天前
          - week_end: str (ISO date)          — 周报结束日期，默认今天
        """
        tenant_id_str: str = params.get("tenant_id", "")
        snapshots: list[dict] = params.get("competitor_snapshots", [])
        own_reviews: list[dict] = params.get("own_reviews", [])
        competitor_reviews: list[dict] = params.get("competitor_reviews", [])
        market_trends: list[dict] = params.get("market_trends", [])
        week_end_str: str = params.get("week_end", date.today().isoformat())
        week_start_str: str = params.get("week_start", (date.today() - timedelta(days=7)).isoformat())

        # ── 1. 竞对快照分析 ──
        snapshot_summary = _analyze_snapshots(snapshots)

        # ── 2. 点评情感对比 ──
        review_summary = _analyze_reviews(own_reviews, competitor_reviews)

        # ── 3. 市场趋势摘要 ──
        trend_summary = _analyze_trends(market_trends)

        # ── 4. 综合威胁评估 ──
        threat_score = _calculate_threat_score(snapshot_summary, review_summary, trend_summary)
        threat_level = (
            "critical"
            if threat_score >= 75
            else "high"
            if threat_score >= 50
            else "medium"
            if threat_score >= 25
            else "low"
        )

        # ── 5. 生成行动建议 ──
        recommended_actions = _generate_recommended_actions(
            snapshot_summary, review_summary, trend_summary, threat_level
        )

        report: dict[str, Any] = {
            "report_type": "weekly_intel",
            "tenant_id": tenant_id_str,
            "period": {"start": week_start_str, "end": week_end_str},
            "threat_level": threat_level,
            "threat_score": threat_score,
            # 竞对动态
            "competitor_summary": snapshot_summary,
            # 口碑对比
            "review_summary": review_summary,
            # 市场趋势
            "trend_summary": trend_summary,
            # 综合建议
            "recommended_actions": recommended_actions,
            # 统计
            "stats": {
                "competitors_tracked": len({s.get("competitor_brand_id") for s in snapshots}),
                "own_reviews_analyzed": len(own_reviews),
                "competitor_reviews_analyzed": len(competitor_reviews),
                "trend_signals_captured": len(market_trends),
            },
            "generated_at": date.today().isoformat(),
        }

        reasoning_parts = [f"威胁评分 {threat_score}/100（{threat_level}）"]
        if snapshot_summary.get("rating_dropped_competitors"):
            reasoning_parts.append(f"{len(snapshot_summary['rating_dropped_competitors'])} 个竞对评分下降")
        if snapshot_summary.get("rating_raised_competitors"):
            reasoning_parts.append(f"{len(snapshot_summary['rating_raised_competitors'])} 个竞对评分上升（需关注）")
        if review_summary.get("own_avg_sentiment") is not None:
            own_sent = review_summary["own_avg_sentiment"]
            reasoning_parts.append(f"自家情感均分 {own_sent:.2f}")
        if trend_summary.get("rising_keywords"):
            reasoning_parts.append(f"上升趋势关键词 {len(trend_summary['rising_keywords'])} 个")

        return AgentResult(
            success=True,
            action="generate_weekly_intel_report",
            data=report,
            reasoning="周报摘要: " + "；".join(reasoning_parts),
            confidence=0.78,
        )


# ─── 周报生成辅助函数 ───


def _analyze_snapshots(snapshots: list[dict]) -> dict[str, Any]:
    """分析竞对快照变化"""
    if not snapshots:
        return {
            "total_snapshots": 0,
            "rating_raised_competitors": [],
            "rating_dropped_competitors": [],
            "new_promotions": [],
            "avg_rating_change": 0.0,
        }

    # 按 competitor_brand_id 分组，取最新和次新快照对比
    from collections import defaultdict

    brand_snaps: dict[str, list[dict]] = defaultdict(list)
    for snap in snapshots:
        brand_snaps[snap.get("competitor_brand_id", "")].append(snap)

    rating_raised: list[dict] = []
    rating_dropped: list[dict] = []
    new_promotions: list[dict] = []

    for brand_id, snaps in brand_snaps.items():
        snaps_sorted = sorted(snaps, key=lambda x: x.get("snapshot_date", ""))
        if len(snaps_sorted) >= 2:
            latest = snaps_sorted[-1]
            prev = snaps_sorted[-2]
            old_r = float(prev.get("avg_rating") or 0)
            new_r = float(latest.get("avg_rating") or 0)
            if old_r > 0 and abs(new_r - old_r) >= 0.1:
                entry = {
                    "competitor_brand_id": brand_id,
                    "old_rating": old_r,
                    "new_rating": new_r,
                    "delta": round(new_r - old_r, 2),
                }
                if new_r > old_r:
                    rating_raised.append(entry)
                else:
                    rating_dropped.append(entry)

        # 收集活跃促销
        latest_snap = snaps_sorted[-1] if snaps_sorted else {}
        promotions = latest_snap.get("active_promotions") or []
        if promotions:
            new_promotions.extend([{"competitor_brand_id": brand_id, **p} for p in promotions[:3]])

    return {
        "total_snapshots": len(snapshots),
        "brands_tracked": len(brand_snaps),
        "rating_raised_competitors": rating_raised,
        "rating_dropped_competitors": rating_dropped,
        "new_promotions": new_promotions[:10],
        "avg_rating_change": (
            round(
                sum(e["delta"] for e in rating_raised + rating_dropped)
                / max(1, len(rating_raised) + len(rating_dropped)),
                2,
            )
            if (rating_raised or rating_dropped)
            else 0.0
        ),
    }


def _analyze_reviews(
    own_reviews: list[dict],
    competitor_reviews: list[dict],
) -> dict[str, Any]:
    """分析自家和竞对点评情感对比"""

    def avg_sentiment(reviews: list[dict]) -> float | None:
        scores = [float(r["sentiment_score"]) for r in reviews if r.get("sentiment_score") is not None]
        return round(sum(scores) / len(scores), 3) if scores else None

    def avg_rating(reviews: list[dict]) -> float | None:
        ratings = [float(r["rating"]) for r in reviews if r.get("rating") is not None]
        return round(sum(ratings) / len(ratings), 2) if ratings else None

    own_sent = avg_sentiment(own_reviews)
    comp_sent = avg_sentiment(competitor_reviews)
    own_rat = avg_rating(own_reviews)
    comp_rat = avg_rating(competitor_reviews)

    # 提取高频负面主题
    negative_topics: dict[str, int] = {}
    for review in own_reviews:
        for topic in review.get("topics") or []:
            if isinstance(topic, dict) and topic.get("sentiment") == "negative":
                t = topic.get("topic", "")
                if t:
                    negative_topics[t] = negative_topics.get(t, 0) + 1

    top_negative = sorted(negative_topics.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "own_review_count": len(own_reviews),
        "competitor_review_count": len(competitor_reviews),
        "own_avg_sentiment": own_sent,
        "competitor_avg_sentiment": comp_sent,
        "own_avg_rating": own_rat,
        "competitor_avg_rating": comp_rat,
        "sentiment_gap": (
            round(float(own_sent) - float(comp_sent), 3) if own_sent is not None and comp_sent is not None else None
        ),
        "top_negative_topics": [{"topic": t, "count": c} for t, c in top_negative],
        "sentiment_trend": (
            "领先竞对"
            if own_sent and comp_sent and own_sent > comp_sent
            else "落后竞对"
            if own_sent and comp_sent and own_sent < comp_sent
            else "持平"
        ),
    }


def _analyze_trends(market_trends: list[dict]) -> dict[str, Any]:
    """分析市场趋势信号"""
    if not market_trends:
        return {
            "total_signals": 0,
            "rising_keywords": [],
            "declining_keywords": [],
            "top_dish_trends": [],
        }

    rising = [t for t in market_trends if t.get("trend_direction") == "rising"]
    declining = [t for t in market_trends if t.get("trend_direction") == "declining"]
    dish_trends = [t for t in market_trends if t.get("signal_type") == "dish_trend"]

    return {
        "total_signals": len(market_trends),
        "rising_keywords": [
            {"keyword": t.get("keyword"), "score": t.get("trend_score"), "region": t.get("region")}
            for t in sorted(rising, key=lambda x: float(x.get("trend_score") or 0), reverse=True)[:10]
        ],
        "declining_keywords": [
            {"keyword": t.get("keyword"), "score": t.get("trend_score"), "region": t.get("region")}
            for t in sorted(declining, key=lambda x: float(x.get("trend_score") or 0))[:5]
        ],
        "top_dish_trends": [
            {"keyword": t.get("keyword"), "score": t.get("trend_score"), "category": t.get("category")}
            for t in sorted(dish_trends, key=lambda x: float(x.get("trend_score") or 0), reverse=True)[:10]
        ],
        "rising_count": len(rising),
        "declining_count": len(declining),
    }


def _calculate_threat_score(
    snapshot_summary: dict,
    review_summary: dict,
    trend_summary: dict,
) -> int:
    """计算综合威胁评分（0-100）"""
    score = 0

    # 竞对评分上升（最高 35 分）
    raised = len(snapshot_summary.get("rating_raised_competitors", []))
    score += min(35, raised * 10)

    # 自家情感分低于竞对（最高 25 分）
    sent_gap = review_summary.get("sentiment_gap")
    if sent_gap is not None and sent_gap < 0:
        score += min(25, int(abs(sent_gap) * 50))

    # 竞对活跃促销（最高 20 分）
    promotions = len(snapshot_summary.get("new_promotions", []))
    score += min(20, promotions * 4)

    # 上升趋势信号强度（最高 20 分）
    rising = trend_summary.get("rising_count", 0)
    score += min(20, rising * 2)

    return min(100, score)


def _generate_recommended_actions(
    snapshot_summary: dict,
    review_summary: dict,
    trend_summary: dict,
    threat_level: str,
) -> list[dict[str, Any]]:
    """根据分析结果生成优先行动建议"""
    actions: list[dict[str, Any]] = []

    if snapshot_summary.get("rating_raised_competitors"):
        count = len(snapshot_summary["rating_raised_competitors"])
        actions.append(
            {
                "priority": "high",
                "action": f"重点调研 {count} 个评分上升竞对的改进举措，制定跟进计划",
                "source": "competitor_snapshot",
            }
        )

    if snapshot_summary.get("new_promotions"):
        actions.append(
            {
                "priority": "high",
                "action": "竞对有活跃促销活动，评估是否需要制定应对营销方案",
                "source": "competitor_snapshot",
            }
        )

    top_negative = review_summary.get("top_negative_topics", [])
    if top_negative:
        top_issue = top_negative[0]["topic"]
        actions.append(
            {
                "priority": "medium",
                "action": f"自家门店「{top_issue}」被客户多次负面提及，安排专项改善",
                "source": "review_intel",
            }
        )

    sent_gap = review_summary.get("sentiment_gap")
    if sent_gap is not None and sent_gap < -0.1:
        actions.append(
            {
                "priority": "medium",
                "action": f"客户情感得分低于竞对 {abs(sent_gap):.2f}，开展服务品质专项提升",
                "source": "review_intel",
            }
        )

    rising_keywords = trend_summary.get("rising_keywords", [])
    if rising_keywords:
        top_kw = rising_keywords[0]["keyword"]
        actions.append(
            {
                "priority": "low",
                "action": f"市场趋势「{top_kw}」热度上升，研发团队可评估新品研发机会",
                "source": "market_trend",
            }
        )

    if not actions:
        actions.append(
            {
                "priority": "low",
                "action": "本周竞争态势平稳，维持常规监测频率",
                "source": "system",
            }
        )

    return actions
