"""决策效果追踪闭环

记录执行 → 计算效果 → 生成学习上下文 → 统计 Agent 表现。
形成"决策 → 执行 → 效果 → 学习 → 更优决策"正循环。
"""
import time
import uuid
from typing import Optional

import structlog

logger = structlog.get_logger()


class DecisionFeedbackService:
    """决策效果追踪闭环"""

    @staticmethod
    def record_execution(
        decision_id: str,
        executed_by: str,
        execution_data: dict,
    ) -> dict:
        """记录决策已执行

        Args:
            decision_id: 决策 ID
            executed_by: 执行人
            execution_data: 执行详情

        Returns:
            执行记录
        """
        record = {
            "decision_id": decision_id,
            "executed_by": executed_by,
            "execution_data": execution_data,
            "executed_at": time.time(),
            "status": "executed",
        }
        logger.info(
            "decision_executed",
            decision_id=decision_id,
            executed_by=executed_by,
        )
        return record

    @staticmethod
    def compute_outcome(
        decision_type: str,
        before_data: dict,
        after_data: dict,
    ) -> dict:
        """计算决策效果

        根据不同决策类型对比前后指标变化：
        - menu_push: 对比菜品销量变化
        - procurement: 对比是否避免缺货
        - staffing: 对比人效变化
        - marketing: 对比触达率/转化率

        Args:
            decision_type: 决策类型
            before_data: 决策前数据
            after_data: 决策后数据

        Returns:
            {outcome_score, outcome_summary, metrics_delta}
        """
        metrics_delta: dict = {}
        outcome_summary = ""
        outcome_score = 50.0  # 基准分

        if decision_type == "menu_push":
            # 菜品销量变化
            before_sales = before_data.get("sales_count", 0)
            after_sales = after_data.get("sales_count", 0)
            sales_change = after_sales - before_sales
            sales_pct = (sales_change / before_sales * 100) if before_sales > 0 else 0.0

            before_revenue = before_data.get("revenue", 0)
            after_revenue = after_data.get("revenue", 0)
            revenue_change = after_revenue - before_revenue

            metrics_delta = {
                "sales_count": {"before": before_sales, "after": after_sales, "change": sales_change, "pct": round(sales_pct, 1)},
                "revenue": {"before": before_revenue, "after": after_revenue, "change": revenue_change},
            }

            # 评分：销量增长幅度映射到 0-100
            if sales_pct >= 50:
                outcome_score = 95.0
            elif sales_pct >= 30:
                outcome_score = 85.0
            elif sales_pct >= 10:
                outcome_score = 75.0
            elif sales_pct >= 0:
                outcome_score = 60.0
            elif sales_pct >= -10:
                outcome_score = 45.0
            else:
                outcome_score = 30.0

            sign = "+" if sales_pct >= 0 else ""
            outcome_summary = f"销量{sign}{sales_pct:.0f}%"

        elif decision_type == "procurement":
            # 是否避免缺货
            shortage_before = before_data.get("shortage_count", 0)
            shortage_after = after_data.get("shortage_count", 0)
            waste_before = before_data.get("waste_rate", 0)
            waste_after = after_data.get("waste_rate", 0)

            metrics_delta = {
                "shortage_count": {"before": shortage_before, "after": shortage_after, "change": shortage_after - shortage_before},
                "waste_rate": {"before": waste_before, "after": waste_after, "change": round(waste_after - waste_before, 2)},
            }

            # 评分：缺货减少 + 损耗降低
            shortage_improvement = shortage_before - shortage_after
            waste_improvement = waste_before - waste_after

            outcome_score = 50.0
            if shortage_improvement > 0:
                outcome_score += min(30, shortage_improvement * 10)
            if waste_improvement > 0:
                outcome_score += min(20, waste_improvement * 100)
            if shortage_after == 0:
                outcome_score = max(outcome_score, 80.0)
            outcome_score = min(100.0, outcome_score)

            parts = []
            if shortage_improvement > 0:
                parts.append(f"缺货减少{shortage_improvement}次")
            elif shortage_improvement == 0 and shortage_after == 0:
                parts.append("无缺货")
            else:
                parts.append(f"缺货增加{abs(shortage_improvement)}次")
            outcome_summary = "，".join(parts) if parts else "采购效果持平"

        elif decision_type == "staffing":
            # 人效变化
            before_efficiency = before_data.get("efficiency", 0)
            after_efficiency = after_data.get("efficiency", 0)
            before_labor_cost = before_data.get("labor_cost", 0)
            after_labor_cost = after_data.get("labor_cost", 0)

            eff_change = after_efficiency - before_efficiency
            eff_pct = (eff_change / before_efficiency * 100) if before_efficiency > 0 else 0.0
            cost_change = after_labor_cost - before_labor_cost

            metrics_delta = {
                "efficiency": {"before": before_efficiency, "after": after_efficiency, "change": round(eff_change, 2), "pct": round(eff_pct, 1)},
                "labor_cost": {"before": before_labor_cost, "after": after_labor_cost, "change": cost_change},
            }

            if eff_pct >= 20:
                outcome_score = 90.0
            elif eff_pct >= 10:
                outcome_score = 80.0
            elif eff_pct >= 0:
                outcome_score = 60.0
            elif eff_pct >= -10:
                outcome_score = 40.0
            else:
                outcome_score = 25.0

            sign = "+" if eff_pct >= 0 else ""
            outcome_summary = f"人效{sign}{eff_pct:.0f}%"

        elif decision_type == "marketing":
            # 触达率 / 转化率
            before_reach = before_data.get("reach_rate", 0)
            after_reach = after_data.get("reach_rate", 0)
            before_conversion = before_data.get("conversion_rate", 0)
            after_conversion = after_data.get("conversion_rate", 0)

            reach_change = after_reach - before_reach
            conv_change = after_conversion - before_conversion

            metrics_delta = {
                "reach_rate": {"before": before_reach, "after": after_reach, "change": round(reach_change, 3)},
                "conversion_rate": {"before": before_conversion, "after": after_conversion, "change": round(conv_change, 3)},
            }

            # 转化率权重更高
            outcome_score = 50.0
            if conv_change > 0:
                outcome_score += min(30, conv_change * 1000)
            if reach_change > 0:
                outcome_score += min(20, reach_change * 200)
            outcome_score = min(100.0, max(0.0, outcome_score))

            parts = []
            if reach_change != 0:
                sign = "+" if reach_change > 0 else ""
                parts.append(f"触达率{sign}{reach_change * 100:.1f}%")
            if conv_change != 0:
                sign = "+" if conv_change > 0 else ""
                parts.append(f"转化率{sign}{conv_change * 100:.1f}%")
            outcome_summary = "，".join(parts) if parts else "营销效果持平"

        else:
            outcome_summary = f"未知决策类型: {decision_type}"
            outcome_score = 50.0

        return {
            "outcome_score": round(outcome_score, 1),
            "outcome_summary": outcome_summary,
            "metrics_delta": metrics_delta,
            "decision_type": decision_type,
        }

    @staticmethod
    def compute_effectiveness_score(outcome_data: dict) -> float:
        """综合效果评分 0-100

        如果 outcome_data 中已包含 outcome_score 则直接使用，
        否则根据 metrics_delta 中的正向变化比例计算。

        Args:
            outcome_data: 含 outcome_score 或 metrics_delta 的结果数据

        Returns:
            0-100 的综合评分
        """
        if "outcome_score" in outcome_data:
            return float(min(100.0, max(0.0, outcome_data["outcome_score"])))

        metrics_delta = outcome_data.get("metrics_delta", {})
        if not metrics_delta:
            return 50.0

        scores = []
        for _key, delta in metrics_delta.items():
            if isinstance(delta, dict):
                pct = delta.get("pct", 0)
                change = delta.get("change", 0)
                # 正向变化得高分
                if pct != 0:
                    scores.append(min(100, max(0, 50 + pct)))
                elif change > 0:
                    scores.append(70)
                elif change < 0:
                    scores.append(30)
                else:
                    scores.append(50)

        if not scores:
            return 50.0
        return round(min(100.0, max(0.0, sum(scores) / len(scores))), 1)

    @staticmethod
    def generate_learning_context(
        past_decisions: list[dict],
        limit: int = 10,
    ) -> str:
        """生成 Agent 学习上下文（注入 prompt 提升质量）

        将最近 N 条决策的效果摘要格式化为文本。

        Args:
            past_decisions: 过往决策列表，每条含 title/outcome_summary/outcome_score
            limit: 最多取几条

        Returns:
            格式化文本，用于注入 Agent prompt
        """
        if not past_decisions:
            return "历史决策参考：暂无历史决策数据。"

        selected = past_decisions[:limit]
        lines = ["历史决策参考："]
        for i, d in enumerate(selected, 1):
            title = d.get("title", "未知决策")
            summary = d.get("outcome_summary", "效果未知")
            score = d.get("outcome_score", 0)
            lines.append(f"{i}. {title} -> {summary}（效果分{score:.0f}）")

        return "\n".join(lines)

    @staticmethod
    def get_agent_stats(decisions: list[dict]) -> dict:
        """Agent 决策统计

        Args:
            decisions: 决策列表，每条含 status, outcome_score 等

        Returns:
            {total, adopted_count, adoption_rate, avg_score, top_decisions, worst_decisions}
        """
        total = len(decisions)
        if total == 0:
            return {
                "total": 0,
                "adopted_count": 0,
                "adoption_rate": 0.0,
                "avg_score": 0.0,
                "top_decisions": [],
                "worst_decisions": [],
            }

        adopted = [d for d in decisions if d.get("status") in ("executed", "adopted", "approved")]
        adopted_count = len(adopted)
        adoption_rate = round(adopted_count / total * 100, 1)

        scored = [d for d in decisions if "outcome_score" in d]
        avg_score = round(sum(d["outcome_score"] for d in scored) / len(scored), 1) if scored else 0.0

        sorted_by_score = sorted(scored, key=lambda d: d.get("outcome_score", 0), reverse=True)
        top_decisions = sorted_by_score[:3]
        worst_decisions = sorted_by_score[-3:] if len(sorted_by_score) >= 3 else sorted_by_score

        return {
            "total": total,
            "adopted_count": adopted_count,
            "adoption_rate": adoption_rate,
            "avg_score": avg_score,
            "top_decisions": top_decisions,
            "worst_decisions": worst_decisions,
        }
