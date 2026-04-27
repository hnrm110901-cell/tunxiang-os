"""企业客户激活 Agent — 增长型 | 云端

识别周边企业客户，设计企业套餐，追踪企业客户生命周期。
通过 ModelRouter (MODERATE) 调用 LLM 生成企业套餐方案。
"""

import uuid
from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

try:
    from services.tunxiang_api.src.shared.core.model_router import model_router
except ImportError:
    model_router = None  # 独立测试时无跨服务依赖

logger = structlog.get_logger()

# 企业类型定义
ENTERPRISE_TYPES = {
    "group_meal": {"label": "团餐企业", "min_pax": 10, "frequency": "daily"},
    "business_banquet": {"label": "商务宴请", "min_pax": 6, "frequency": "weekly"},
    "annual_party": {"label": "年会/庆典", "min_pax": 50, "frequency": "yearly"},
    "team_building": {"label": "团建聚餐", "min_pax": 15, "frequency": "quarterly"},
    "conference_meal": {"label": "会议用餐", "min_pax": 8, "frequency": "monthly"},
}

# 企业客户生命周期阶段
LIFECYCLE_STAGES = {
    "prospect": {"label": "潜在客户", "next": "first_contact"},
    "first_contact": {"label": "首次接触", "next": "trial"},
    "trial": {"label": "体验消费", "next": "contract"},
    "contract": {"label": "签约合作", "next": "repeat"},
    "repeat": {"label": "稳定复购", "next": "vip"},
    "vip": {"label": "VIP大客户", "next": None},
    "churn_warning": {"label": "流失预警", "next": None},
}

# 毛利底线: 企业套餐最低毛利率
MIN_ENTERPRISE_MARGIN_RATE = 0.15


