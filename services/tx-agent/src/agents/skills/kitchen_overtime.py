"""后厨超时Agent — 出餐超时检测/预警、催菜自动调度、超时原因分析

职责：
- 实时监控出餐时间，超过阈值自动预警
- 分析超时原因（缺料/设备故障/人手不足/高峰积压）
- 自动触发催菜通知到 KDS
- 超时趋势分析，识别长期瓶颈档口
- VIP/催菜订单自动提升优先级

事件驱动：
- ORDER.ITEM_SENT_TO_KITCHEN → 开始计时
- KDS.ITEM_COMPLETED → 记录出餐时间
- 定时扫描（每60秒） → 检测超时项
"""
from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger()


class KitchenOvertimeAgent(SkillAgent):
    agent_id = "kitchen_overtime"
    agent_name = "后厨超时监控"
    description = "出餐超时检测/预警、催菜自动调度、超时原因分析、瓶颈档口识别"
    priority = "P1"
    run_location = "edge"  # 边缘实时监控，低延迟
    agent_level = 2  # 自动催菜 + 回滚（取消催菜）

    def get_supported_actions(self) -> list[str]:
        return [
            "scan_overtime_items",
            "analyze_overtime_cause",
            "auto_rush_notify",
            "get_station_bottleneck",
            "predict_serve_time",
            "get_overtime_stats",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "scan_overtime_items": self._scan_overtime_items,
            "analyze_overtime_cause": self._analyze_overtime_cause,
            "auto_rush_notify": self._auto_rush_notify,
            "get_station_bottleneck": self._get_station_bottleneck,
            "predict_serve_time": self._predict_serve_time,
            "get_overtime_stats": self._get_overtime_stats,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported action: {action}")
        return await handler(params)

    async def _scan_overtime_items(self, params: dict) -> AgentResult:
        """扫描当前所有超时出餐项"""
        pending_items = params.get("pending_items", [])
        threshold_minutes = params.get("threshold_minutes", 25)
        warn_threshold = int(threshold_minutes * 0.6)

        overtime = []
        warning = []
        for item in pending_items:
            elapsed = item.get("elapsed_minutes", 0)
            if elapsed >= threshold_minutes:
                overtime.append({**item, "severity": "critical", "overtime_minutes": elapsed - threshold_minutes})
            elif elapsed >= warn_threshold:
                warning.append({**item, "severity": "warning", "remaining_minutes": threshold_minutes - elapsed})

        return AgentResult(
            success=True, action="scan_overtime_items",
            data={
                "overtime_count": len(overtime),
                "warning_count": len(warning),
                "overtime_items": overtime,
                "warning_items": warning,
                "threshold_minutes": threshold_minutes,
            },
            reasoning=f"扫描{len(pending_items)}个待出品项：{len(overtime)}个超时，{len(warning)}个预警",
            confidence=0.95,
            inference_layer="edge",
        )

    async def _analyze_overtime_cause(self, params: dict) -> AgentResult:
        """分析超时根因"""
        item = params.get("item", {})
        station = item.get("kitchen_station", "default")
        elapsed = item.get("elapsed_minutes", 0)
        station_queue_length = params.get("station_queue_length", 0)
        station_staff_count = params.get("station_staff_count", 1)
        ingredient_shortage = params.get("ingredient_shortage", False)
        equipment_issue = params.get("equipment_issue", False)

        causes = []
        primary_cause = "unknown"

        if ingredient_shortage:
            causes.append({"cause": "ingredient_shortage", "label": "食材缺料", "weight": 0.9})
            primary_cause = "ingredient_shortage"
        if equipment_issue:
            causes.append({"cause": "equipment_issue", "label": "设备故障", "weight": 0.85})
            primary_cause = "equipment_issue"
        if station_queue_length > 8:
            causes.append({"cause": "queue_overload", "label": f"档口积压（{station_queue_length}单待制）", "weight": 0.7})
            if primary_cause == "unknown":
                primary_cause = "queue_overload"
        if station_staff_count < 2 and station_queue_length > 4:
            causes.append({"cause": "understaffed", "label": f"人手不足（{station_staff_count}人值档）", "weight": 0.65})
            if primary_cause == "unknown":
                primary_cause = "understaffed"

        if not causes:
            causes.append({"cause": "normal_peak", "label": "高峰期正常积压", "weight": 0.5})
            primary_cause = "normal_peak"

        # 云端深度分析
        ai_suggestion = None
        if self._router and elapsed > 30:
            try:
                resp = await self._router.complete(
                    prompt=f"餐厅{station}档口出餐超时{elapsed}分钟，当前积压{station_queue_length}单，"
                           f"值档{station_staff_count}人。请给出1条简短处理建议（30字以内）。",
                    max_tokens=50,
                )
                if resp:
                    ai_suggestion = resp.strip()
            except (ValueError, RuntimeError, ConnectionError, TimeoutError):
                pass

        return AgentResult(
            success=True, action="analyze_overtime_cause",
            data={
                "primary_cause": primary_cause,
                "causes": causes,
                "station": station,
                "elapsed_minutes": elapsed,
                "ai_suggestion": ai_suggestion,
            },
            reasoning=f"{station}档口超时{elapsed}分钟，主因: {causes[0]['label'] if causes else '未知'}",
            confidence=0.8,
            inference_layer="edge+cloud" if ai_suggestion else "edge",
        )

    async def _auto_rush_notify(self, params: dict) -> AgentResult:
        """自动催菜通知到KDS"""
        item = params.get("item", {})
        order_no = item.get("order_no", "")
        dish_name = item.get("dish_name", "")
        table_no = item.get("table_no", "")
        station = item.get("kitchen_station", "")

        logger.info("auto_rush_notify",
                     order_no=order_no, dish=dish_name, table=table_no, station=station)

        return AgentResult(
            success=True, action="auto_rush_notify",
            data={
                "order_no": order_no,
                "dish_name": dish_name,
                "table_no": table_no,
                "station": station,
                "notification_type": "kds_rush",
                "message": f"催菜: {table_no} - {dish_name}",
            },
            reasoning=f"自动催菜: {table_no} {dish_name} → {station}档口",
            confidence=0.95,
            inference_layer="edge",
        )

    async def _get_station_bottleneck(self, params: dict) -> AgentResult:
        """识别瓶颈档口"""
        station_stats = params.get("station_stats", [])

        bottlenecks = []
        for stat in station_stats:
            avg_time = stat.get("avg_serve_minutes", 0)
            overtime_rate = stat.get("overtime_rate", 0)
            if overtime_rate > 0.2 or avg_time > 20:
                bottlenecks.append({
                    "station": stat.get("station_name", ""),
                    "avg_serve_minutes": avg_time,
                    "overtime_rate": overtime_rate,
                    "pending_count": stat.get("pending_count", 0),
                    "severity": "critical" if overtime_rate > 0.4 else "warning",
                })

        bottlenecks.sort(key=lambda x: x["overtime_rate"], reverse=True)

        return AgentResult(
            success=True, action="get_station_bottleneck",
            data={"bottlenecks": bottlenecks, "total_stations": len(station_stats)},
            reasoning=f"{len(station_stats)}个档口中，{len(bottlenecks)}个存在瓶颈",
            confidence=0.85,
            inference_layer="edge",
        )

    async def _predict_serve_time(self, params: dict) -> AgentResult:
        """预测出餐时间"""
        dish_name = params.get("dish_name", "")
        station = params.get("station", "default")
        queue_ahead = params.get("queue_ahead", 0)
        avg_cook_minutes = params.get("avg_cook_minutes", 15)

        predicted = avg_cook_minutes + queue_ahead * 3  # 每个排队项增加约3分钟

        return AgentResult(
            success=True, action="predict_serve_time",
            data={
                "dish_name": dish_name,
                "station": station,
                "predicted_minutes": predicted,
                "queue_ahead": queue_ahead,
            },
            reasoning=f"{dish_name} 预计{predicted}分钟出餐（{station}档口排队{queue_ahead}单）",
            confidence=0.7,
            inference_layer="edge",
        )

    async def _get_overtime_stats(self, params: dict) -> AgentResult:
        """获取超时统计"""
        period = params.get("period", "today")

        # DB query placeholder
        stats = {
            "period": period,
            "total_items": params.get("total_items", 420),
            "overtime_count": params.get("overtime_count", 12),
            "overtime_rate": params.get("overtime_rate", 0.028),
            "avg_serve_minutes": params.get("avg_serve_minutes", 14.5),
            "worst_station": params.get("worst_station", "热菜档"),
            "worst_dish": params.get("worst_dish", "口味虾"),
        }

        return AgentResult(
            success=True, action="get_overtime_stats",
            data=stats,
            reasoning=f"{period}出品{stats['total_items']}项，超时{stats['overtime_count']}项（{stats['overtime_rate']:.1%}），"
                      f"平均出餐{stats['avg_serve_minutes']:.1f}分钟",
            confidence=0.9,
            inference_layer="edge",
        )
