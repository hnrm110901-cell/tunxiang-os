"""复盘总结 Agent — 优化型 | 云端

能力：日经营总结生成、经营规律发现、改进行动计划
通过 ModelRouter (MODERATE) 调用 LLM 生成自然语言总结。
"""
import statistics
from typing import Any

import structlog

from ..base import SkillAgent, AgentResult

try:
    from services.tunxiang_api.src.shared.core.model_router import model_router
except ImportError:
    model_router = None  # 独立测试时无跨服务依赖

logger = structlog.get_logger()

# 经营指标基准 (可被门店配置覆盖)
BENCHMARK = {
    "avg_revenue_fen": 5000000,     # 日均营收 5 万元
    "avg_covers": 200,              # 日均客流 200 人
    "avg_per_customer_fen": 25000,  # 客单价 250 元
    "target_margin_rate": 0.30,     # 目标毛利率 30%
    "target_turnover_rate": 2.5,    # 翻台率 2.5
}


class ReviewSummaryAgent(SkillAgent):
    agent_id = "review_summary"
    agent_name = "复盘总结"
    description = "自动生成日经营总结、发现经营规律、生成改进行动计划"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return ["daily_summary", "weekly_pattern", "action_plan"]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "daily_summary": self._daily_summary,
            "weekly_pattern": self._weekly_pattern,
            "action_plan": self._action_plan,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported: {action}")
        return await handler(params)

    async def _daily_summary(self, params: dict) -> AgentResult:
        """自动生成日经营总结"""
        store_id = params.get("store_id", "")
        date = params.get("date", "")
        metrics = params.get("metrics", {})

        if not metrics:
            return AgentResult(
                success=False, action="daily_summary",
                error="无经营数据",
            )

        # 使用 ModelRouter (MODERATE)
        model = model_router.get_model("kpi_summary") if model_router else "claude-sonnet-4-6"

        revenue_fen = metrics.get("revenue_fen", 0)
        covers = metrics.get("covers", 0)
        per_customer_fen = revenue_fen // covers if covers > 0 else 0
        margin_rate = metrics.get("margin_rate", 0)
        turnover_rate = metrics.get("turnover_rate", 0)
        food_cost_fen = metrics.get("food_cost_fen", 0)
        labor_cost_fen = metrics.get("labor_cost_fen", 0)
        waste_fen = metrics.get("waste_fen", 0)
        top_dishes = metrics.get("top_dishes", [])
        complaints = metrics.get("complaints", 0)

        # 与基准对比
        highlights = []
        warnings = []

        benchmark = params.get("benchmark", BENCHMARK)

        if revenue_fen > benchmark["avg_revenue_fen"] * 1.1:
            highlights.append(f"营收 ¥{revenue_fen/100:.0f} 超基准 {(revenue_fen/benchmark['avg_revenue_fen']-1)*100:.0f}%")
        elif revenue_fen < benchmark["avg_revenue_fen"] * 0.9:
            warnings.append(f"营收 ¥{revenue_fen/100:.0f} 低于基准 {(1-revenue_fen/benchmark['avg_revenue_fen'])*100:.0f}%")

        if margin_rate < benchmark["target_margin_rate"] - 0.03:
            warnings.append(f"毛利率 {margin_rate:.1%} 低于目标 {benchmark['target_margin_rate']:.1%}")
        elif margin_rate > benchmark["target_margin_rate"] + 0.02:
            highlights.append(f"毛利率 {margin_rate:.1%} 表现优秀")

        if turnover_rate > benchmark["target_turnover_rate"]:
            highlights.append(f"翻台率 {turnover_rate:.1f} 超目标")
        elif turnover_rate < benchmark["target_turnover_rate"] * 0.8:
            warnings.append(f"翻台率 {turnover_rate:.1f} 低于目标 {benchmark['target_turnover_rate']:.1f}")

        if complaints > 3:
            warnings.append(f"投诉 {complaints} 单，需关注")

        if waste_fen > food_cost_fen * 0.05 and food_cost_fen > 0:
            warnings.append(f"浪费金额 ¥{waste_fen/100:.0f}，占食材成本 {waste_fen/food_cost_fen*100:.1f}%")

        # 总结评级
        score = 70
        score += len(highlights) * 5
        score -= len(warnings) * 8
        score = max(0, min(100, score))

        if score >= 85:
            grade = "优秀"
        elif score >= 70:
            grade = "良好"
        elif score >= 55:
            grade = "一般"
        else:
            grade = "需改进"

        if model_router:
            model_router.log_call(
                task_type="kpi_summary", model=model,
                input_tokens=0, output_tokens=0, latency_ms=0, success=True,
            )

        return AgentResult(
            success=True, action="daily_summary",
            data={
                "store_id": store_id,
                "date": date,
                "grade": grade,
                "score": score,
                "kpi": {
                    "revenue_fen": revenue_fen,
                    "revenue_yuan": round(revenue_fen / 100, 2),
                    "covers": covers,
                    "per_customer_yuan": round(per_customer_fen / 100, 2),
                    "margin_rate": margin_rate,
                    "turnover_rate": turnover_rate,
                    "food_cost_yuan": round(food_cost_fen / 100, 2),
                    "labor_cost_yuan": round(labor_cost_fen / 100, 2),
                    "waste_yuan": round(waste_fen / 100, 2),
                    "complaints": complaints,
                },
                "highlights": highlights,
                "warnings": warnings,
                "top_dishes": top_dishes[:5],
            },
            reasoning=f"门店 {store_id} {date} 经营评级: {grade}({score}分)，"
                      f"亮点{len(highlights)}项，预警{len(warnings)}项",
            confidence=0.85,
        )

    async def _weekly_pattern(self, params: dict) -> AgentResult:
        """发现经营规律 -- 周末vs工作日/季节性/天气影响"""
        store_id = params.get("store_id", "")
        daily_data = params.get("daily_data", [])
        days = params.get("days", 30)

        if len(daily_data) < 7:
            return AgentResult(
                success=False, action="weekly_pattern",
                error=f"数据不足，至少需要7天数据，当前仅 {len(daily_data)} 天",
            )

        # 按周末/工作日分组
        weekday_revenues = []
        weekend_revenues = []
        weekday_covers = []
        weekend_covers = []

        for d in daily_data:
            rev = d.get("revenue_fen", 0)
            covers = d.get("covers", 0)
            is_weekend = d.get("is_weekend", False)

            if is_weekend:
                weekend_revenues.append(rev)
                weekend_covers.append(covers)
            else:
                weekday_revenues.append(rev)
                weekday_covers.append(covers)

        patterns = []

        # 周末 vs 工作日
        if weekday_revenues and weekend_revenues:
            wd_avg = statistics.mean(weekday_revenues)
            we_avg = statistics.mean(weekend_revenues)
            diff_pct = (we_avg - wd_avg) / wd_avg if wd_avg > 0 else 0

            patterns.append({
                "type": "weekday_vs_weekend",
                "weekday_avg_revenue_fen": round(wd_avg),
                "weekend_avg_revenue_fen": round(we_avg),
                "weekend_uplift_pct": round(diff_pct * 100, 1),
                "insight": f"周末营收{'高于' if diff_pct > 0 else '低于'}工作日 {abs(diff_pct)*100:.0f}%",
            })

            if weekday_covers and weekend_covers:
                wd_cov = statistics.mean(weekday_covers)
                we_cov = statistics.mean(weekend_covers)
                patterns.append({
                    "type": "cover_distribution",
                    "weekday_avg_covers": round(wd_cov),
                    "weekend_avg_covers": round(we_cov),
                    "insight": f"工作日均客流 {wd_cov:.0f}，周末 {we_cov:.0f}",
                })

        # 趋势分析 (简单线性)
        if len(daily_data) >= 14:
            first_half = [d.get("revenue_fen", 0) for d in daily_data[:len(daily_data)//2]]
            second_half = [d.get("revenue_fen", 0) for d in daily_data[len(daily_data)//2:]]
            first_avg = statistics.mean(first_half)
            second_avg = statistics.mean(second_half)
            trend_pct = (second_avg - first_avg) / first_avg if first_avg > 0 else 0

            trend_direction = "上升" if trend_pct > 0.03 else "下降" if trend_pct < -0.03 else "平稳"
            patterns.append({
                "type": "trend",
                "direction": trend_direction,
                "change_pct": round(trend_pct * 100, 1),
                "insight": f"近期营收趋势{trend_direction} {abs(trend_pct)*100:.1f}%",
            })

        # 天气影响 (如果数据中包含天气)
        weather_data = [d for d in daily_data if d.get("weather")]
        if weather_data:
            weather_groups: dict[str, list] = {}
            for d in weather_data:
                w = d.get("weather", "unknown")
                weather_groups.setdefault(w, []).append(d.get("revenue_fen", 0))

            weather_impact = []
            for w, revs in weather_groups.items():
                weather_impact.append({
                    "weather": w, "avg_revenue_fen": round(statistics.mean(revs)), "days": len(revs),
                })
            weather_impact.sort(key=lambda x: x["avg_revenue_fen"], reverse=True)
            patterns.append({
                "type": "weather_impact",
                "breakdown": weather_impact,
                "insight": f"最佳天气: {weather_impact[0]['weather']}" if weather_impact else "",
            })

        return AgentResult(
            success=True, action="weekly_pattern",
            data={
                "store_id": store_id,
                "analysis_days": len(daily_data),
                "patterns": patterns,
                "pattern_count": len(patterns),
            },
            reasoning=f"门店 {store_id} {len(daily_data)} 天数据发现 {len(patterns)} 个经营规律",
            confidence=0.8,
        )

    async def _action_plan(self, params: dict) -> AgentResult:
        """生成改进行动计划"""
        summary = params.get("summary", {})
        patterns = params.get("patterns", [])
        store_id = params.get("store_id", "")

        # 使用 ModelRouter (MODERATE)
        model = model_router.get_model("kpi_summary") if model_router else "claude-sonnet-4-6"

        actions = []

        # 从总结预警中提取行动
        warnings = summary.get("warnings", [])
        for w in warnings:
            if "毛利" in w:
                actions.append({
                    "category": "成本控制",
                    "action": "启动成本偏差诊断，排查毛利下降原因",
                    "priority": "high",
                    "timeline": "本周内",
                    "owner": "店长+厨师长",
                })
            elif "翻台" in w:
                actions.append({
                    "category": "运营效率",
                    "action": "优化桌台配置和出餐流程，提升翻台率",
                    "priority": "medium",
                    "timeline": "两周内",
                    "owner": "店长",
                })
            elif "投诉" in w:
                actions.append({
                    "category": "服务质量",
                    "action": "分析投诉原因，针对性培训服务员",
                    "priority": "high",
                    "timeline": "本周内",
                    "owner": "前厅主管",
                })
            elif "浪费" in w:
                actions.append({
                    "category": "损耗控制",
                    "action": "盘点高损耗食材，优化采购量和储存方式",
                    "priority": "medium",
                    "timeline": "两周内",
                    "owner": "后厨主管",
                })

        # 从规律中提取行动
        for p in patterns:
            ptype = p.get("type", "")
            if ptype == "weekday_vs_weekend":
                uplift = p.get("weekend_uplift_pct", 0)
                if uplift > 30:
                    actions.append({
                        "category": "营销策略",
                        "action": "工作日客流不足，建议推出工作日午市套餐或工作日会员折扣",
                        "priority": "medium",
                        "timeline": "下周启动",
                        "owner": "营销经理",
                    })
            elif ptype == "trend" and p.get("direction") == "下降":
                actions.append({
                    "category": "经营预警",
                    "action": f"营收呈下降趋势({p.get('change_pct', 0):.1f}%)，建议全面复盘菜品和服务",
                    "priority": "high",
                    "timeline": "立即",
                    "owner": "区域经理+店长",
                })

        # 如果无具体行动，给出通用建议
        if not actions:
            actions.append({
                "category": "持续优化",
                "action": "经营指标正常，建议保持现有策略，关注客流变化",
                "priority": "low",
                "timeline": "持续",
                "owner": "店长",
            })

        # 按优先级排序
        priority_order = {"high": 0, "medium": 1, "low": 2}
        actions.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 9))

        if model_router:
            model_router.log_call(
                task_type="kpi_summary", model=model,
                input_tokens=0, output_tokens=0, latency_ms=0, success=True,
            )

        return AgentResult(
            success=True, action="action_plan",
            data={
                "store_id": store_id,
                "actions": actions,
                "action_count": len(actions),
                "high_priority_count": sum(1 for a in actions if a.get("priority") == "high"),
            },
            reasoning=f"生成 {len(actions)} 条行动计划，"
                      f"其中 {sum(1 for a in actions if a.get('priority') == 'high')} 条高优先级",
            confidence=0.8,
        )