class EnterpriseActivationAgent(SkillAgent):
    agent_id = "enterprise_activation"
    agent_name = "企业客户激活"
    description = "企业客户识别、企业套餐设计、企业客户生命周期追踪"
    priority = "P1"
    run_location = "cloud"

    # Sprint D1 / PR 批次 4：企业套餐设计直接影响大额合同毛利（已设 MIN_ENTERPRISE_MARGIN_RATE=0.15）
    constraint_scope = {"margin"}

    def get_supported_actions(self) -> list[str]:
        return ["identify", "design_package", "track_lifecycle"]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "identify": self._identify_enterprise_prospects,
            "design_package": self._design_enterprise_package,
            "track_lifecycle": self._track_enterprise_lifecycle,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _identify_enterprise_prospects(self, params: dict) -> AgentResult:
        """识别周边企业客户（高频团餐/商务宴请）"""
        store_id = params.get("store_id", self.store_id or "")
        nearby_companies = params.get("nearby_companies", [])
        existing_enterprise_ids = set(params.get("existing_enterprise_ids", []))
        radius_km = params.get("radius_km", 3)

        prospects = []
        for company in nearby_companies:
            company_id = company.get("company_id", "")
            if company_id in existing_enterprise_ids:
                continue

            employee_count = company.get("employee_count", 0)
            distance_km = company.get("distance_km", 0)
            industry = company.get("industry", "")

            # 评分模型: 员工数 + 距离 + 行业匹配
            score = 0.0
            if employee_count >= 500:
                score += 0.4
            elif employee_count >= 100:
                score += 0.3
            elif employee_count >= 30:
                score += 0.2
            else:
                score += 0.05

            if distance_km <= 1:
                score += 0.3
            elif distance_km <= 2:
                score += 0.2
            elif distance_km <= radius_km:
                score += 0.1

            # 高消费行业加分
            high_value_industries = ["金融", "科技", "地产", "法律", "咨询", "医疗"]
            if industry in high_value_industries:
                score += 0.2

            # 推断企业类型
            enterprise_types = []
            if employee_count >= 30:
                enterprise_types.append("group_meal")
            if industry in high_value_industries:
                enterprise_types.append("business_banquet")
            if employee_count >= 50:
                enterprise_types.append("annual_party")
                enterprise_types.append("team_building")
            if employee_count >= 20:
                enterprise_types.append("conference_meal")

            score = min(1.0, score)
            prospects.append(
                {
                    "company_id": company_id,
                    "company_name": company.get("company_name", ""),
                    "employee_count": employee_count,
                    "distance_km": distance_km,
                    "industry": industry,
                    "prospect_score": round(score, 2),
                    "potential_types": enterprise_types,
                    "estimated_monthly_revenue_fen": _estimate_monthly_revenue(employee_count, enterprise_types),
                }
            )

        prospects.sort(key=lambda x: x["prospect_score"], reverse=True)
        high_value = sum(1 for p in prospects if p["prospect_score"] >= 0.6)

        return AgentResult(
            success=True,
            action="identify",
            data={
                "store_id": store_id,
                "prospects": prospects[:50],
                "total": len(prospects),
                "high_value_count": high_value,
                "radius_km": radius_km,
            },
            reasoning=f"识别 {len(prospects)} 家潜在企业客户，高价值 {high_value} 家",
            confidence=0.8,
        )

    async def _design_enterprise_package(self, params: dict) -> AgentResult:
        """设计企业套餐（会议餐/年会/团建）"""
        enterprise_type = params.get("enterprise_type", "group_meal")
        pax = params.get("pax", 10)
        budget_per_person_fen = params.get("budget_per_person_fen", 8000)
        dishes = params.get("available_dishes", [])
        preferences = params.get("preferences", [])

        type_config = ENTERPRISE_TYPES.get(enterprise_type, ENTERPRISE_TYPES["group_meal"])

        # 使用 ModelRouter (MODERATE)
        model = model_router.get_model("enterprise_package") if model_router else "claude-sonnet-4-6"

        # 根据预算和人数组建套餐
        total_budget_fen = budget_per_person_fen * pax

        # 选菜: 按类别分配预算
        cold_dishes = [d for d in dishes if d.get("category") == "凉菜"]
        hot_dishes = [d for d in dishes if d.get("category") == "热菜"]
        staples = [d for d in dishes if d.get("category") == "主食"]
        desserts = [d for d in dishes if d.get("category") == "甜品"]

        # 推荐菜品组合
        package_dishes = []
        total_cost_fen = 0
        total_price_fen = 0

        # 按类别选菜
        for category_dishes, count in [
            (cold_dishes, max(2, pax // 5)),
            (hot_dishes, max(4, pax // 3)),
            (staples, max(2, pax // 5)),
            (desserts, 1),
        ]:
            sorted_dishes = sorted(
                category_dishes,
                key=lambda d: d.get("popularity_score", 0),
                reverse=True,
            )
            for dish in sorted_dishes[:count]:
                dish_price = dish.get("price_fen", 0)
                dish_cost = dish.get("cost_fen", 0)
                package_dishes.append(
                    {
                        "dish_id": dish.get("dish_id"),
                        "name": dish.get("name"),
                        "category": dish.get("category"),
                        "price_fen": dish_price,
                        "cost_fen": dish_cost,
                        "quantity": 1,
                    }
                )
                total_price_fen += dish_price
                total_cost_fen += dish_cost

        # 毛利底线校验
        if total_price_fen > 0:
            margin_rate = (total_price_fen - total_cost_fen) / total_price_fen
        else:
            margin_rate = 0.0

        margin_safe = margin_rate >= MIN_ENTERPRISE_MARGIN_RATE

        # 如果低于毛利底线，调整价格
        if not margin_safe and total_cost_fen > 0:
            min_price_fen = int(total_cost_fen / (1 - MIN_ENTERPRISE_MARGIN_RATE))
            adjusted_per_person = int(min_price_fen / max(1, pax))
            margin_warning = (
                f"当前毛利率 {margin_rate:.1%} 低于底线 {MIN_ENTERPRISE_MARGIN_RATE:.0%}，"
                f"建议人均不低于 {adjusted_per_person / 100:.0f} 元"
            )
        else:
            adjusted_per_person = None
            margin_warning = None

        package_id = str(uuid.uuid4())[:8]

        return AgentResult(
            success=True,
            action="design_package",
            data={
                "package_id": package_id,
                "enterprise_type": enterprise_type,
                "type_label": type_config["label"],
                "pax": pax,
                "dishes": package_dishes,
                "total_price_fen": total_price_fen,
                "total_cost_fen": total_cost_fen,
                "per_person_fen": int(total_price_fen / max(1, pax)),
                "margin_rate": round(margin_rate, 4),
                "margin_safe": margin_safe,
                "margin_warning": margin_warning,
                "adjusted_per_person_fen": adjusted_per_person,
                "price_fen": total_price_fen,
                "cost_fen": total_cost_fen,
            },
            reasoning=(
                f"为{type_config['label']}设计 {pax} 人套餐，"
                f"人均 {total_price_fen / max(1, pax) / 100:.0f} 元，"
                f"毛利率 {margin_rate:.1%}" + (f"（警告: {margin_warning}）" if margin_warning else "")
            ),
            confidence=0.75 if margin_safe else 0.5,
        )

    async def _track_enterprise_lifecycle(self, params: dict) -> AgentResult:
        """企业客户生命周期追踪（首次->签约->复购->流失预警）"""
        enterprise_id = params.get("enterprise_id", "")
        enterprise_name = params.get("enterprise_name", "")
        orders = params.get("orders", [])
        contract_signed = params.get("contract_signed", False)
        last_order_days_ago = params.get("last_order_days_ago", 999)
        total_spent_fen = params.get("total_spent_fen", 0)
        order_count = len(orders) if orders else params.get("order_count", 0)

        # 判断生命周期阶段
        if order_count == 0:
            stage = "prospect"
        elif order_count == 1:
            stage = "first_contact"
        elif not contract_signed and order_count <= 3:
            stage = "trial"
        elif contract_signed and order_count <= 5:
            stage = "contract"
        elif contract_signed and order_count > 5 and total_spent_fen >= 500000:
            stage = "vip"
        elif contract_signed and order_count > 5:
            stage = "repeat"
        else:
            stage = "trial"

        # 流失预警检测
        churn_warning = False
        churn_signals = []

        if stage in ("contract", "repeat", "vip") and last_order_days_ago >= 45:
            churn_warning = True
            churn_signals.append(f"已{last_order_days_ago}天未下单")

        if order_count >= 3 and orders:
            recent_amounts = [o.get("amount_fen", 0) for o in orders[-3:]]
            if len(recent_amounts) >= 2 and recent_amounts[-1] < recent_amounts[0] * 0.5:
                churn_warning = True
                churn_signals.append("近期订单金额下降超50%")

        if churn_warning:
            stage = "churn_warning"

        stage_info = LIFECYCLE_STAGES.get(stage, LIFECYCLE_STAGES["prospect"])

        # 生成建议动作
        next_actions = []
        if stage == "prospect":
            next_actions = ["发送企业合作方案", "安排商务拜访"]
        elif stage == "first_contact":
            next_actions = ["跟进体验反馈", "发送优惠体验套餐"]
        elif stage == "trial":
            next_actions = ["推送签约优惠", "安排客户经理对接"]
        elif stage == "contract":
            next_actions = ["定期回访", "推荐新品套餐"]
        elif stage == "repeat":
            next_actions = ["升级VIP权益", "推荐增值服务"]
        elif stage == "vip":
            next_actions = ["专属客户关怀", "年度合作续约提醒"]
        elif stage == "churn_warning":
            next_actions = ["紧急回访", "发送挽留优惠", "安排高层拜访"]

        return AgentResult(
            success=True,
            action="track_lifecycle",
            data={
                "enterprise_id": enterprise_id,
                "enterprise_name": enterprise_name,
                "stage": stage,
                "stage_label": stage_info["label"],
                "next_stage": stage_info["next"],
                "order_count": order_count,
                "total_spent_yuan": round(total_spent_fen / 100, 2),
                "last_order_days_ago": last_order_days_ago,
                "churn_warning": churn_warning,
                "churn_signals": churn_signals,
                "recommended_actions": next_actions,
            },
            reasoning=(
                f"企业 {enterprise_name} 处于{stage_info['label']}阶段，"
                f"累计消费 {total_spent_fen / 100:.0f} 元"
                + (f"，流失预警: {'、'.join(churn_signals)}" if churn_warning else "")
            ),
            confidence=0.85 if not churn_warning else 0.7,
        )


def _estimate_monthly_revenue(employee_count: int, enterprise_types: list[str]) -> int:
    """估算企业客户月均营收贡献（分）"""
    revenue_fen = 0
    if "group_meal" in enterprise_types:
        # 假设10%员工用团餐，人均50元，每月22天
        daily_pax = max(1, int(employee_count * 0.1))
        revenue_fen += daily_pax * 5000 * 22
    if "business_banquet" in enterprise_types:
        # 假设月均2次商务宴请，人均200元，8人
        revenue_fen += 2 * 20000 * 8
    if "conference_meal" in enterprise_types:
        # 假设月均1次会议用餐，人均80元，15人
        revenue_fen += 1 * 8000 * 15
    return revenue_fen
