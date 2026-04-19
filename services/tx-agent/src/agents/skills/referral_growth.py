"""裂变增长 Agent — P1 | 云端

裂变活动设计、裂变海报生成、裂变链路追踪、奖励结算、裂变效果分析、种子用户筛选。
"""
import uuid
from typing import Any

from ..base import AgentResult, SkillAgent

# 裂变活动模板
REFERRAL_TEMPLATES = {
    "invite_reward": {"name": "邀请有礼", "desc": "老客邀请新客，双方各得优惠券",
                      "referrer_reward_fen": 2000, "invitee_reward_fen": 1500},
    "group_buy": {"name": "拼团优惠", "desc": "3人成团享7折",
                  "min_group_size": 3, "discount_rate": 0.7},
    "share_coupon": {"name": "分享领券", "desc": "分享到朋友圈领取优惠券",
                     "coupon_fen": 1000, "max_claims": 100},
    "lucky_draw": {"name": "助力抽奖", "desc": "邀请好友助力解锁抽奖机会",
                   "assists_needed": 5, "prize_pool": ["免单券", "半价券", "甜品券"]},
    "member_day": {"name": "会员日裂变", "desc": "会员日当天分享可获得双倍积分",
                   "points_multiplier": 2},
}


class ReferralGrowthAgent(SkillAgent):
    agent_id = "referral_growth"
    agent_name = "裂变增长"
    description = "裂变活动设计、海报生成、链路追踪、奖励结算、效果分析、种子用户筛选"
    priority = "P1"
    run_location = "cloud"

    # Sprint D1 / PR 批次 3：裂变奖励 = 单位获客成本，需 margin 校验避免奖励超过 LTV
    constraint_scope = {"margin"}

    def get_supported_actions(self) -> list[str]:
        return [
            "design_referral_campaign",
            "generate_referral_poster",
            "track_referral_chain",
            "settle_referral_rewards",
            "analyze_referral_effect",
            "select_seed_users",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "design_referral_campaign": self._design_campaign,
            "generate_referral_poster": self._generate_poster,
            "track_referral_chain": self._track_chain,
            "settle_referral_rewards": self._settle_rewards,
            "analyze_referral_effect": self._analyze_effect,
            "select_seed_users": self._select_seed_users,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _design_campaign(self, params: dict) -> AgentResult:
        """裂变活动设计"""
        template_key = params.get("template", "invite_reward")
        target_new_customers = params.get("target_new_customers", 100)
        budget_fen = params.get("budget_fen", 1000000)

        template = REFERRAL_TEMPLATES.get(template_key, REFERRAL_TEMPLATES["invite_reward"])
        campaign_id = str(uuid.uuid4())[:8]

        # 计算预期成本
        if template_key == "invite_reward":
            cost_per_new = template["referrer_reward_fen"] + template["invitee_reward_fen"]
        elif template_key == "share_coupon":
            cost_per_new = template["coupon_fen"]
        else:
            cost_per_new = int(budget_fen / max(1, target_new_customers))

        max_affordable = int(budget_fen / max(1, cost_per_new))

        return AgentResult(
            success=True, action="design_referral_campaign",
            data={
                "campaign_id": campaign_id,
                "template": template_key,
                "template_name": template["name"],
                "description": template["desc"],
                "target_new_customers": target_new_customers,
                "budget_yuan": round(budget_fen / 100, 2),
                "cost_per_new_yuan": round(cost_per_new / 100, 2),
                "max_affordable_customers": max_affordable,
                "channels": ["微信朋友圈", "微信群", "小程序"],
                "valid_days": 7,
                "rules": template,
            },
            reasoning=f"设计「{template['name']}」裂变活动，单客成本 ¥{cost_per_new / 100:.0f}，"
                      f"预算可覆盖 {max_affordable} 人",
            confidence=0.85,
        )

    async def _generate_poster(self, params: dict) -> AgentResult:
        """裂变海报生成"""
        campaign_id = params.get("campaign_id", "")
        referrer_id = params.get("referrer_id", "")
        referrer_name = params.get("referrer_name", "")
        store_name = params.get("store_name", "")
        offer_text = params.get("offer_text", "邀请好友，双方各得优惠券")

        poster_id = str(uuid.uuid4())[:8]
        qr_code_url = f"https://mp.tunxiang.com/r/{campaign_id}/{referrer_id}"

        return AgentResult(
            success=True, action="generate_referral_poster",
            data={
                "poster_id": poster_id,
                "campaign_id": campaign_id,
                "referrer_id": referrer_id,
                "qr_code_url": qr_code_url,
                "poster_elements": {
                    "title": f"{store_name}邀您尝鲜",
                    "subtitle": offer_text,
                    "referrer_text": f"{referrer_name} 推荐您",
                    "cta": "长按识别二维码领取",
                },
                "share_text": f"我在{store_name}发现了超值优惠，{offer_text}，快来一起享受！",
            },
            reasoning=f"为 {referrer_name} 生成裂变海报，含专属二维码",
            confidence=0.9,
        )

    async def _track_chain(self, params: dict) -> AgentResult:
        """裂变链路追踪"""
        campaign_id = params.get("campaign_id", "")
        referral_events = params.get("referral_events", [])

        # 构建裂变树
        chain_depth: dict[str, int] = {}
        referrer_counts: dict[str, int] = {}
        total_invitees = 0

        for event in referral_events:
            referrer = event.get("referrer_id", "")
            invitee = event.get("invitee_id", "")
            depth = event.get("depth", 1)

            referrer_counts[referrer] = referrer_counts.get(referrer, 0) + 1
            chain_depth[invitee] = depth
            total_invitees += 1

        top_referrers = sorted(referrer_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        max_depth = max(chain_depth.values()) if chain_depth else 0
        viral_coefficient = round(total_invitees / max(1, len(referrer_counts)), 2)

        return AgentResult(
            success=True, action="track_referral_chain",
            data={
                "campaign_id": campaign_id,
                "total_referrers": len(referrer_counts),
                "total_invitees": total_invitees,
                "max_chain_depth": max_depth,
                "viral_coefficient": viral_coefficient,
                "top_referrers": [{"referrer_id": r, "invite_count": c} for r, c in top_referrers],
                "is_viral": viral_coefficient >= 1.0,
            },
            reasoning=f"裂变链路: {len(referrer_counts)} 个推荐人带来 {total_invitees} 个新客，"
                      f"K因子 {viral_coefficient}",
            confidence=0.85,
        )

    async def _settle_rewards(self, params: dict) -> AgentResult:
        """奖励结算"""
        campaign_id = params.get("campaign_id", "")
        reward_records = params.get("reward_records", [])

        total_reward_fen = 0
        settled_count = 0
        pending_count = 0

        for r in reward_records:
            amount = r.get("reward_fen", 0)
            if r.get("invitee_converted", False):
                total_reward_fen += amount
                settled_count += 1
            else:
                pending_count += 1

        return AgentResult(
            success=True, action="settle_referral_rewards",
            data={
                "campaign_id": campaign_id,
                "total_records": len(reward_records),
                "settled_count": settled_count,
                "pending_count": pending_count,
                "total_reward_yuan": round(total_reward_fen / 100, 2),
                "avg_reward_yuan": round(total_reward_fen / max(1, settled_count) / 100, 2),
            },
            reasoning=f"结算 {settled_count} 笔奖励，合计 ¥{total_reward_fen / 100:.0f}，待结算 {pending_count} 笔",
            confidence=0.9,
        )

    async def _analyze_effect(self, params: dict) -> AgentResult:
        """裂变效果分析"""
        campaign_id = params.get("campaign_id", "")
        total_referrers = params.get("total_referrers", 0)
        total_invitees = params.get("total_invitees", 0)
        converted_invitees = params.get("converted_invitees", 0)
        total_cost_fen = params.get("total_cost_fen", 0)
        invitee_revenue_fen = params.get("invitee_revenue_fen", 0)

        conversion_rate = round(converted_invitees / max(1, total_invitees) * 100, 1)
        cac_fen = int(total_cost_fen / max(1, converted_invitees))
        roi = round((invitee_revenue_fen - total_cost_fen) / max(1, total_cost_fen), 2)
        viral_k = round(total_invitees / max(1, total_referrers), 2)

        return AgentResult(
            success=True, action="analyze_referral_effect",
            data={
                "campaign_id": campaign_id,
                "total_referrers": total_referrers,
                "total_invitees": total_invitees,
                "converted_invitees": converted_invitees,
                "conversion_rate_pct": conversion_rate,
                "cac_yuan": round(cac_fen / 100, 2),
                "roi": roi,
                "viral_k": viral_k,
                "invitee_revenue_yuan": round(invitee_revenue_fen / 100, 2),
                "effectiveness": "爆发" if viral_k >= 1.5 else "良好" if viral_k >= 1.0 else "一般" if viral_k >= 0.5 else "较差",
            },
            reasoning=f"裂变K因子 {viral_k}，转化率 {conversion_rate}%，ROI {roi}",
            confidence=0.8,
        )

    async def _select_seed_users(self, params: dict) -> AgentResult:
        """种子用户筛选"""
        members = params.get("members", [])
        top_n = params.get("top_n", 50)

        scored = []
        for m in members:
            social_score = 0
            # 社交影响力指标
            social_score += min(30, m.get("wechat_friends", 0) / 10)
            social_score += min(20, m.get("past_referrals", 0) * 5)
            social_score += min(20, m.get("social_shares", 0) * 2)
            # 忠诚度指标
            social_score += min(15, m.get("visit_count", 0) * 1.5)
            social_score += min(15, m.get("avg_rating", 0) * 3)

            scored.append({
                "customer_id": m.get("customer_id"),
                "name": m.get("name", ""),
                "seed_score": round(social_score, 1),
                "past_referrals": m.get("past_referrals", 0),
                "social_influence": "高" if social_score >= 60 else "中" if social_score >= 35 else "低",
            })

        scored.sort(key=lambda x: x["seed_score"], reverse=True)
        selected = scored[:top_n]

        return AgentResult(
            success=True, action="select_seed_users",
            data={
                "seed_users": selected,
                "total_candidates": len(members),
                "selected_count": len(selected),
                "avg_seed_score": round(sum(s["seed_score"] for s in selected) / max(1, len(selected)), 1),
            },
            reasoning=f"从 {len(members)} 人中筛选 {len(selected)} 位种子用户，"
                      f"平均社交影响力分 {sum(s['seed_score'] for s in selected) / max(1, len(selected)):.1f}",
            confidence=0.75,
        )
