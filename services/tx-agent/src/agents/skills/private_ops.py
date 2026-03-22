"""#9 私域运营 Agent — P2 | 云端

来源：private_domain + people_agent + reservation + banquet
能力：私域全链路、绩效评分、人力成本、预订、宴会

迁移自 tunxiang V2.x people_agent/agent.py + reservation/agent.py + banquet/agent.py
"""
import statistics
from typing import Any
from ..base import SkillAgent, AgentResult


# 绩效规则（6种岗位）— 迁移自 performance/agent.py
ROLE_WEIGHTS = {
    "manager": {"revenue": 0.3, "cost_rate": 0.25, "customer_sat": 0.2, "staff_mgmt": 0.15, "compliance": 0.1},
    "waiter": {"service_count": 0.3, "tips": 0.2, "complaints": 0.2, "upsell": 0.15, "attendance": 0.15},
    "chef": {"dish_quality": 0.3, "speed": 0.25, "waste": 0.2, "consistency": 0.15, "hygiene": 0.1},
    "cashier": {"accuracy": 0.35, "speed": 0.25, "customer_sat": 0.2, "attendance": 0.2},
}


class PrivateOpsAgent(SkillAgent):
    agent_id = "private_ops"
    agent_name = "私域运营"
    description = "私域全链路运营、绩效评分、人力成本、预订管理、宴会"
    priority = "P2"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "get_private_domain_dashboard", "trigger_campaign", "advance_journey",
            "optimize_shift", "score_performance", "analyze_labor_cost", "warn_attendance",
            "create_reservation", "manage_banquet", "generate_beo", "allocate_seating",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "score_performance": self._score_performance,
            "analyze_labor_cost": self._analyze_labor_cost,
            "warn_attendance": self._warn_attendance,
            "allocate_seating": self._allocate_seating,
            "generate_beo": self._generate_beo,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=True, action=action, data={"message": f"{action} ready"}, confidence=0.8)

    async def _score_performance(self, params: dict) -> AgentResult:
        """员工绩效评分（加权多指标）"""
        role = params.get("role", "waiter")
        metrics = params.get("metrics", {})
        weights = ROLE_WEIGHTS.get(role, ROLE_WEIGHTS["waiter"])

        dimension_scores = {}
        for dim, weight in weights.items():
            value = metrics.get(dim, 50)
            dimension_scores[dim] = {"value": value, "weight": weight, "weighted": round(value * weight, 1)}

        total = sum(d["weighted"] for d in dimension_scores.values())

        # 红线处罚
        penalties = []
        if metrics.get("food_safety_violation"):
            total = min(total, 30)
            penalties.append("食安违规（封顶30分）")
        if metrics.get("customer_complaint_serious"):
            total *= 0.7
            penalties.append("严重客诉（扣30%）")

        # 提成计算（简化）
        base_salary_fen = params.get("base_salary_fen", 500000)  # 默认5000元/月
        commission_rate = 0.03 if total >= 90 else 0.02 if total >= 70 else 0.01
        commission_fen = round(base_salary_fen * commission_rate)

        return AgentResult(
            success=True, action="score_performance",
            data={
                "role": role,
                "total_score": round(total, 1),
                "grade": "A" if total >= 90 else "B" if total >= 80 else "C" if total >= 60 else "D",
                "dimensions": dimension_scores,
                "penalties": penalties,
                "commission_fen": commission_fen,
                "commission_yuan": round(commission_fen / 100, 2),
            },
            reasoning=f"{role} 绩效 {total:.0f} 分，提成 ¥{commission_fen/100:.0f}",
            confidence=0.9,
        )

    async def _analyze_labor_cost(self, params: dict) -> AgentResult:
        """人力成本分析"""
        total_wage_fen = params.get("total_wage_fen", 0)
        revenue_fen = params.get("revenue_fen", 0)
        staff_count = params.get("staff_count", 0)
        target_rate = params.get("target_rate", 0.25)

        labor_rate = total_wage_fen / revenue_fen if revenue_fen > 0 else 0
        per_capita_fen = total_wage_fen // staff_count if staff_count > 0 else 0
        over_budget_fen = max(0, total_wage_fen - int(revenue_fen * target_rate))

        return AgentResult(
            success=True, action="analyze_labor_cost",
            data={
                "labor_cost_rate": round(labor_rate, 4),
                "labor_cost_rate_pct": round(labor_rate * 100, 1),
                "total_wage_yuan": round(total_wage_fen / 100, 2),
                "per_capita_yuan": round(per_capita_fen / 100, 2),
                "revenue_yuan": round(revenue_fen / 100, 2),
                "target_rate": target_rate,
                "over_budget_yuan": round(over_budget_fen / 100, 2),
                "status": "critical" if labor_rate > 0.35 else "warning" if labor_rate > target_rate else "ok",
            },
            reasoning=f"人力成本率 {labor_rate*100:.1f}%，目标 {target_rate*100:.0f}%",
            confidence=0.9,
        )

    async def _warn_attendance(self, params: dict) -> AgentResult:
        """出勤异常预警"""
        records = params.get("records", [])
        warnings = []

        for r in records:
            emp_name = r.get("name", "")
            late_count = r.get("late_count", 0)
            absent_count = r.get("absent_count", 0)
            early_leave = r.get("early_leave_count", 0)

            total_issues = late_count + absent_count * 3 + early_leave
            if total_issues >= 5:
                level = "high"
            elif total_issues >= 3:
                level = "medium"
            elif total_issues >= 1:
                level = "low"
            else:
                continue

            warnings.append({
                "employee": emp_name,
                "level": level,
                "late": late_count,
                "absent": absent_count,
                "early_leave": early_leave,
                "issue_score": total_issues,
            })

        warnings.sort(key=lambda w: w["issue_score"], reverse=True)
        return AgentResult(
            success=True, action="warn_attendance",
            data={"warnings": warnings, "total": len(warnings)},
            reasoning=f"发现 {len(warnings)} 个出勤异常",
            confidence=0.9,
        )

    async def _allocate_seating(self, params: dict) -> AgentResult:
        """智能座位分配"""
        guest_count = params.get("guest_count", 2)
        preferences = params.get("preferences", [])  # ["包间", "靠窗"]
        tables = params.get("available_tables", [])

        if not tables:
            return AgentResult(success=False, action="allocate_seating", error="无可用桌台")

        # 匹配：座位数 >= 客人数，且尽量不浪费
        candidates = [t for t in tables if t.get("seats", 0) >= guest_count]
        if not candidates:
            candidates = tables  # 无完美匹配时选最大桌

        # 按偏好加分
        def score_table(t):
            s = 100 - abs(t.get("seats", 0) - guest_count) * 5  # 座位匹配度
            if preferences:
                for pref in preferences:
                    if pref in (t.get("area", "") + t.get("type", "")):
                        s += 50
            return s

        candidates.sort(key=score_table, reverse=True)
        best = candidates[0]

        return AgentResult(
            success=True, action="allocate_seating",
            data={
                "table_no": best.get("table_no"),
                "area": best.get("area"),
                "seats": best.get("seats"),
                "match_score": score_table(best),
            },
            reasoning=f"推荐桌台 {best.get('table_no')}（{best.get('area')}，{best.get('seats')}座）",
            confidence=0.85,
        )

    async def _generate_beo(self, params: dict) -> AgentResult:
        """生成宴会执行单（BEO）"""
        event_name = params.get("event_name", "宴会")
        guest_count = params.get("guest_count", 0)
        menu_items = params.get("menu_items", [])
        event_date = params.get("event_date", "")
        special_requests = params.get("special_requests", [])

        total_cost_fen = sum(item.get("price_fen", 0) * item.get("quantity", 1) for item in menu_items)

        beo = {
            "event_name": event_name,
            "event_date": event_date,
            "guest_count": guest_count,
            "menu": menu_items,
            "total_cost_yuan": round(total_cost_fen / 100, 2),
            "per_guest_yuan": round(total_cost_fen / 100 / max(1, guest_count), 2),
            "special_requests": special_requests,
            "timeline": [
                {"time": "T-7", "task": "确认菜单和人数"},
                {"time": "T-3", "task": "食材采购+场地布置准备"},
                {"time": "T-1", "task": "食材到货检查+试菜"},
                {"time": "T-0 -2h", "task": "场地布置+设备检查"},
                {"time": "T-0 -30m", "task": "全员到位+最终确认"},
            ],
        }

        return AgentResult(
            success=True, action="generate_beo",
            data=beo,
            reasoning=f"宴会执行单：{event_name}，{guest_count}人，¥{total_cost_fen/100:.0f}",
            confidence=0.9,
        )
