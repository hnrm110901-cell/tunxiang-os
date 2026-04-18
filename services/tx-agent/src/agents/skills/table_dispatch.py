"""桌台调度建议 Agent — 优化型 | 云端

能力：桌台利用率分析、最优桌台推荐、等位时间预测
通过 ModelRouter (MODERATE) 调用 LLM 生成调度建议。
"""
from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

try:
    from services.tunxiang_api.src.shared.core.model_router import model_router
except ImportError:
    model_router = None  # 独立测试时无跨服务依赖

logger = structlog.get_logger()

# 桌台类型权重
TABLE_TYPE_WEIGHTS = {
    "small_2": {"capacity": 2, "turnover_target_min": 45},
    "medium_4": {"capacity": 4, "turnover_target_min": 60},
    "large_6": {"capacity": 6, "turnover_target_min": 75},
    "large_8": {"capacity": 8, "turnover_target_min": 90},
    "vip_room": {"capacity": 12, "turnover_target_min": 120},
}

# 等位容忍阈值
MAX_ACCEPTABLE_WAIT_MINUTES = 30


class TableDispatchAgent(SkillAgent):
    agent_id = "table_dispatch"
    agent_name = "桌台调度建议"
    description = "桌台利用率分析、最优桌台推荐（VIP/等位/翻台）、等位时间预测"
    priority = "P1"
    run_location = "cloud"

    # Sprint D1 / PR H 批次 2：桌台调度影响等位/翻台体验
    constraint_scope = {"experience"}

    def get_supported_actions(self) -> list[str]:
        return ["suggest_seating", "analyze_utilization", "predict_wait"]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "suggest_seating": self._suggest_seating,
            "analyze_utilization": self._analyze_utilization,
            "predict_wait": self._predict_wait,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported: {action}")
        return await handler(params)

    async def _suggest_seating(self, params: dict) -> AgentResult:
        """最优桌台推荐 -- 考虑 VIP/等位时间/翻台目标"""
        party_size = params.get("party_size", 2)
        is_vip = params.get("is_vip", False)
        tables = params.get("available_tables", [])
        preferences = params.get("preferences", {})

        if not tables:
            return AgentResult(
                success=True, action="suggest_seating",
                data={"recommended_table": None, "reason": "无可用桌台，建议等位"},
                reasoning="当前无空闲桌台",
                confidence=0.9,
            )

        scored = []
        for t in tables:
            score = 50.0
            capacity = t.get("capacity", 4)
            table_type = t.get("table_type", "medium_4")

            # 容量匹配度: 容量刚好合适最优，浪费座位扣分
            if capacity < party_size:
                continue  # 坐不下，跳过
            waste = capacity - party_size
            score -= waste * 5  # 每浪费一个座位扣 5 分

            # VIP 偏好
            if is_vip and table_type == "vip_room":
                score += 30
            elif is_vip and t.get("location") == "window":
                score += 15

            # 位置偏好
            preferred_location = preferences.get("location")
            if preferred_location and t.get("location") == preferred_location:
                score += 20

            # 翻台效率: 优先推荐距上次翻台时间较长的桌台(已清洁就绪)
            idle_minutes = t.get("idle_minutes", 0)
            if idle_minutes > 10:
                score += 10

            # 距离出餐口近的加分
            if t.get("near_kitchen", False):
                score += 5

            scored.append({**t, "match_score": round(max(0, min(100, score)), 1)})

        scored.sort(key=lambda x: x["match_score"], reverse=True)
        best = scored[0] if scored else None

        return AgentResult(
            success=True, action="suggest_seating",
            data={
                "recommended_table": best,
                "alternatives": scored[1:3],
                "party_size": party_size,
                "is_vip": is_vip,
                "total_evaluated": len(scored),
            },
            reasoning=f"为 {party_size} 人{'VIP' if is_vip else ''}推荐桌台 {best.get('table_id', '?') if best else '无'}，"
                      f"评分 {best.get('match_score', 0) if best else 0}",
            confidence=0.85,
        )

    async def _analyze_utilization(self, params: dict) -> AgentResult:
        """分析桌台利用率，建议调整桌台配置"""
        store_id = params.get("store_id", "")
        tables = params.get("tables", [])
        period_hours = params.get("period_hours", 24)

        if not tables:
            return AgentResult(
                success=False, action="analyze_utilization",
                error="无桌台数据",
            )

        # 使用 ModelRouter 选择模型 (MODERATE)
        model = model_router.get_model("kpi_summary") if model_router else "claude-sonnet-4-6"

        type_stats: dict[str, dict] = {}
        total_occupied_minutes = 0
        total_capacity_minutes = 0

        for t in tables:
            ttype = t.get("table_type", "unknown")
            occupied_min = t.get("occupied_minutes", 0)
            capacity = t.get("capacity", 4)
            capacity_min = period_hours * 60

            total_occupied_minutes += occupied_min
            total_capacity_minutes += capacity_min

            if ttype not in type_stats:
                type_stats[ttype] = {"count": 0, "total_occupied_min": 0, "total_capacity_min": 0,
                                     "total_seats": 0, "total_covers": 0}
            type_stats[ttype]["count"] += 1
            type_stats[ttype]["total_occupied_min"] += occupied_min
            type_stats[ttype]["total_capacity_min"] += capacity_min
            type_stats[ttype]["total_seats"] += capacity
            type_stats[ttype]["total_covers"] += t.get("covers_served", 0)

        overall_utilization = total_occupied_minutes / total_capacity_minutes if total_capacity_minutes > 0 else 0

        # 生成建议
        suggestions = []
        for ttype, stats in type_stats.items():
            util = stats["total_occupied_min"] / stats["total_capacity_min"] if stats["total_capacity_min"] > 0 else 0
            type_stats[ttype]["utilization_rate"] = round(util, 4)

            if util < 0.3:
                suggestions.append(f"{ttype} 利用率仅 {util:.0%}，建议减少或合并为其他桌型")
            elif util > 0.85:
                suggestions.append(f"{ttype} 利用率 {util:.0%}，已接近饱和，建议增加此桌型")

        if model_router:
            model_router.log_call(
                task_type="kpi_summary", model=model,
                input_tokens=0, output_tokens=0, latency_ms=0, success=True,
            )

        return AgentResult(
            success=True, action="analyze_utilization",
            data={
                "store_id": store_id,
                "overall_utilization": round(overall_utilization, 4),
                "type_breakdown": type_stats,
                "suggestions": suggestions,
                "period_hours": period_hours,
                "total_tables": len(tables),
            },
            reasoning=f"门店 {store_id} 整体桌台利用率 {overall_utilization:.0%}，"
                      f"共 {len(suggestions)} 条优化建议",
            confidence=0.8,
        )

    async def _predict_wait(self, params: dict) -> AgentResult:
        """等位时间预测"""
        store_id = params.get("store_id", "")
        current_queue = params.get("current_queue", 0)
        avg_turnover_min = params.get("avg_turnover_minutes", 60)
        available_tables = params.get("available_tables_count", 0)
        total_tables = params.get("total_tables", 20)
        party_size = params.get("party_size", 2)

        # 简单排队模型: 等位 = (排队组数 / 预计空出桌数) * 平均用餐时间
        if available_tables > 0:
            predicted_wait = 0
        elif total_tables > 0:
            # 预计每个翻台周期空出的桌数
            tables_per_cycle = max(1, total_tables * 0.2)  # 假设 20% 桌台在一个周期内翻台
            cycles_needed = (current_queue + 1) / tables_per_cycle
            predicted_wait = round(cycles_needed * avg_turnover_min * 0.5)
        else:
            predicted_wait = current_queue * 15  # 降级估算

        # 大桌等待更久
        if party_size > 6:
            predicted_wait = round(predicted_wait * 1.5)
        elif party_size > 4:
            predicted_wait = round(predicted_wait * 1.2)

        is_acceptable = predicted_wait <= MAX_ACCEPTABLE_WAIT_MINUTES
        suggestion = "预计等待时间可接受" if is_acceptable else "建议引导顾客到附近门店或提供等位优惠"

        return AgentResult(
            success=True, action="predict_wait",
            data={
                "store_id": store_id,
                "predicted_wait_minutes": predicted_wait,
                "current_queue": current_queue,
                "is_acceptable": is_acceptable,
                "suggestion": suggestion,
                "party_size": party_size,
            },
            reasoning=f"门店 {store_id} 预计等位 {predicted_wait} 分钟，"
                      f"排队 {current_queue} 组，{'可接受' if is_acceptable else '超阈值'}",
            confidence=0.75 if current_queue > 0 else 0.9,
        )
