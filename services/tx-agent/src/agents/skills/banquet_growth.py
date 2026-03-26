"""宴会增长 Agent — P1 | 云端

宴会线索挖掘、宴会套餐推荐、宴会转化跟踪、宴会档期管理、宴会收益分析、宴会口碑管理。
"""
import uuid
from typing import Any
from ..base import SkillAgent, AgentResult


# 宴会类型及客单价参考
BANQUET_TYPES = {
    "wedding": {"name": "婚宴", "avg_per_table_fen": 200000, "min_tables": 10, "peak_months": [5, 6, 9, 10]},
    "birthday": {"name": "生日宴", "avg_per_table_fen": 120000, "min_tables": 3, "peak_months": list(range(1, 13))},
    "corporate": {"name": "商务宴请", "avg_per_table_fen": 180000, "min_tables": 2, "peak_months": [1, 3, 6, 12]},
    "baby_banquet": {"name": "满月/百日宴", "avg_per_table_fen": 150000, "min_tables": 5, "peak_months": list(range(1, 13))},
    "reunion": {"name": "家庭聚餐", "avg_per_table_fen": 100000, "min_tables": 2, "peak_months": [1, 2, 10]},
    "graduation": {"name": "升学/谢师宴", "avg_per_table_fen": 130000, "min_tables": 5, "peak_months": [6, 7, 8]},
}

# 套餐等级
PACKAGE_TIERS = {
    "standard": {"name": "标准套餐", "multiplier": 1.0},
    "premium": {"name": "精品套餐", "multiplier": 1.3},
    "luxury": {"name": "豪华套餐", "multiplier": 1.8},
}


