"""多轮对话上下文管理 — Redis-backed conversation context (BI-1.3)

支持：
- 会话上下文存储与恢复
- 代词消解（"那个"、"它"、"他"、"上次"）
- 追问收敛（同一 topic 内保持 measures/dimensions）
- TTL 自动过期（可配置，默认 30 分钟）
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class DialogueContext(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = ""
    store_id: Optional[str] = None
    brand_id: Optional[str] = None
    last_intent: Optional[str] = None
    last_filters: dict[str, Any] = Field(default_factory=dict)
    last_measures: list[str] = Field(default_factory=list)
    last_dimensions: list[str] = Field(default_factory=list)
    last_question: str = ""
    last_answer: str = ""
    turn_count: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str = ""

    def touch(self, ttl_seconds: int = 1800) -> None:
        """更新过期时间（默认 30 分钟）"""
        self.expires_at = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        now = datetime.now(timezone.utc)
        exp = datetime.fromisoformat(
            self.expires_at.replace("Z", "+00:00")
        )
        return now > exp


# ---------------------------------------------------------------------------
# Pronoun / reference resolution
# ---------------------------------------------------------------------------

_REFERENCE_PATTERNS: dict[str, str] = {
    "那个": "previous_topic",
    "它": "previous_topic",
    "他": "previous_topic",
    "她": "previous_topic",
    "这个": "previous_topic",
    "上次": "previous_results",
    "刚才": "previous_results",
    "前面": "previous_results",
    "同上": "repeat_query",
    "一样": "repeat_query",
    "也": "same_measure",
    "还": "same_dimension",
}


def resolve_reference(question: str, ctx: DialogueContext) -> tuple[str, bool]:
    """检测问题是否包含代词引用，返回 (expanded_question, is_reference).

    例如：
    - "那福田店呢"（上一个 query 是关于南山店的）→ store_id 替换为福田
    - "毛利率呢"（上一个 query 是营收）→ 追加 reference context
    """
    question_lower = question.lower().strip()

    for pronoun, ref_type in _REFERENCE_PATTERNS.items():
        if pronoun in question_lower:
            if ref_type == "previous_topic" and ctx.last_intent:
                return (
                    f"[上下文：上轮调查询 {ctx.last_intent}] {question}",
                    True,
                )
            if ref_type == "previous_results" and ctx.last_answer:
                return (
                    f"[上下文：上次回答 {ctx.last_answer[:200]}] {question}",
                    True,
                )
            if ref_type == "same_measure" and ctx.last_measures:
                return (
                    f"[上下文：上轮指标 {', '.join(ctx.last_measures)}] {question}",
                    True,
                )
            if ref_type == "same_dimension" and ctx.last_dimensions:
                return (
                    f"[上下文：上轮维度 {', '.join(ctx.last_dimensions)}] {question}",
                    True,
                )
            if ref_type == "repeat_query":
                return (ctx.last_question, True) if ctx.last_question else (question, False)

    return question, False


# ---------------------------------------------------------------------------
# Context Manager
# ---------------------------------------------------------------------------


class ContextManager:
    """多轮对话上下文管理器。

    使用方式：
    - 生产环境：传入 Redis URL，基于 Redis 存储
    - 开发环境：不传 Redis URL，基于 in-memory dict（进程重启丢失）
    """

    def __init__(self, redis_url: Optional[str] = None):
        self._redis_url = redis_url
        self._redis_client: Any = None
        # 开发模式：in-memory 存储
        self._store: dict[str, DialogueContext] = {}
        self._ttl_seconds = 1800  # 默认 30 分钟

    # ---- Redis client (lazy init) ----

    async def _ensure_redis(self) -> None:
        if self._redis_url and self._redis_client is None:
            try:
                import redis.asyncio as aioredis

                self._redis_client = aioredis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_connect_timeout=3,
                )
            except ImportError:
                # 开发模式降级到 in-memory
                pass

    def _redis_key(self, session_id: str) -> str:
        return f"nlq:ctx:{session_id}"

    # ---- public API ----

    async def get_context(self, session_id: str) -> DialogueContext:
        """获取或创建新上下文"""
        await self._ensure_redis()

        if self._redis_client:
            try:
                raw = await self._redis_client.get(self._redis_key(session_id))
                if raw:
                    ctx = DialogueContext(**json.loads(raw))
                    if not ctx.is_expired():
                        return ctx
                    await self._redis_client.delete(self._redis_key(session_id))
            except Exception:
                pass

        if session_id in self._store:
            ctx = self._store[session_id]
            if not ctx.is_expired():
                return ctx
            del self._store[session_id]

        return DialogueContext(session_id=session_id)

    async def save_context(self, ctx: DialogueContext) -> None:
        """持久化上下文"""
        await self._ensure_redis()
        ctx.touch(self._ttl_seconds)
        data = ctx.model_dump()

        if self._redis_client:
            try:
                await self._redis_client.setex(
                    self._redis_key(ctx.session_id),
                    self._ttl_seconds,
                    json.dumps(data, ensure_ascii=False),
                )
            except Exception:
                self._store[ctx.session_id] = ctx
        else:
            self._store[ctx.session_id] = ctx

    async def clear_context(self, session_id: str) -> None:
        """手动清除会话上下文（'清空上下文'/'从新开始'）"""
        await self._ensure_redis()
        if self._redis_client:
            try:
                await self._redis_client.delete(self._redis_key(session_id))
            except Exception:
                pass
        self._store.pop(session_id, None)

    def merge_context(
        self,
        ctx: DialogueContext,
        new_params: dict[str, Any],
        intent: str = "",
        measures: list[str] | None = None,
        dimensions: list[str] | None = None,
    ) -> DialogueContext:
        """将新查询的参数合并到现有上下文中。

        合并策略：
        - 同名参数覆盖（如 store_id 从南山变为福田）
        - 旧参数仅在新查询未指定时保留
        - measures/dimensions 全量替换
        """
        merged = ctx.model_copy(deep=True)
        merged.turn_count += 1
        merged.last_intent = intent or merged.last_intent

        # 合并 filters
        for key, value in new_params.items():
            if key in ("tenant_id", "session_id"):
                continue
            merged.last_filters[key] = value

        # 替换 measures / dimensions
        if measures is not None:
            merged.last_measures = measures
        if dimensions is not None:
            merged.last_dimensions = dimensions

        return merged


# ---------------------------------------------------------------------------
# Simple in-memory singleton for easy access
# ---------------------------------------------------------------------------

_default_manager: Optional[ContextManager] = None


def get_context_manager(redis_url: Optional[str] = None) -> ContextManager:
    """获取（或创建）默认 ContextManager 实例"""
    global _default_manager
    if _default_manager is None:
        _default_manager = ContextManager(redis_url=redis_url)
    return _default_manager
