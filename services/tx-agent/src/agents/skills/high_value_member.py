"""高价值会员维护 Agent — P0 | 云端

高价值会员识别、专属权益设计、流失预警、个性化服务、生命周期管理、价值提升策略。
"""
from typing import Any
from ..base import SkillAgent, AgentResult


# 会员等级定义
MEMBER_TIERS = {
    "diamond": {"name": "钻石会员", "min_annual_spend_fen": 5000000, "discount_rate": 0.88, "points_multiplier": 3},
    "gold": {"name": "金卡会员", "min_annual_spend_fen": 2000000, "discount_rate": 0.92, "points_multiplier": 2},
    "silver": {"name": "银卡会员", "min_annual_spend_fen": 800000, "discount_rate": 0.95, "points_multiplier": 1.5},
    "regular": {"name": "普通会员", "min_annual_spend_fen": 0, "discount_rate": 1.0, "points_multiplier": 1},
}

# 专属权益池
EXCLUSIVE_PERKS = {
    "diamond": ["专属管家服务", "生日免单（限2000元）", "优先包间预订", "新品优先试吃", "年度答谢宴邀请", "免费代客泊车"],
    "gold": ["生日8折", "优先排队", "新品试吃", "季度赠券"],
    "silver": ["生日9折", "积分翻倍日", "节日赠券"],
}


