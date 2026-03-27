"""语音会话管理 — 多轮对话 + 上下文

管理语音交互的会话状态，支持：
- 多轮对话上下文保持
- 槽位渐进填充
- 会话超时自动清理
- 同一门店多设备并发会话
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

# 会话默认超时（秒）
SESSION_TIMEOUT_SECONDS = 300  # 5 分钟无活动自动关闭
MAX_TURNS_PER_SESSION = 50


class VoiceSessionManager:
    """语音会话管理器

    内存存储（单机部署），生产环境可替换为 Redis。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}

    def create_session(
        self,
        employee_id: str,
        store_id: str,
        device_type: str = "pos",
    ) -> dict[str, Any]:
        """创建新的语音会话。

        Args:
            employee_id: 操作员工ID
            store_id: 门店ID
            device_type: 设备类型 (pos/kds/crew/tablet)

        Returns:
            {session_id, employee_id, store_id, device_type, created_at, status}
        """
        session_id = f"VS-{uuid.uuid4().hex[:12].upper()}"
        now = time.time()

        session = {
            "session_id": session_id,
            "employee_id": employee_id,
            "store_id": store_id,
            "device_type": device_type,
            "created_at": now,
            "updated_at": now,
            "status": "active",
            "turns": [],
            "context": {
                "current_table": None,
                "last_intent": None,
                "last_entities": {},
                "pending_slots": [],
                "accumulated_entities": {},
            },
        }

        self._sessions[session_id] = session

        logger.info(
            "voice_session_created",
            session_id=session_id,
            employee_id=employee_id,
            store_id=store_id,
        )

        return {
            "session_id": session_id,
            "employee_id": employee_id,
            "store_id": store_id,
            "device_type": device_type,
            "created_at": now,
            "status": "active",
        }

    def get_session(self, session_id: str) -> dict[str, Any]:
        """获取会话信息。

        Returns:
            会话完整状态，若不存在返回 {ok: False}
        """
        session = self._sessions.get(session_id)
        if session is None:
            return {"ok": False, "error": f"会话不存在: {session_id}"}

        # 检查超时
        if self._is_expired(session):
            session["status"] = "expired"
            return {"ok": False, "error": "会话已过期", "session_id": session_id}

        return {
            "ok": True,
            "session_id": session["session_id"],
            "employee_id": session["employee_id"],
            "store_id": session["store_id"],
            "device_type": session["device_type"],
            "status": session["status"],
            "turn_count": len(session["turns"]),
            "context": session["context"],
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
        }

    def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> dict[str, Any]:
        """添加一轮对话。

        Args:
            session_id: 会话ID
            role: "user" 或 "system"
            content: 对话内容文本

        Returns:
            {ok, turn_index, session_id}
        """
        session = self._sessions.get(session_id)
        if session is None:
            return {"ok": False, "error": f"会话不存在: {session_id}"}

        if self._is_expired(session):
            session["status"] = "expired"
            return {"ok": False, "error": "会话已过期"}

        if len(session["turns"]) >= MAX_TURNS_PER_SESSION:
            return {"ok": False, "error": "会话轮次已达上限"}

        now = time.time()
        turn = {
            "index": len(session["turns"]),
            "role": role,
            "content": content,
            "timestamp": now,
        }
        session["turns"].append(turn)
        session["updated_at"] = now

        return {
            "ok": True,
            "turn_index": turn["index"],
            "session_id": session_id,
        }

    def update_context(
        self,
        session_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """更新会话上下文。

        Args:
            session_id: 会话ID
            updates: 要更新的上下文字段

        Returns:
            {ok, context}
        """
        session = self._sessions.get(session_id)
        if session is None:
            return {"ok": False, "error": f"会话不存在: {session_id}"}

        ctx = session["context"]
        for key, value in updates.items():
            ctx[key] = value

        # 合并累积实体
        if "entities" in updates and isinstance(updates["entities"], dict):
            accumulated = ctx.get("accumulated_entities", {})
            accumulated.update(updates["entities"])
            ctx["accumulated_entities"] = accumulated

        session["updated_at"] = time.time()

        return {"ok": True, "context": ctx}

    def get_context(self, session_id: str) -> dict[str, Any]:
        """获取当前会话上下文。

        Returns:
            上下文字典，包含 current_table, last_intent, last_entities 等
        """
        session = self._sessions.get(session_id)
        if session is None:
            return {}

        if self._is_expired(session):
            return {}

        return dict(session["context"])

    def close_session(self, session_id: str) -> dict[str, Any]:
        """关闭会话。

        Returns:
            {ok, session_id, total_turns, duration_seconds}
        """
        session = self._sessions.get(session_id)
        if session is None:
            return {"ok": False, "error": f"会话不存在: {session_id}"}

        now = time.time()
        session["status"] = "closed"
        session["updated_at"] = now
        duration = now - session["created_at"]

        logger.info(
            "voice_session_closed",
            session_id=session_id,
            total_turns=len(session["turns"]),
            duration_s=round(duration, 1),
        )

        return {
            "ok": True,
            "session_id": session_id,
            "total_turns": len(session["turns"]),
            "duration_seconds": round(duration, 1),
        }

    def get_active_sessions(self, store_id: str) -> list[dict[str, Any]]:
        """获取门店所有活跃会话。

        Args:
            store_id: 门店ID

        Returns:
            活跃会话列表
        """
        active: list[dict[str, Any]] = []
        now = time.time()

        for session in self._sessions.values():
            if session["store_id"] != store_id:
                continue
            if session["status"] != "active":
                continue
            if self._is_expired(session):
                session["status"] = "expired"
                continue

            active.append({
                "session_id": session["session_id"],
                "employee_id": session["employee_id"],
                "device_type": session["device_type"],
                "turn_count": len(session["turns"]),
                "created_at": session["created_at"],
                "updated_at": session["updated_at"],
                "idle_seconds": round(now - session["updated_at"], 1),
            })

        return active

    def cleanup_expired(self) -> int:
        """清理所有过期会话。返回清理数量。"""
        expired_ids = [
            sid
            for sid, session in self._sessions.items()
            if self._is_expired(session) or session["status"] in ("closed", "expired")
        ]
        for sid in expired_ids:
            del self._sessions[sid]

        if expired_ids:
            logger.info("voice_sessions_cleaned", count=len(expired_ids))

        return len(expired_ids)

    def _is_expired(self, session: dict[str, Any]) -> bool:
        """判断会话是否超时。"""
        if session["status"] in ("closed", "expired"):
            return True
        return (time.time() - session["updated_at"]) > SESSION_TIMEOUT_SECONDS
