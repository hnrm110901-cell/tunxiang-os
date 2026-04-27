"""#3 出餐调度 Agent — P1 | 边缘

来源：order(18方法) + schedule(12方法) + ops_flow(5子Agent)
能力：出餐时间预测、排班优化、客流分析、链式告警、订单异常检测

全部 7 个 action 已实现。
迁移自 tunxiang V2.x schedule/agent.py + ops_flow/agent.py
"""

import statistics
from typing import Any

from constraints.decorator import with_constraint_check

from ..base import AgentResult, SkillAgent
from ..context import ConstraintContext
from ..memory_bus import Finding, MemoryBus


class ServeDispatchAgent(SkillAgent):
    agent_id = "serve_dispatch"
    agent_name = "出餐调度"
    description = "出餐时间预测、排班优化、客流分析、链式告警、工作量平衡"
    priority = "P1"
    run_location = "edge"

    # Sprint D1 / PR H 批次 2：出餐调度核心即 estimated_serve_minutes
    constraint_scope = {"experience"}

    def get_supported_actions(self) -> list[str]:
        return [
            "predict_serve_time",
            "optimize_schedule",
            "analyze_traffic",
            "predict_staffing_needs",
            "detect_order_anomaly",
            "trigger_chain_alert",
            "balance_workload",
        ]

    # Sprint D1：硬阻断装饰器 — predict_serve_time 已填 estimated_serve_minutes，
    # 客户体验约束（30 分钟上限）在出餐预测超阈值时硬阻断决策
    @with_constraint_check(skill_name="serve_dispatch")
    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "predict_serve_time": self._predict_serve,
            "optimize_schedule": self._optimize_schedule,
            "analyze_traffic": self._analyze_traffic,
            "predict_staffing_needs": self._staffing_needs,
            "detect_order_anomaly": self._detect_anomaly,
            "trigger_chain_alert": self._chain_alert,
            "balance_workload": self._balance_workload,
        }
        return await dispatch[action](params)

    async def _predict_serve(self, params: dict) -> AgentResult:
        """出餐时间预测 — 边缘 Core ML"""
        dish_count = params.get("dish_count", 1)
        has_complex = params.get("has_complex_dish", False)
        current_queue = params.get("kitchen_queue_size", 0)

        base = 5 + dish_count * 2.5
        if has_complex:
            base += 8
        queue_delay = current_queue * 1.5
        estimated = round(base + queue_delay)

        return AgentResult(
            success=True,
            action="predict_serve_time",
            data={
                "estimated_serve_minutes": estimated,
                "dish_count": dish_count,
                "queue_delay_minutes": round(queue_delay),
                "has_complex_dish": has_complex,
            },
            reasoning=f"预计出餐 {estimated} 分钟（{dish_count}道菜，队列{current_queue}单）",
            confidence=0.85,
            inference_layer="edge",
            # Sprint D1 / PR H 批次 2：填结构化 context 让 experience 约束真实生效
            # （checker 会验证 estimated <= max_serve_minutes 否则决策被拦截）
            context=ConstraintContext(
                estimated_serve_minutes=float(estimated),
                constraint_scope={"experience"},
            ),
        )

    async def _optimize_schedule(self, params: dict) -> AgentResult:
        """排班优化 — 多目标（成本/满意度/服务质量）"""
        employees = params.get("employees", [])
        traffic_forecast = params.get("traffic_forecast", [])  # 24 小时客流预测
        budget_fen = params.get("budget_fen", 0)

        if not employees or not traffic_forecast:
            return AgentResult(success=False, action="optimize_schedule", error="需要员工列表和客流预测")

        # 简化：按客流高峰分配
        peak_hours = [i for i, t in enumerate(traffic_forecast) if t > statistics.mean(traffic_forecast) * 1.2]
        off_peak = [i for i in range(len(traffic_forecast)) if i not in peak_hours]

        schedule = []
        for i, emp in enumerate(employees):
            if i < len(employees) // 2:
                hours = peak_hours[:8] if peak_hours else list(range(10, 18))
            else:
                hours = (off_peak + peak_hours)[:8]
            schedule.append({"employee": emp.get("name", f"员工{i + 1}"), "hours": hours})

        cost_estimate = len(employees) * 15000  # 简化：150元/天/人

        return AgentResult(
            success=True,
            action="optimize_schedule",
            data={
                "schedule": schedule,
                "peak_hours": peak_hours,
                "staff_count": len(employees),
                "estimated_cost_fen": cost_estimate,
                "cost_within_budget": cost_estimate <= budget_fen if budget_fen else True,
            },
            reasoning=f"为 {len(employees)} 人排班，高峰 {len(peak_hours)} 小时",
            confidence=0.75,
        )

    async def _analyze_traffic(self, params: dict) -> AgentResult:
        """客流分析 — 识别峰谷"""
        hourly_data = params.get("hourly_customers", [])
        if len(hourly_data) < 12:
            return AgentResult(success=False, action="analyze_traffic", error="至少需要12小时数据")

        avg = statistics.mean(hourly_data)
        peak_threshold = avg * 1.3
        valley_threshold = avg * 0.7

        peaks = [{"hour": i, "customers": c} for i, c in enumerate(hourly_data) if c >= peak_threshold]
        valleys = [{"hour": i, "customers": c} for i, c in enumerate(hourly_data) if c <= valley_threshold]

        return AgentResult(
            success=True,
            action="analyze_traffic",
            data={
                "total_customers": sum(hourly_data),
                "avg_hourly": round(avg, 1),
                "peak_hours": peaks,
                "valley_hours": valleys,
                "peak_ratio": round(max(hourly_data) / avg, 2) if avg > 0 else 0,
            },
            reasoning=f"日均时客流 {avg:.0f}，{len(peaks)} 个高峰，{len(valleys)} 个低谷",
            confidence=0.8,
        )

    async def _staffing_needs(self, params: dict) -> AgentResult:
        """人力需求预测"""
        forecast_customers = params.get("forecast_customers", [])
        service_ratio = params.get("service_ratio", 15)  # 每人服务15客

        if not forecast_customers:
            return AgentResult(success=False, action="predict_staffing_needs", error="需要客流预测")

        needs = []
        for i, customers in enumerate(forecast_customers):
            staff = max(1, round(customers / service_ratio))
            needs.append({"period": i, "customers": customers, "staff_needed": staff})

        total_staff_hours = sum(n["staff_needed"] for n in needs)

        return AgentResult(
            success=True,
            action="predict_staffing_needs",
            data={
                "staffing_needs": needs,
                "total_staff_hours": total_staff_hours,
                "max_concurrent": max(n["staff_needed"] for n in needs),
                "service_ratio": service_ratio,
            },
            reasoning=f"总需 {total_staff_hours} 人时，峰值 {max(n['staff_needed'] for n in needs)} 人",
            confidence=0.8,
        )

    async def _detect_anomaly(self, params: dict) -> AgentResult:
        """订单异常检测"""
        order = params.get("order", {})
        anomalies = []

        # 超时检测
        elapsed = order.get("elapsed_minutes", 0)
        if elapsed > 30:
            anomalies.append({"type": "timeout", "detail": f"出餐超时 {elapsed} 分钟", "severity": "high"})
        elif elapsed > 20:
            anomalies.append({"type": "slow", "detail": f"出餐偏慢 {elapsed} 分钟", "severity": "medium"})

        # 退菜检测
        return_count = order.get("return_count", 0)
        if return_count >= 2:
            anomalies.append({"type": "multi_return", "detail": f"退菜 {return_count} 次", "severity": "high"})

        # 大额折扣
        discount_rate = order.get("discount_rate", 0)
        if discount_rate > 0.5:
            anomalies.append({"type": "high_discount", "detail": f"折扣率 {discount_rate:.0%}", "severity": "medium"})

        return AgentResult(
            success=True,
            action="detect_order_anomaly",
            data={"anomalies": anomalies, "is_anomaly": len(anomalies) > 0, "anomaly_count": len(anomalies)},
            reasoning=f"检测到 {len(anomalies)} 个异常" if anomalies else "无异常",
            confidence=0.85,
        )

    async def _chain_alert(self, params: dict) -> AgentResult:
        """链式告警 — 1个事件触发3层联动"""
        trigger_event = params.get("event", {})
        event_type = trigger_event.get("type", "unknown")

        # 3层联动
        chain = {
            "L1_trigger": {"type": event_type, "source": trigger_event.get("source", "")},
            "L2_related": [],
            "L3_actions": [],
        }

        if event_type == "kitchen_delay":
            chain["L2_related"] = [
                {"check": "库存是否充足", "agent": "inventory_alert"},
                {"check": "是否人手不足", "agent": "private_ops"},
            ]
            chain["L3_actions"] = ["催菜通知厨房", "通知服务员解释等待", "检查备料"]
        elif event_type == "complaint":
            chain["L2_related"] = [
                {"check": "菜品质量记录", "agent": "smart_menu"},
                {"check": "员工服务评分", "agent": "smart_service"},
            ]
            chain["L3_actions"] = ["通知店长处理", "记录投诉", "启动差评修复旅程"]

        # 发布到 Memory Bus
        bus = MemoryBus.get_instance()
        bus.publish(
            Finding(
                agent_id=self.agent_id,
                finding_type="chain_alert",
                data=chain,
                confidence=0.9,
                store_id=self.store_id,
            )
        )

        return AgentResult(
            success=True,
            action="trigger_chain_alert",
            data=chain,
            reasoning=f"链式告警：{event_type} → {len(chain['L2_related'])} 关联检查 → {len(chain['L3_actions'])} 行动",
            confidence=0.9,
        )

    async def _balance_workload(self, params: dict) -> AgentResult:
        """工作量平衡"""
        staff_loads = params.get("staff_loads", [])  # [{"name": "张三", "current_orders": 8}, ...]

        if not staff_loads:
            return AgentResult(success=False, action="balance_workload", error="需要员工负载数据")

        loads = [s.get("current_orders", 0) for s in staff_loads]
        avg_load = statistics.mean(loads)
        std = statistics.stdev(loads) if len(loads) >= 2 else 0
        balance_score = max(0, 100 - std / max(1, avg_load) * 100)

        overloaded = [s for s in staff_loads if s.get("current_orders", 0) > avg_load * 1.5]
        underloaded = [s for s in staff_loads if s.get("current_orders", 0) < avg_load * 0.5]

        suggestions = []
        for over in overloaded:
            for under in underloaded:
                suggestions.append(
                    {
                        "from": over["name"],
                        "to": under["name"],
                        "transfer_orders": round(over["current_orders"] - avg_load),
                    }
                )

        return AgentResult(
            success=True,
            action="balance_workload",
            data={
                "balance_score": round(balance_score, 1),
                "avg_load": round(avg_load, 1),
                "overloaded": [s["name"] for s in overloaded],
                "underloaded": [s["name"] for s in underloaded],
                "suggestions": suggestions,
            },
            reasoning=f"负载均衡度 {balance_score:.0f}%，{len(overloaded)} 人超载，{len(underloaded)} 人空闲",
            confidence=0.8,
        )