class HighValueMemberAgent(SkillAgent):
    agent_id = "high_value_member"
    agent_name = "高价值会员维护"
    description = "高价值会员识别、专属权益设计、流失预警、个性化服务、生命周期管理、价值提升"
    priority = "P0"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "identify_high_value_members",
            "design_exclusive_perks",
            "alert_high_value_churn",
            "personalize_service",
            "manage_member_lifecycle",
            "suggest_value_upgrade",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "identify_high_value_members": self._identify_hvm,
            "design_exclusive_perks": self._design_perks,
            "alert_high_value_churn": self._alert_churn,
            "personalize_service": self._personalize,
            "manage_member_lifecycle": self._manage_lifecycle,
            "suggest_value_upgrade": self._suggest_upgrade,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _identify_hvm(self, params: dict) -> AgentResult:
        """高价值会员识别"""
        members = params.get("members", [])
        results = {"diamond": [], "gold": [], "silver": [], "regular": []}

        for m in members:
            annual_spend = m.get("annual_spend_fen", 0)
            if annual_spend >= MEMBER_TIERS["diamond"]["min_annual_spend_fen"]:
                tier = "diamond"
            elif annual_spend >= MEMBER_TIERS["gold"]["min_annual_spend_fen"]:
                tier = "gold"
            elif annual_spend >= MEMBER_TIERS["silver"]["min_annual_spend_fen"]:
                tier = "silver"
            else:
                tier = "regular"

            results[tier].append({
                "customer_id": m.get("customer_id"),
                "name": m.get("name", ""),
                "tier": tier,
                "tier_name": MEMBER_TIERS[tier]["name"],
                "annual_spend_yuan": round(annual_spend / 100, 2),
                "visit_count": m.get("visit_count", 0),
            })

        hv_count = len(results["diamond"]) + len(results["gold"])
        total = len(members)

        return AgentResult(
            success=True, action="identify_high_value_members",
            data={
                "tier_distribution": {k: len(v) for k, v in results.items()},
                "diamond_members": results["diamond"][:20],
                "gold_members": results["gold"][:20],
                "high_value_count": hv_count,
                "high_value_pct": round(hv_count / max(1, total) * 100, 1),
                "total_members": total,
            },
            reasoning=f"识别高价值会员 {hv_count} 人（钻石{len(results['diamond'])}、金卡{len(results['gold'])}），"
                      f"占比 {hv_count / max(1, total) * 100:.1f}%",
            confidence=0.9,
        )

    async def _design_perks(self, params: dict) -> AgentResult:
        """专属权益设计"""
        tier = params.get("tier", "gold")
        customer_id = params.get("customer_id", "")
        preferences = params.get("preferences", [])

        base_perks = EXCLUSIVE_PERKS.get(tier, EXCLUSIVE_PERKS.get("silver", []))
        tier_info = MEMBER_TIERS.get(tier, MEMBER_TIERS["regular"])

        personalized_perks = list(base_perks)
        if "海鲜" in preferences:
            personalized_perks.append("海鲜拼盘升级")
        if "包间" in preferences:
            personalized_perks.append("包间费减免")
        if "红酒" in preferences:
            personalized_perks.append("红酒开瓶费免除")

        return AgentResult(
            success=True, action="design_exclusive_perks",
            data={
                "customer_id": customer_id,
                "tier": tier,
                "tier_name": tier_info.get("name", tier) if isinstance(tier_info, dict) else tier,
                "discount_rate": tier_info["discount_rate"],
                "points_multiplier": tier_info["points_multiplier"],
                "perks": personalized_perks,
                "personalized_count": len(personalized_perks) - len(base_perks),
            },
            reasoning=f"为{MEMBER_TIERS.get(tier, {}).get('name', tier)}设计 {len(personalized_perks)} 项权益，"
                      f"含 {len(personalized_perks) - len(base_perks)} 项个性化权益",
            confidence=0.85,
        )

    async def _alert_churn(self, params: dict) -> AgentResult:
        """高价值会员流失预警"""
        members = params.get("members", [])
        alerts = []

        for m in members:
            annual_spend = m.get("annual_spend_fen", 0)
            if annual_spend < MEMBER_TIERS["silver"]["min_annual_spend_fen"]:
                continue  # 非高价值，跳过

            last_days = m.get("last_visit_days_ago", 0)
            freq_decline = m.get("frequency_decline_pct", 0)
            spend_decline = m.get("spend_decline_pct", 0)

            risk = 0.0
            signals = []
            if last_days >= 30:
                risk += 0.3
                signals.append(f"已{last_days}天未到店")
            if freq_decline >= 30:
                risk += 0.25
                signals.append(f"到店频次下降{freq_decline}%")
            if spend_decline >= 20:
                risk += 0.2
                signals.append(f"消费金额下降{spend_decline}%")
            if m.get("recent_complaint"):
                risk += 0.25
                signals.append("近期有投诉")

            if risk >= 0.3:
                alerts.append({
                    "customer_id": m.get("customer_id"),
                    "name": m.get("name", ""),
                    "tier": "diamond" if annual_spend >= MEMBER_TIERS["diamond"]["min_annual_spend_fen"] else "gold",
                    "risk_score": round(min(1.0, risk), 2),
                    "signals": signals,
                    "annual_spend_yuan": round(annual_spend / 100, 2),
                    "recommended_action": "店长亲自回访" if risk >= 0.7 else "专属管家致电" if risk >= 0.5 else "推送关怀权益",
                })

        alerts.sort(key=lambda x: x["risk_score"], reverse=True)

        return AgentResult(
            success=True, action="alert_high_value_churn",
            data={"alerts": alerts[:30], "total_alerts": len(alerts),
                  "critical_count": sum(1 for a in alerts if a["risk_score"] >= 0.7)},
            reasoning=f"高价值会员流失预警 {len(alerts)} 条，严重 {sum(1 for a in alerts if a['risk_score'] >= 0.7)} 条",
            confidence=0.8,
        )

    async def _personalize(self, params: dict) -> AgentResult:
        """个性化服务"""
        customer_id = params.get("customer_id", "")
        name = params.get("name", "")
        preferences = params.get("preferences", {})
        visit_history = params.get("visit_history", [])

        # 从历史中提取偏好
        fav_dishes = {}
        fav_time_slots = {}
        for v in visit_history:
            for dish in v.get("dishes", []):
                fav_dishes[dish] = fav_dishes.get(dish, 0) + 1
            slot = v.get("time_slot", "")
            if slot:
                fav_time_slots[slot] = fav_time_slots.get(slot, 0) + 1

        top_dishes = sorted(fav_dishes.items(), key=lambda x: x[1], reverse=True)[:5]
        preferred_slot = max(fav_time_slots.items(), key=lambda x: x[1])[0] if fav_time_slots else "未知"

        service_notes = []
        if preferences.get("allergies"):
            service_notes.append(f"过敏源: {', '.join(preferences['allergies'])}")
        if preferences.get("seating"):
            service_notes.append(f"座位偏好: {preferences['seating']}")
        if preferences.get("spice_level"):
            service_notes.append(f"辣度: {preferences['spice_level']}")

        return AgentResult(
            success=True, action="personalize_service",
            data={
                "customer_id": customer_id,
                "name": name,
                "favorite_dishes": [{"dish": d, "order_count": c} for d, c in top_dishes],
                "preferred_time_slot": preferred_slot,
                "service_notes": service_notes,
                "greeting_script": f"欢迎回来，{name}！您常点的{top_dishes[0][0] if top_dishes else '招牌菜'}今天特别新鲜。",
                "upsell_suggestion": f"根据您的口味，推荐今日主厨特选",
            },
            reasoning=f"为 {name} 生成个性化服务方案，含 {len(top_dishes)} 道偏好菜品",
            confidence=0.85,
        )

    async def _manage_lifecycle(self, params: dict) -> AgentResult:
        """生命周期管理"""
        customer_id = params.get("customer_id", "")
        current_tier = params.get("current_tier", "regular")
        months_in_tier = params.get("months_in_tier", 0)
        spend_trend = params.get("spend_trend_pct", 0)
        annual_spend_fen = params.get("annual_spend_fen", 0)

        # 判断生命周期阶段
        if months_in_tier <= 3 and current_tier != "regular":
            stage = "新晋"
            action = "强化权益感知，提升粘性"
        elif spend_trend >= 10:
            stage = "成长"
            action = "引导升级到更高等级"
        elif spend_trend <= -20:
            stage = "衰退"
            action = "启动挽留计划，专属关怀"
        elif months_in_tier >= 12:
            stage = "成熟"
            action = "维持稳定消费，提升客单价"
        else:
            stage = "稳定"
            action = "日常维护，定期触达"

        # 下一等级升级差距
        next_tier = {"regular": "silver", "silver": "gold", "gold": "diamond"}.get(current_tier)
        gap_fen = 0
        if next_tier:
            gap_fen = max(0, MEMBER_TIERS[next_tier]["min_annual_spend_fen"] - annual_spend_fen)

        return AgentResult(
            success=True, action="manage_member_lifecycle",
            data={
                "customer_id": customer_id,
                "current_tier": current_tier,
                "lifecycle_stage": stage,
                "recommended_action": action,
                "months_in_tier": months_in_tier,
                "spend_trend_pct": spend_trend,
                "next_tier": next_tier,
                "upgrade_gap_yuan": round(gap_fen / 100, 2) if gap_fen > 0 else 0,
            },
            reasoning=f"会员生命周期阶段: {stage}，建议: {action}",
            confidence=0.8,
        )

    async def _suggest_upgrade(self, params: dict) -> AgentResult:
        """价值提升策略"""
        members = params.get("members", [])
        suggestions = []

        for m in members:
            current_tier = m.get("tier", "regular")
            annual_spend = m.get("annual_spend_fen", 0)
            avg_ticket_fen = m.get("avg_ticket_fen", 0)
            frequency = m.get("monthly_frequency", 0)

            strategies = []
            # 提频策略
            if frequency <= 2:
                strategies.append({"type": "提频", "detail": "推送限时优惠，提升到店频次",
                                   "expected_lift_pct": 15})
            # 提客单策略
            if avg_ticket_fen <= 15000:
                strategies.append({"type": "提客单", "detail": "推荐套餐/加菜引导，提升客单价",
                                   "expected_lift_pct": 10})
            # 升级策略
            next_tier = {"regular": "silver", "silver": "gold", "gold": "diamond"}.get(current_tier)
            if next_tier:
                gap = MEMBER_TIERS[next_tier]["min_annual_spend_fen"] - annual_spend
                if 0 < gap <= annual_spend * 0.3:
                    strategies.append({"type": "升级激励", "detail": f"距{MEMBER_TIERS[next_tier]['name']}仅差 ¥{gap / 100:.0f}",
                                       "expected_lift_pct": 20})

            if strategies:
                suggestions.append({
                    "customer_id": m.get("customer_id"),
                    "name": m.get("name", ""),
                    "current_tier": current_tier,
                    "strategies": strategies,
                })

        return AgentResult(
            success=True, action="suggest_value_upgrade",
            data={"suggestions": suggestions[:50], "total": len(suggestions)},
            reasoning=f"为 {len(suggestions)} 位会员生成价值提升策略",
            confidence=0.75,
        )
