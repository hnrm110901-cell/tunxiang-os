"""
HR 助手多轮对话上下文管理（走 agent_memory_bus + 内存 fallback）

- 每个 conversation_id 维护最近 10 轮 (role/content/tool_calls/ts)
- 写入记忆总线用于跨 Agent 共享（仅 summary）
- DB 落库由 api 层调用 HRMessage model 完成
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

import structlog

logger = structlog.get_logger()

_MAX_TURNS = 10
_memory_store: Dict[str, Deque[Dict[str, Any]]] = defaultdict(lambda: deque(maxlen=_MAX_TURNS))


class ConversationContext:
    """轻量会话上下文"""

    def __init__(self, conversation_id: str, employee_id: str):
        self.conversation_id = conversation_id
        self.employee_id = employee_id
        self.turns: Deque[Dict[str, Any]] = _memory_store[conversation_id]

    def append(self, role: str, content: str, tool_calls: Optional[List[Dict[str, Any]]] = None) -> None:
        self.turns.append(
            {
                "role": role,
                "content": content,
                "tool_calls": tool_calls or [],
                "ts": datetime.utcnow().isoformat(),
            }
        )

    def recent_turns(self, n: int = 5) -> List[Dict[str, Any]]:
        return list(self.turns)[-n:]

    def as_llm_messages(self) -> List[Dict[str, str]]:
        """导出为 LLM 消息格式"""
        return [{"role": t["role"], "content": t["content"]} for t in self.turns]

    def to_json(self) -> str:
        return json.dumps(list(self.turns), ensure_ascii=False)


async def publish_to_memory_bus(employee_id: str, summary: str) -> None:
    """异步推送摘要到 agent_memory_bus（best-effort）"""
    try:
        from ..agent_memory_bus import agent_memory_bus

        await agent_memory_bus.publish(
            store_id=f"employee:{employee_id}",
            agent_id="hr_assistant",
            action="hr_query",
            summary=summary[:120],
            confidence=0.8,
            data={},
        )
    except Exception as exc:
        logger.debug("hr_ctx.bus_publish_skip", error=str(exc))
