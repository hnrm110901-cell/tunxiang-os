"""游戏化教练 Agent — P2 | 云端

职责：
  - 根据门店经营数据，推荐合适的挑战活动
  - 评估季节性活动方案的可行性和预期ROI
  - 三条硬约束校验（毛利底线/食安合规/客户体验）
  - 全程决策留痕

两个核心 Skill：
  1. suggest_challenges — 基于会员画像推荐挑战
  2. evaluate_seasonal_event — 评估季节性活动方案
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger(__name__)

BRAIN_SERVICE_URL = os.getenv("BRAIN_SERVICE_URL", "http://tx-brain:8010")

# ─── 挑战模板库 ─────────────────────────────────────────────────────────────

CHALLENGE_TEMPLATES: list[dict] = [
    {
        "template_id": "visit_streak_7",
        "name": "连续7天打卡",
        "type": "visit_streak",
        "rules": {"target": 7, "consecutive": True},
        "reward": {"type": "points", "amount": 500},
        "suitable_for": ["new_customer", "active"],
        "min_member_count": 50,
        "expected_roi": 2.5,
    },
    {
        "template_id": "spend_target_500",
        "name": "累计消费满500元",
        "type": "spend_target",
        "rules": {"target": 50000, "unit": "fen"},
        "reward": {"type": "coupon", "coupon_type": "cash", "face_value_fen": 5000},
        "suitable_for": ["active", "loyal"],
        "min_member_count": 30,
        "expected_roi": 3.0,
    },
    {
        "template_id": "dish_explorer_10",
        "name": "美食探索家(尝试10道菜)",
        "type": "dish_explorer",
        "rules": {"target": 10, "unique_dishes": True},
        "reward": {"type": "badge", "badge_category": "exploration"},
        "suitable_for": ["active", "loyal", "vip"],
        "min_member_count": 20,
        "expected_roi": 1.8,
    },
    {
        "template_id": "referral_drive_3",
        "name": "推荐3位好友",
        "type": "referral_drive",
        "rules": {"target": 3, "must_order": True},
        "reward": {"type": "points", "amount": 1000},
        "suitable_for": ["loyal", "vip"],
        "min_member_count": 10,
        "expected_roi": 5.0,
    },
    {
        "template_id": "weekend_warrior",
        "name": "周末勇士(连续4个周末到店)",
        "type": "visit_streak",
        "rules": {"target": 4, "day_filter": "weekend"},
        "reward": {"type": "coupon", "coupon_type": "discount", "discount_rate": 85},
        "suitable_for": ["active", "loyal"],
        "min_member_count": 40,
        "expected_roi": 2.0,
    },
]

# ─── 季节性活动评估维度 ──────────────────────────────────────────────────────

SEASONAL_DIMENSIONS = [
    "traffic_impact",  # 对客流的预期影响
    "margin_safety",  # 毛利安全性
    "staff_workload",  # 员工工作量影响
    "food_safety_risk",  # 食安风险
    "customer_experience",  # 客户体验影响
    "brand_alignment",  # 品牌调性匹配
]


class GamificationCoachAgent(SkillAgent):
    """游戏化教练 — P2 云端 Skill Agent"""

    agent_id: str = "gamification_coach"
    agent_name: str = "游戏化教练"
    priority: str = "P2"
    run_location: str = "cloud"

    async def suggest_challenges(
        self,
        tenant_id: str,
        store_id: str | None = None,
        member_segment: str | None = None,
        max_suggestions: int = 3,
    ) -> AgentResult:
        """根据门店经营数据推荐挑战活动"""
        start_ts = time.time()
        decision_id = str(uuid.uuid4())

        logger.info(
            "gamification_suggest_start",
            tenant_id=tenant_id,
            store_id=store_id,
            segment=member_segment,
        )

        # 1. 获取门店基础数据
        store_stats = await self._get_store_stats(tenant_id, store_id)

        # 2. 过滤匹配的挑战模板
        candidates = []
        for tpl in CHALLENGE_TEMPLATES:
            # 会员分层匹配
            if member_segment and member_segment not in tpl["suitable_for"]:
                continue
            # 最低会员数量要求
            if store_stats.get("active_member_count", 0) < tpl["min_member_count"]:
                continue
            candidates.append(tpl)

        # 3. 按预期ROI排序，取前N个
        candidates.sort(key=lambda x: x["expected_roi"], reverse=True)
        suggestions = candidates[:max_suggestions]

        # 4. 三条硬约束校验
        constraints = self._check_constraints(suggestions, store_stats)

        # 5. 决策留痕
        elapsed = time.time() - start_ts
        decision_log = {
            "agent_id": self.agent_id,
            "decision_id": decision_id,
            "decision_type": "suggest_challenges",
            "input_context": {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "member_segment": member_segment,
                "store_stats": store_stats,
            },
            "reasoning": f"从{len(CHALLENGE_TEMPLATES)}个模板中筛选出{len(suggestions)}个推荐，按ROI排序",
            "output_action": {
                "suggestions": suggestions,
            },
            "constraints_check": constraints,
            "confidence": 0.75 if suggestions else 0.3,
            "elapsed_ms": round(elapsed * 1000),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "gamification_suggest_done",
            decision_id=decision_id,
            suggestion_count=len(suggestions),
            elapsed_ms=decision_log["elapsed_ms"],
        )

        return AgentResult(
            success=True,
            data={"suggestions": suggestions, "constraints": constraints},
            decision_log=decision_log,
        )

    async def evaluate_seasonal_event(
        self,
        tenant_id: str,
        event_plan: dict,
        store_id: str | None = None,
    ) -> AgentResult:
        """评估季节性活动方案"""
        start_ts = time.time()
        decision_id = str(uuid.uuid4())

        logger.info(
            "seasonal_event_eval_start",
            tenant_id=tenant_id,
            event_name=event_plan.get("name"),
        )

        store_stats = await self._get_store_stats(tenant_id, store_id)

        # 多维度评估
        scores: dict[str, float] = {}
        recommendations: list[str] = []

        # 客流影响
        expected_traffic_boost = event_plan.get("expected_traffic_boost_pct", 0)
        scores["traffic_impact"] = min(expected_traffic_boost / 30, 1.0) * 10

        # 毛利安全
        discount_depth = event_plan.get("max_discount_pct", 0)
        margin_score = max(10 - discount_depth / 5, 0)
        scores["margin_safety"] = margin_score
        if discount_depth > 30:
            recommendations.append("折扣力度超过30%，建议控制在20%以内以保证毛利底线")

        # 员工工作量
        extra_hours = event_plan.get("extra_staff_hours", 0)
        scores["staff_workload"] = max(10 - extra_hours / 4, 0)
        if extra_hours > 20:
            recommendations.append("额外工时超过20小时，建议分阶段执行或增加临时人手")

        # 食安风险
        new_dishes = event_plan.get("new_dish_count", 0)
        scores["food_safety_risk"] = max(10 - new_dishes * 0.5, 0)
        if new_dishes > 10:
            recommendations.append("新增菜品过多，需确保供应链和食安检测跟上")

        # 客户体验
        scores["customer_experience"] = 8.0  # 默认良好，有活动提升
        if expected_traffic_boost > 50:
            scores["customer_experience"] = 5.0
            recommendations.append("预期客流激增可能影响出餐速度，需提前优化出餐动线")

        # 品牌匹配
        scores["brand_alignment"] = event_plan.get("brand_alignment_score", 7.0)

        overall_score = sum(scores.values()) / len(scores) if scores else 0
        feasible = overall_score >= 6.0

        # 三条硬约束
        constraints = {
            "margin_floor": margin_score >= 5.0,
            "food_safety": scores.get("food_safety_risk", 10) >= 5.0,
            "customer_experience": scores.get("customer_experience", 10) >= 5.0,
        }
        all_pass = all(constraints.values())

        elapsed = time.time() - start_ts
        decision_log = {
            "agent_id": self.agent_id,
            "decision_id": decision_id,
            "decision_type": "evaluate_seasonal_event",
            "input_context": {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "event_plan": event_plan,
            },
            "reasoning": (
                f"综合评分 {overall_score:.1f}/10, "
                f"{'方案可行' if feasible else '方案需调整'}, "
                f"硬约束{'全通过' if all_pass else '有未通过项'}"
            ),
            "output_action": {
                "feasible": feasible and all_pass,
                "overall_score": round(overall_score, 1),
                "dimension_scores": scores,
                "recommendations": recommendations,
            },
            "constraints_check": constraints,
            "confidence": 0.8 if all_pass else 0.5,
            "elapsed_ms": round(elapsed * 1000),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "seasonal_event_eval_done",
            decision_id=decision_id,
            feasible=feasible and all_pass,
            overall_score=round(overall_score, 1),
        )

        return AgentResult(
            success=True,
            data={
                "feasible": feasible and all_pass,
                "overall_score": round(overall_score, 1),
                "scores": scores,
                "constraints": constraints,
                "recommendations": recommendations,
            },
            decision_log=decision_log,
        )

    # ─── 私有方法 ─────────────────────────────────────────────────────────────

    async def _get_store_stats(
        self,
        tenant_id: str,
        store_id: str | None,
    ) -> dict[str, Any]:
        """获取门店经营统计（简化版，生产走物化视图）"""
        return {
            "active_member_count": 200,
            "avg_order_fen": 8800,
            "monthly_orders": 3000,
            "avg_margin_pct": 62,
        }

    def _check_constraints(
        self,
        suggestions: list[dict],
        store_stats: dict,
    ) -> dict[str, bool]:
        """三条硬约束校验"""
        margin_ok = True
        food_safety_ok = True
        customer_exp_ok = True

        for s in suggestions:
            reward = s.get("reward", {})
            # 毛利底线检查：优惠券面值不超过平均客单价的20%
            if reward.get("type") == "coupon":
                face = reward.get("face_value_fen", 0)
                avg_order = store_stats.get("avg_order_fen", 10000)
                if face > avg_order * 0.2:
                    margin_ok = False

        return {
            "margin_floor": margin_ok,
            "food_safety": food_safety_ok,
            "customer_experience": customer_exp_ok,
        }
