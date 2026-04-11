"""排位Agent — 智能排队叫号、台型匹配、等位时间预测、VIP优先

职责：
- 根据候位人数和桌台周转，预测等位时间
- 根据就餐人数匹配最优台型（避免大桌坐小客）
- VIP/会员自动优先排队
- 结合预定信息避免冲突
- 高峰期主动建议分流（引导到相邻门店/外卖）

事件驱动：
- TABLE.STATUS_CHANGED → 有桌空出时自动叫号
- QUEUE.TICKET_CREATED → 新排队时预测等位时间
- RESERVATION.NO_SHOW → 爽约后释放预留桌位
"""
from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger()


class QueueSeatingAgent(SkillAgent):
    agent_id = "queue_seating"
    agent_name = "排位智能"
    description = "智能排队叫号、台型匹配、等位时间预测、VIP优先排队"
    priority = "P1"
    run_location = "edge+cloud"
    agent_level = 2  # 自动叫号 + 30分钟回滚（跳号可恢复）

    def get_supported_actions(self) -> list[str]:
        return [
            "predict_wait_time",
            "suggest_seating",
            "auto_call_next",
            "match_table_type",
            "handle_no_show_release",
            "peak_diversion_suggest",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "predict_wait_time": self._predict_wait_time,
            "suggest_seating": self._suggest_seating,
            "auto_call_next": self._auto_call_next,
            "match_table_type": self._match_table_type,
            "handle_no_show_release": self._handle_no_show_release,
            "peak_diversion_suggest": self._peak_diversion_suggest,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported action: {action}")
        return await handler(params)

    async def _predict_wait_time(self, params: dict) -> AgentResult:
        """根据当前排队人数、桌台周转速度、预定到店率预测等位时间"""
        party_size = params.get("party_size", 4)
        queue_position = params.get("queue_position", 1)

        # 边缘推理：基于历史平均翻台时间
        avg_turn_minutes = params.get("avg_turn_minutes", 45)
        table_count = params.get("available_table_count", 0)
        tables_for_size = params.get("matching_table_count", 3)

        if table_count > 0:
            estimated_minutes = 0
        elif tables_for_size > 0:
            estimated_minutes = int(avg_turn_minutes * (queue_position / tables_for_size))
        else:
            estimated_minutes = avg_turn_minutes * queue_position

        # 高峰修正：12:00-13:00 和 18:00-19:30 翻台更慢
        import datetime
        now = datetime.datetime.now()
        if (12 <= now.hour < 13) or (18 <= now.hour < 20):
            estimated_minutes = int(estimated_minutes * 1.2)

        return AgentResult(
            success=True,
            action="predict_wait_time",
            data={
                "estimated_minutes": estimated_minutes,
                "party_size": party_size,
                "queue_position": queue_position,
                "matching_tables": tables_for_size,
            },
            reasoning=f"队列第{queue_position}位，{party_size}人桌可用{tables_for_size}张，"
                      f"平均翻台{avg_turn_minutes}分钟，预计等位{estimated_minutes}分钟",
            confidence=0.75,
            inference_layer="edge",
        )

    async def _suggest_seating(self, params: dict) -> AgentResult:
        """为候位客人推荐最优桌位"""
        party_size = params.get("party_size", 4)
        is_vip = params.get("is_vip", False)
        preference = params.get("preference", "")  # "private_room", "window", etc.
        available_tables = params.get("available_tables", [])

        if not available_tables:
            return AgentResult(
                success=True, action="suggest_seating",
                data={"suggestion": None, "reason": "no_available_tables"},
                reasoning="当前无可用桌位",
                confidence=1.0, inference_layer="edge",
            )

        # 评分逻辑：容量匹配度 + VIP偏好 + 翻台目标
        scored = []
        for table in available_tables:
            capacity = table.get("seat_capacity", 4)
            score = 100.0

            # 容量匹配：尽量避免大桌坐小客（浪费），也避免挤
            if capacity < party_size:
                score -= 50  # 不够坐，大幅扣分
            elif capacity == party_size:
                score += 20  # 完美匹配
            elif capacity - party_size <= 2:
                score += 10  # 略有余量
            else:
                score -= (capacity - party_size) * 5  # 大桌浪费

            # VIP 偏好包间
            if is_vip and table.get("is_private_room"):
                score += 30
            if preference == "private_room" and table.get("is_private_room"):
                score += 25
            if preference == "window" and table.get("is_window", False):
                score += 15

            scored.append({"table": table, "score": score})

        scored.sort(key=lambda x: x["score"], reverse=True)
        best = scored[0]

        return AgentResult(
            success=True, action="suggest_seating",
            data={
                "recommended_table": best["table"],
                "score": best["score"],
                "alternatives": [s["table"] for s in scored[1:3]],
            },
            reasoning=f"推荐桌位 {best['table'].get('code', '?')}，"
                      f"容量{best['table'].get('seat_capacity', '?')}人，"
                      f"匹配度评分{best['score']:.0f}",
            confidence=0.85,
            inference_layer="edge",
        )

    async def _auto_call_next(self, params: dict) -> AgentResult:
        """桌台空出时自动叫号下一位"""
        freed_table = params.get("freed_table", {})
        queue = params.get("queue", [])

        if not queue:
            return AgentResult(
                success=True, action="auto_call_next",
                data={"called": None, "reason": "queue_empty"},
                reasoning="排队队列为空，无需叫号", confidence=1.0, inference_layer="edge",
            )

        table_capacity = freed_table.get("seat_capacity", 4)

        # 找队列中最匹配的客人（容量匹配 + VIP优先）
        candidates = []
        for ticket in queue:
            ps = ticket.get("party_size", 4)
            if ps <= table_capacity:
                priority = 0
                if ticket.get("is_vip"):
                    priority += 100
                if ticket.get("is_member"):
                    priority += 50
                # 容量匹配奖励
                priority += max(0, 20 - (table_capacity - ps) * 5)
                candidates.append({"ticket": ticket, "priority": priority})

        if not candidates:
            return AgentResult(
                success=True, action="auto_call_next",
                data={"called": None, "reason": "no_matching_party"},
                reasoning=f"桌位容量{table_capacity}人，队列中无匹配客人",
                confidence=0.9, inference_layer="edge",
            )

        candidates.sort(key=lambda x: x["priority"], reverse=True)
        called = candidates[0]["ticket"]

        logger.info("queue_auto_call", table=freed_table.get("code"), ticket=called.get("ticket_no"),
                     party_size=called.get("party_size"), is_vip=called.get("is_vip"))

        return AgentResult(
            success=True, action="auto_call_next",
            data={
                "called_ticket": called,
                "assigned_table": freed_table,
            },
            reasoning=f"叫号 {called.get('ticket_no', '?')}（{called.get('party_size', '?')}人）→ "
                      f"桌位 {freed_table.get('code', '?')}",
            confidence=0.9,
            inference_layer="edge",
        )

    async def _match_table_type(self, params: dict) -> AgentResult:
        """根据人数推荐台型"""
        party_size = params.get("party_size", 4)

        if party_size <= 2:
            table_type = "small"
            label = "小桌（2人）"
        elif party_size <= 4:
            table_type = "medium"
            label = "中桌（4人）"
        elif party_size <= 8:
            table_type = "large"
            label = "大桌（8人）"
        elif party_size <= 12:
            table_type = "private_room"
            label = "包间（12人）"
        else:
            table_type = "vip"
            label = "VIP大包/宴会厅"

        return AgentResult(
            success=True, action="match_table_type",
            data={"party_size": party_size, "recommended_type": table_type, "label": label},
            reasoning=f"{party_size}人就餐，推荐{label}",
            confidence=0.95, inference_layer="edge",
        )

    async def _handle_no_show_release(self, params: dict) -> AgentResult:
        """预定爽约后释放预留桌位，通知排队队列"""
        reservation_id = params.get("reservation_id", "")
        table_code = params.get("table_code", "")

        return AgentResult(
            success=True, action="handle_no_show_release",
            data={
                "reservation_id": reservation_id,
                "released_table": table_code,
                "action": "release_to_queue",
            },
            reasoning=f"预定 {reservation_id} 爽约，释放桌位 {table_code} 给排队队列",
            confidence=1.0, inference_layer="edge",
        )

    async def _peak_diversion_suggest(self, params: dict) -> AgentResult:
        """高峰期分流建议"""
        current_wait_minutes = params.get("current_wait_minutes", 30)
        queue_length = params.get("queue_length", 10)
        nearby_stores = params.get("nearby_stores", [])

        suggestions = []
        if current_wait_minutes > 45:
            suggestions.append("建议推荐外卖自提，减少堂食等位压力")
        if nearby_stores:
            for store in nearby_stores[:2]:
                if store.get("estimated_wait", 60) < current_wait_minutes:
                    suggestions.append(f"可引导至 {store.get('name', '?')}（预计等位{store.get('estimated_wait', '?')}分钟）")

        if not suggestions:
            suggestions.append("当前等位时间在可接受范围内，暂无分流建议")

        # 云端深度分析（如果可用）
        if self._router and current_wait_minutes > 60:
            try:
                resp = await self._router.complete(
                    prompt=f"门店当前排队{queue_length}桌，预计等位{current_wait_minutes}分钟。请给出3条分流建议。",
                    max_tokens=200,
                )
                if resp:
                    suggestions.append(f"AI建议: {resp}")
            except (ValueError, RuntimeError, ConnectionError, TimeoutError):
                pass

        return AgentResult(
            success=True, action="peak_diversion_suggest",
            data={
                "current_wait_minutes": current_wait_minutes,
                "queue_length": queue_length,
                "suggestions": suggestions,
            },
            reasoning=f"当前排队{queue_length}桌，预计等位{current_wait_minutes}分钟",
            confidence=0.7,
            inference_layer="edge+cloud" if self._router else "edge",
        )