class BanquetGrowthAgent(SkillAgent):
    agent_id = "banquet_growth"
    agent_name = "宴会增长"
    description = "宴会线索挖掘、套餐推荐、转化跟踪、档期管理、收益分析、口碑管理"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "discover_banquet_leads",
            "recommend_banquet_package",
            "track_banquet_conversion",
            "manage_banquet_schedule",
            "analyze_banquet_revenue",
            "manage_banquet_review",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "discover_banquet_leads": self._discover_leads,
            "recommend_banquet_package": self._recommend_package,
            "track_banquet_conversion": self._track_conversion,
            "manage_banquet_schedule": self._manage_schedule,
            "analyze_banquet_revenue": self._analyze_revenue,
            "manage_banquet_review": self._manage_review,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _discover_leads(self, params: dict) -> AgentResult:
        """宴会线索挖掘"""
        members = params.get("members", [])
        current_month = params.get("current_month", 6)

        leads = []
        for m in members:
            customer_id = m.get("customer_id")
            name = m.get("name", "")

            # 生日宴线索：生日在未来30天内
            birth_month = m.get("birth_month")
            if birth_month and abs(birth_month - current_month) <= 1:
                leads.append({
                    "customer_id": customer_id, "name": name,
                    "lead_type": "birthday", "lead_type_name": "生日宴",
                    "confidence": 0.6, "estimated_tables": 3,
                    "signal": f"生日在{birth_month}月",
                })

            # 婚宴线索：近期搜索/咨询过
            if m.get("searched_wedding"):
                leads.append({
                    "customer_id": customer_id, "name": name,
                    "lead_type": "wedding", "lead_type_name": "婚宴",
                    "confidence": 0.8, "estimated_tables": 15,
                    "signal": "近期搜索婚宴信息",
                })

            # 商务宴请：高频商务客户
            if m.get("is_corporate") and m.get("monthly_frequency", 0) >= 3:
                leads.append({
                    "customer_id": customer_id, "name": name,
                    "lead_type": "corporate", "lead_type_name": "商务宴请",
                    "confidence": 0.5, "estimated_tables": 3,
                    "signal": "高频商务客户",
                })

        leads.sort(key=lambda x: x["confidence"], reverse=True)
        return AgentResult(
            success=True, action="discover_banquet_leads",
            data={"leads": leads[:50], "total": len(leads),
                  "by_type": {t: sum(1 for l in leads if l["lead_type"] == t) for t in BANQUET_TYPES}},
            reasoning=f"发现 {len(leads)} 条宴会线索",
            confidence=0.7,
        )

    async def _recommend_package(self, params: dict) -> AgentResult:
        """宴会套餐推荐"""
        banquet_type = params.get("banquet_type", "birthday")
        table_count = params.get("table_count", 5)
        budget_per_table_fen = params.get("budget_per_table_fen", 0)

        type_info = BANQUET_TYPES.get(banquet_type, BANQUET_TYPES["birthday"])
        base_price = type_info["avg_per_table_fen"]

        packages = []
        for tier_key, tier in PACKAGE_TIERS.items():
            per_table = int(base_price * tier["multiplier"])
            total = per_table * table_count
            packages.append({
                "tier": tier_key,
                "tier_name": tier["name"],
                "per_table_yuan": round(per_table / 100, 2),
                "total_yuan": round(total / 100, 2),
                "table_count": table_count,
                "includes": self._get_package_items(banquet_type, tier_key),
            })

        # 推荐最合适的
        recommended = "standard"
        if budget_per_table_fen > 0:
            for pkg in packages:
                if pkg["per_table_yuan"] * 100 <= budget_per_table_fen:
                    recommended = pkg["tier"]

        return AgentResult(
            success=True, action="recommend_banquet_package",
            data={
                "banquet_type": banquet_type,
                "banquet_type_name": type_info["name"],
                "packages": packages,
                "recommended_tier": recommended,
            },
            reasoning=f"为{type_info['name']}推荐 {len(packages)} 个套餐方案，建议{PACKAGE_TIERS[recommended]['name']}",
            confidence=0.8,
        )

    @staticmethod
    def _get_package_items(banquet_type: str, tier: str) -> list[str]:
        base = ["凉菜4道", "热菜8道", "主食2道", "甜品1道", "水果拼盘"]
        if tier == "premium":
            base += ["高端海鲜1道", "精品汤品", "免费布置"]
        elif tier == "luxury":
            base += ["鲍鱼/龙虾", "燕窝甜品", "豪华布置", "专属服务管家", "音响设备"]
        if banquet_type == "wedding":
            base.append("喜糖喜酒")
        return base

    async def _track_conversion(self, params: dict) -> AgentResult:
        """宴会转化跟踪"""
        leads = params.get("leads", [])
        total_leads = len(leads)
        converted = sum(1 for l in leads if l.get("status") == "converted")
        pending = sum(1 for l in leads if l.get("status") == "pending")
        lost = sum(1 for l in leads if l.get("status") == "lost")

        conversion_rate = round(converted / max(1, total_leads) * 100, 1)
        pipeline_value_fen = sum(l.get("estimated_value_fen", 0) for l in leads if l.get("status") == "pending")

        return AgentResult(
            success=True, action="track_banquet_conversion",
            data={
                "total_leads": total_leads, "converted": converted,
                "pending": pending, "lost": lost,
                "conversion_rate_pct": conversion_rate,
                "pipeline_value_yuan": round(pipeline_value_fen / 100, 2),
            },
            reasoning=f"宴会线索 {total_leads} 条，转化 {converted} 单（{conversion_rate}%），"
                      f"在谈 {pending} 单",
            confidence=0.85,
        )

    async def _manage_schedule(self, params: dict) -> AgentResult:
        """宴会档期管理"""
        month = params.get("month", 6)
        capacity_per_day = params.get("capacity_per_day", 3)
        bookings = params.get("bookings", [])

        booked_dates: dict[str, int] = {}
        for b in bookings:
            date = b.get("date", "")
            booked_dates[date] = booked_dates.get(date, 0) + 1

        full_dates = [d for d, c in booked_dates.items() if c >= capacity_per_day]
        available_slots = capacity_per_day * 30 - sum(booked_dates.values())

        return AgentResult(
            success=True, action="manage_banquet_schedule",
            data={
                "month": month,
                "total_bookings": len(bookings),
                "full_dates": full_dates,
                "available_slots": max(0, available_slots),
                "utilization_pct": round(sum(booked_dates.values()) / max(1, capacity_per_day * 30) * 100, 1),
            },
            reasoning=f"{month}月宴会档期: 已预订{len(bookings)}场，剩余{max(0, available_slots)}个档位",
            confidence=0.9,
        )

    async def _analyze_revenue(self, params: dict) -> AgentResult:
        """宴会收益分析"""
        banquets = params.get("banquets", [])
        total_revenue_fen = sum(b.get("revenue_fen", 0) for b in banquets)
        total_cost_fen = sum(b.get("cost_fen", 0) for b in banquets)
        gross_margin = round((total_revenue_fen - total_cost_fen) / max(1, total_revenue_fen) * 100, 1)

        by_type: dict[str, dict] = {}
        for b in banquets:
            bt = b.get("banquet_type", "other")
            if bt not in by_type:
                by_type[bt] = {"count": 0, "revenue_fen": 0}
            by_type[bt]["count"] += 1
            by_type[bt]["revenue_fen"] += b.get("revenue_fen", 0)

        return AgentResult(
            success=True, action="analyze_banquet_revenue",
            data={
                "total_banquets": len(banquets),
                "total_revenue_yuan": round(total_revenue_fen / 100, 2),
                "total_cost_yuan": round(total_cost_fen / 100, 2),
                "gross_margin_pct": gross_margin,
                "avg_revenue_yuan": round(total_revenue_fen / max(1, len(banquets)) / 100, 2),
                "by_type": {k: {"count": v["count"], "revenue_yuan": round(v["revenue_fen"] / 100, 2)}
                           for k, v in by_type.items()},
            },
            reasoning=f"宴会收入 ¥{total_revenue_fen / 100:.0f}，毛利率 {gross_margin}%",
            confidence=0.85,
        )

    async def _manage_review(self, params: dict) -> AgentResult:
        """宴会口碑管理"""
        reviews = params.get("reviews", [])
        avg_rating = sum(r.get("rating", 5) for r in reviews) / max(1, len(reviews))
        bad_reviews = [r for r in reviews if r.get("rating", 5) <= 3]

        suggestions = []
        for r in bad_reviews:
            text = r.get("text", "")
            if "菜品" in text or "味道" in text:
                suggestions.append({"issue": "菜品质量", "action": "优化宴会菜单，增加试菜环节"})
            if "服务" in text or "态度" in text:
                suggestions.append({"issue": "服务质量", "action": "加强宴会服务培训，指定专属管家"})
            if "环境" in text or "布置" in text:
                suggestions.append({"issue": "场地布置", "action": "升级宴会布置方案"})

        return AgentResult(
            success=True, action="manage_banquet_review",
            data={
                "total_reviews": len(reviews),
                "avg_rating": round(avg_rating, 1),
                "bad_review_count": len(bad_reviews),
                "improvement_suggestions": suggestions[:5],
            },
            reasoning=f"宴会评价 {len(reviews)} 条，均分 {avg_rating:.1f}，差评 {len(bad_reviews)} 条",
            confidence=0.8,
        )
