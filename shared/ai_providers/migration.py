"""旧 ModelRouter 迁移桥接层。

渐进式迁移路由器，让所有现有服务无感切换到多 Provider 架构。

使用方式（替换 ModelRouter 的 import）：
    # 旧：
    # from services.tx_agent.src.services.model_router import ModelRouter
    # 新：
    from shared.ai_providers.migration import MigrationRouter as ModelRouter

环境变量：
    MULTI_PROVIDER_ENABLED  — "true" 启用多 Provider 路由，默认 "false"
    ANTHROPIC_API_KEY       — Claude API 密钥（降级模式必须）
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, AsyncGenerator, Optional

import structlog

logger = structlog.get_logger()

# 尝试导入新架构组件（可能尚未就绪）
_NEW_ROUTER_AVAILABLE = False
_MultiProviderRouter = None

try:
    from shared.ai_providers.router import MultiProviderRouter as _MultiProviderRouter  # type: ignore[assignment]

    _NEW_ROUTER_AVAILABLE = True
except ImportError:
    logger.info("migration_router_new_arch_unavailable", reason="shared.ai_providers.router not found")


def _is_multi_provider_enabled() -> bool:
    """检查是否启用多 Provider 路由。"""
    return _NEW_ROUTER_AVAILABLE and os.environ.get("MULTI_PROVIDER_ENABLED", "false").lower() == "true"


class MigrationRouter:
    """渐进式迁移路由器。

    MULTI_PROVIDER_ENABLED=false (默认): 行为与旧 ModelRouter 完全一致
    MULTI_PROVIDER_ENABLED=true:        使用新的 MultiProviderRouter

    接口签名与旧 ModelRouter 100% 兼容：
    - complete() 返回 str（非 LLMResponse）
    - stream_complete() 返回 AsyncGenerator[str, None]
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        self._multi_provider_enabled = _is_multi_provider_enabled()

        if self._multi_provider_enabled and _MultiProviderRouter is not None:
            try:
                self._new_router = _MultiProviderRouter(**kwargs)
                logger.info("migration_router_using_multi_provider")
            except Exception as exc:
                logger.warning(
                    "migration_router_new_router_init_failed",
                    error=str(exc),
                    fallback="legacy",
                    exc_info=True,
                )
                self._multi_provider_enabled = False
                self._new_router = None
                self._init_legacy(api_key)
        else:
            self._new_router = None
            self._init_legacy(api_key)

    def _init_legacy(self, api_key: Optional[str] = None) -> None:
        """初始化旧版 Anthropic-only 路由。"""
        from anthropic import AsyncAnthropic

        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ValueError("ANTHROPIC_API_KEY 环境变量未设置")

        self._client = AsyncAnthropic(api_key=resolved_key)

        # 复刻旧 ModelRouter 的模型选择策略
        self._task_model_map: dict[str, str] = {
            "quick_classification": "claude-haiku-4-5-20251001",
            "standard_analysis": "claude-sonnet-4-6",
            "complex_reasoning": "claude-opus-4-6",
            "agent_decision": "claude-sonnet-4-6",
            "supplier_scoring": "claude-sonnet-4-6",
            "demand_forecast": "claude-sonnet-4-6",
            "cost_analysis": "claude-sonnet-4-6",
            "patrol_report": "claude-haiku-4-5-20251001",
            "dashboard_brief": "claude-sonnet-4-6",
            "default": "claude-sonnet-4-6",
        }
        self._downgrade_model = "claude-haiku-4-5-20251001"
        self._upgrade_model = "claude-opus-4-6"

        logger.info("migration_router_using_legacy")

    # ── 模型选择（旧逻辑复刻） ────────────────────────────────────────────

    def _select_model(self, task_type: str, urgency: str = "normal") -> str:
        if urgency == "fast":
            return self._downgrade_model
        if urgency == "quality":
            return self._upgrade_model
        if task_type not in self._task_model_map:
            logger.warning("migration_router_unknown_task_type", task_type=task_type, using_default="claude-sonnet-4-6")
        return self._task_model_map.get(task_type, self._task_model_map["default"])

    # ── complete — 与旧 ModelRouter 完全相同的签名 ────────────────────────

    async def complete(
        self,
        tenant_id: str,
        task_type: str,
        messages: list[dict[str, str]],
        system: Optional[str] = None,
        urgency: str = "normal",
        max_tokens: int = 1024,
        timeout_s: int = 30,
        request_id: Optional[str] = None,
        db: Any = None,
    ) -> str:
        """发起模型调用，返回纯文本字符串。

        签名与旧 ModelRouter.complete() 完全一致，保证向后兼容。

        Args:
            tenant_id:  租户 UUID
            task_type:  任务类型
            messages:   对话消息列表
            system:     系统 prompt
            urgency:    "fast" | "normal" | "quality"
            max_tokens: 最大输出 token 数
            timeout_s:  超时秒数
            request_id: 幂等请求 ID
            db:         AsyncSession（可选，记录成本）

        Returns:
            模型生成的文本字符串 (str)
        """
        req_id = request_id or str(uuid.uuid4())

        # ── 新架构路径 ──
        if self._multi_provider_enabled and self._new_router is not None:
            try:
                response = await self._new_router.complete(
                    tenant_id=tenant_id,
                    task_type=task_type,
                    messages=messages,
                    system=system,
                    urgency=urgency,
                    max_tokens=max_tokens,
                    timeout_s=timeout_s,
                    request_id=req_id,
                )
                # MultiProviderRouter 返回 LLMResponse，这里取 .text 保持 str 兼容
                if hasattr(response, "text"):
                    return response.text
                # 如果已经是 str，直接返回
                return str(response)
            except Exception as exc:
                logger.warning(
                    "migration_router_new_router_failed",
                    error=str(exc),
                    request_id=req_id,
                    fallback="legacy",
                    exc_info=True,
                )
                # 降级到旧逻辑
                return await self._legacy_complete(
                    tenant_id=tenant_id,
                    task_type=task_type,
                    messages=messages,
                    system=system,
                    urgency=urgency,
                    max_tokens=max_tokens,
                    timeout_s=timeout_s,
                    request_id=req_id,
                )

        # ── 旧架构路径 ──
        return await self._legacy_complete(
            tenant_id=tenant_id,
            task_type=task_type,
            messages=messages,
            system=system,
            urgency=urgency,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            request_id=req_id,
        )

    async def _legacy_complete(
        self,
        tenant_id: str,
        task_type: str,
        messages: list[dict[str, str]],
        system: Optional[str] = None,
        urgency: str = "normal",
        max_tokens: int = 1024,
        timeout_s: int = 30,
        request_id: Optional[str] = None,
    ) -> str:
        """旧版 Anthropic-only 调用逻辑（含重试）。"""
        model = self._select_model(task_type, urgency)
        req_id = request_id or str(uuid.uuid4())
        max_retries = 3
        retry_delays = [1, 2, 4]

        logger.info(
            "migration_router_legacy_call",
            tenant_id=tenant_id,
            task_type=task_type,
            model=model,
            request_id=req_id,
        )

        last_exc: Optional[Exception] = None

        for attempt in range(max_retries):
            if attempt > 0:
                await asyncio.sleep(retry_delays[attempt - 1])

            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": messages,
                }
                if system:
                    kwargs["system"] = system

                response = await asyncio.wait_for(
                    self._client.messages.create(**kwargs),
                    timeout=timeout_s,
                )
                if response.content:
                    return response.content[0].text
                return ""  # Anthropic 返回空内容

            except Exception as exc:  # noqa: BLE001 — outermost retry loop; re-raised after exhaustion
                last_exc = exc
                logger.warning(
                    "migration_router_legacy_retry",
                    attempt=attempt + 1,
                    error=type(exc).__name__,
                    request_id=req_id,
                    exc_info=True,
                )

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("MigrationRouter: all retries exhausted")

    # ── stream_complete — 与旧 ModelRouter 完全相同的签名 ────────────────

    async def stream_complete(
        self,
        tenant_id: str,
        task_type: str,
        messages: list[dict[str, str]],
        system: Optional[str] = None,
        urgency: str = "normal",
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        """流式调用，逐 chunk 返回文本。

        签名与旧 ModelRouter.stream_complete() 完全一致。

        Yields:
            模型生成的文本片段 (str)
        """
        # ── 新架构路径 ──
        if self._multi_provider_enabled and self._new_router is not None:
            try:
                async for chunk in self._new_router.stream_complete(
                    tenant_id=tenant_id,
                    task_type=task_type,
                    messages=messages,
                    system=system,
                    urgency=urgency,
                    max_tokens=max_tokens,
                ):
                    # 确保 yield str
                    yield str(chunk) if not isinstance(chunk, str) else chunk
                return
            except Exception as exc:
                logger.warning(
                    "migration_router_stream_new_failed",
                    error=str(exc),
                    fallback="legacy",
                    exc_info=True,
                )
                # 降级到旧逻辑（下面继续执行）

        # ── 旧架构路径 ──
        model = self._select_model(task_type, urgency)

        logger.info(
            "migration_router_legacy_stream",
            tenant_id=tenant_id,
            task_type=task_type,
            model=model,
        )

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as exc:
            logger.error(
                "migration_router_legacy_stream_failed",
                error=type(exc).__name__,
                tenant_id=tenant_id,
                exc_info=True,
            )
            return
