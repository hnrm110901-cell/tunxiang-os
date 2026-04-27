"""#8 智能客服 Agent — P2 | 云端

来源：service(7方法) + training(8方法)
能力：投诉处理、培训需求评估、技能差距分析、培训效果评估

迁移自 tunxiang V2.x service/agent.py + training/agent.py
"""

import statistics
from typing import Any

from ..base import AgentResult, SkillAgent

# 岗位技能要求
ROLE_SKILLS = {
    "waiter": ["服务礼仪", "点菜推荐", "投诉处理", "结账操作", "卫生规范"],
    "chef": ["食材处理", "烹饪技法", "菜品摆盘", "食品安全", "设备操作"],
    "cashier": ["收银操作", "支付方式", "退款处理", "发票开具", "现金管理"],
    "manager": ["团队管理", "排班优化", "成本控制", "客诉处理", "数据分析"],
}

# 投诉优先级
COMPLAINT_PRIORITY = {
    "food_quality": 1,
    "service_attitude": 2,
    "wait_time": 2,
    "hygiene": 1,
    "billing": 3,
    "other": 3,
}


class SmartServiceAgent(SkillAgent):
    agent_id = "smart_service"
    agent_name = "智能客服"
    description = "投诉处理、培训需求评估、技能差距分析、改进建议"
    priority = "P2"
    run_location = "cloud"

    # Sprint D1 / PR H 批次 2：投诉处理源于体验缺陷，改进建议闭环到出餐时长
    constraint_scope = {"experience"}

    def get_supported_actions(self) -> list[str]:
        return [
            "analyze_feedback",
            "handle_complaint",
            "generate_improvements",
            "assess_training_needs",
            "generate_training_plan",
            "track_training_progress",
            "evaluate_effectiveness",
            "analyze_skill_gaps",
            "manage_certificates",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "handle_complaint": self._handle_complaint,
            "assess_training_needs": self._assess_training,
            "analyze_skill_gaps": self._analyze_skill_gaps,
            "evaluate_effectiveness": self._evaluate_effectiveness,
            "generate_improvements": self._generate_improvements,
            "analyze_feedback": self._analyze_feedback,
            "generate_training_plan": self._training_plan,
            "track_training_progress": self._track_progress,
            "manage_certificates": self._manage_certs,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"Unsupported: {action}")

    async def _handle_complaint(self, params: dict) -> AgentResult:
        """投诉处理闭环"""
        complaint_type = params.get("type", "other")
        description = params.get("description", "")
        customer_id = params.get("customer_id")

        priority = COMPLAINT_PRIORITY.get(complaint_type, 3)
        auto_assign = priority <= 2  # 高优先级自动分配到店长

        # 解决方案模板
        solutions = {
            "food_quality": "1.向顾客致歉 2.重做/换菜 3.赠送甜品 4.记录问题菜品反馈厨房",
            "service_attitude": "1.店长亲自道歉 2.赠送优惠券 3.对涉事员工进行沟通",
            "wait_time": "1.赠送饮品/小食 2.告知预计等待时间 3.优先出餐",
            "hygiene": "1.立即整改 2.向顾客致歉+免单/折扣 3.全店卫生检查",
            "billing": "1.核实账单明细 2.多收退还+致歉 3.确认系统价格",
        }

        return AgentResult(
            success=True,
            action="handle_complaint",
            data={
                "complaint_type": complaint_type,
                "priority": priority,
                "priority_label": "紧急" if priority == 1 else "一般" if priority == 2 else "低",
                "auto_assign_manager": auto_assign,
                "suggested_solution": solutions.get(complaint_type, "了解情况后酌情处理"),
                "follow_up_hours": 24 if priority <= 2 else 48,
                "compensation": "免单" if priority == 1 else "优惠券" if priority == 2 else "致歉",
            },
            reasoning=f"投诉类型 {complaint_type}，优先级 {priority}",
            confidence=0.85,
        )

    async def _assess_training(self, params: dict) -> AgentResult:
        """培训需求评估"""
        employees = params.get("employees", [])
        needs = []

        for emp in employees:
            role = emp.get("role", "waiter")
            current_skills = emp.get("skills", [])
            performance_score = emp.get("performance_score", 50)
            required = ROLE_SKILLS.get(role, [])

            missing = [s for s in required if s not in current_skills]
            urgency = (
                "high"
                if performance_score < 60 or len(missing) >= 3
                else "medium"
                if performance_score < 80 or len(missing) >= 1
                else "low"
            )

            if missing or performance_score < 80:
                needs.append(
                    {
                        "employee": emp.get("name", ""),
                        "role": role,
                        "missing_skills": missing,
                        "performance_score": performance_score,
                        "urgency": urgency,
                        "recommended_courses": [f"{s}培训" for s in missing[:3]],
                    }
                )

        needs.sort(key=lambda n: {"high": 0, "medium": 1, "low": 2}[n["urgency"]])

        return AgentResult(
            success=True,
            action="assess_training_needs",
            data={"needs": needs, "total": len(needs)},
            reasoning=f"{len(needs)} 名员工需要培训，{sum(1 for n in needs if n['urgency'] == 'high')} 人紧急",
            confidence=0.8,
        )

    async def _analyze_skill_gaps(self, params: dict) -> AgentResult:
        """技能差距分析"""
        role = params.get("role", "waiter")
        current_scores = params.get("skill_scores", {})  # {"服务礼仪": 80, ...}
        required = ROLE_SKILLS.get(role, [])

        gaps = []
        for skill in required:
            score = current_scores.get(skill, 0)
            gap = max(0, 80 - score)  # 80分为合格线
            if gap > 0:
                gaps.append(
                    {
                        "skill": skill,
                        "current_score": score,
                        "target_score": 80,
                        "gap": gap,
                        "impact_yuan": gap * 50,  # 简化：每分差距=50元/月潜在损失
                    }
                )

        gaps.sort(key=lambda g: g["gap"], reverse=True)
        total_impact = sum(g["impact_yuan"] for g in gaps)

        return AgentResult(
            success=True,
            action="analyze_skill_gaps",
            data={
                "role": role,
                "gaps": gaps,
                "total_gap_impact_yuan": total_impact,
                "priority_training": [g["skill"] for g in gaps[:3]],
            },
            reasoning=f"{role} 有 {len(gaps)} 个技能差距，潜在月损失 ¥{total_impact}",
            confidence=0.75,
        )

    async def _evaluate_effectiveness(self, params: dict) -> AgentResult:
        """培训效果评估"""
        pre_scores = params.get("pre_scores", [])
        post_scores = params.get("post_scores", [])
        attendance_rate = params.get("attendance_rate", 0)

        if not pre_scores or not post_scores:
            return AgentResult(success=False, action="evaluate_effectiveness", error="需要培训前后评分数据")

        pre_avg = statistics.mean(pre_scores)
        post_avg = statistics.mean(post_scores)
        improvement = post_avg - pre_avg
        retention_rate = min(100, post_avg / max(1, pre_avg) * 100) if pre_avg > 0 else 0

        return AgentResult(
            success=True,
            action="evaluate_effectiveness",
            data={
                "pre_avg_score": round(pre_avg, 1),
                "post_avg_score": round(post_avg, 1),
                "improvement": round(improvement, 1),
                "improvement_pct": round(improvement / max(1, pre_avg) * 100, 1),
                "attendance_rate": attendance_rate,
                "knowledge_retention_pct": round(retention_rate, 1),
                "effectiveness": "high" if improvement > 15 else "medium" if improvement > 5 else "low",
                "roi_estimate": f"培训投入回报率约 {round(improvement * 10)}%",
            },
            reasoning=f"平均提升 {improvement:.1f} 分（{pre_avg:.0f}→{post_avg:.0f}）",
            confidence=0.8,
        )

    async def _generate_improvements(self, params: dict) -> AgentResult:
        """生成服务改进建议"""
        issues = params.get("top_issues", [])
        improvements = []

        for issue in issues[:5]:
            issue_type = issue.get("type", "other")
            count = issue.get("count", 0)
            improvements.append(
                {
                    "issue": issue_type,
                    "occurrence": count,
                    "suggestion": {
                        "wait_time": "增加高峰时段人手，优化出餐流程",
                        "food_quality": "加强厨房质检，更新SOP操作规范",
                        "service_attitude": "开展服务礼仪培训，建立激励机制",
                        "hygiene": "增加清洁频次，引入检查打卡制度",
                    }.get(issue_type, "针对性改进"),
                    "priority": "high" if count >= 5 else "medium",
                    "expected_effect": f"预计减少 {min(count, count // 2 + 1)} 次同类问题",
                }
            )

        return AgentResult(
            success=True,
            action="generate_improvements",
            data={"improvements": improvements, "total": len(improvements)},
            reasoning=f"生成 {len(improvements)} 条改进建议",
            confidence=0.8,
        )

    async def _analyze_feedback(self, params: dict) -> AgentResult:
        feedbacks = params.get("feedbacks", [])
        if not feedbacks:
            return AgentResult(success=True, action="analyze_feedback", data={"total": 0}, confidence=0.5)
        positive = sum(1 for f in feedbacks if f.get("rating", 3) >= 4)
        negative = sum(1 for f in feedbacks if f.get("rating", 3) <= 2)
        return AgentResult(
            success=True,
            action="analyze_feedback",
            data={
                "total": len(feedbacks),
                "positive": positive,
                "negative": negative,
                "sentiment_score": round(positive / len(feedbacks) * 100, 1),
            },
            reasoning=f"好评 {positive}/{len(feedbacks)}",
            confidence=0.8,
        )

    async def _training_plan(self, params: dict) -> AgentResult:
        role = params.get("role", "waiter")
        gaps = params.get("skill_gaps", [])
        plan = [{"week": i + 1, "skill": g, "method": "实操+理论", "hours": 4} for i, g in enumerate(gaps[:4])]
        return AgentResult(
            success=True,
            action="generate_training_plan",
            data={"role": role, "plan": plan, "total_weeks": len(plan), "total_hours": len(plan) * 4},
            reasoning=f"为 {role} 生成 {len(plan)} 周培训计划",
            confidence=0.8,
        )

    async def _track_progress(self, params: dict) -> AgentResult:
        records = params.get("records", [])
        completed = sum(1 for r in records if r.get("completed"))
        total = len(records)
        return AgentResult(
            success=True,
            action="track_training_progress",
            data={
                "completed": completed,
                "total": total,
                "completion_pct": round(completed / total * 100, 1) if total > 0 else 0,
            },
            reasoning=f"完成 {completed}/{total}",
            confidence=0.9,
        )

    async def _manage_certs(self, params: dict) -> AgentResult:
        certs = params.get("certificates", [])
        expiring = [c for c in certs if c.get("remaining_days", 999) <= 30]
        expired = [c for c in certs if c.get("remaining_days", 999) <= 0]
        return AgentResult(
            success=True,
            action="manage_certificates",
            data={
                "total": len(certs),
                "expired": len(expired),
                "expiring": len(expiring),
                "needs_attention": expired + expiring,
            },
            reasoning=f"{len(expired)} 过期，{len(expiring)} 即将过期",
            confidence=0.9,
        )
