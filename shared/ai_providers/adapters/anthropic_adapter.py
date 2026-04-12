"""Anthropic Claude Provider 适配器。

封装现有 Anthropic SDK 调用为统一 ProviderAdapter 接口。
这是原有 ModelRouter 中 Claude 调用逻辑的适配器化。

环境变量：
  ANTHROPIC_API_KEY   — Claude API 密钥
"""
from __future__ import annotations

import time
from typing import Any, AsyncGenerator, Optional

import structlog

from ..types import LLMResponse, ModelInfo, ModelPricing, ProviderHealth, ProviderName
from ..registry import get_models_by_provider, get_model_info
from .base import BaseProviderAdapter

logger = structlog.get_logger()


class AnthropicAdapter(BaseProviderAdapter):
    """Anthropic Claude 适配器。

    支持模型：
      - claude-haiku-4-5-20251001   (Lite)
      - claude-sonnet-4-6           (Standard)
      - claude-opus-4-6             (Premium)

    注意：
      - Anthropic SDK 使用自有消息格式（非 OpenAI 兼容）
      - system prompt 作为独立参数而非消息
      - 境外 Provider，敏感数据需脱敏后使用
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_s: int = 30,
        max_retries: int = 3,
    ):
        import os
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        super().__init__(resolved_key, base_url, timeout_s, max_retries)
        self._client: Any = None

    def _ensure_client(self) -> Any:
        """懒加载 Anthropic 客户端。"""
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as exc:
                raise ImportError("Anthropic 适配器需要 anthropic SDK: pip install anthropic") from exc
            if not self._api_key:
                raise ValueError("ANTHROPIC_API_KEY 未配置")
            self._client = AsyncAnthropic(api_key=self._api_key)
        return self._client

    @property
    def name(self) -> ProviderName:
        return ProviderName.ANTHROPIC

    @property
    def available_models(self) -> list[ModelInfo]:
        return get_models_by_provider(ProviderName.ANTHROPIC)

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout_s: int = 30,
        tools: Optional[list[dict]] = None,
    ) -> LLMResponse:
        """调用 Anthropic Messages API，返回统一响应格式。"""
        client = self._ensure_client()
        request_id = self._generate_request_id()
        start = time.monotonic()

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        async def _do_call():
            return await client.messages.create(**kwargs)

        from anthropic import APIConnectionError, APITimeoutError, APIStatusError
        response = await self._retry_with_backoff(
            _do_call,
            retryable_exceptions=(APIConnectionError, APITimeoutError, APIStatusError),
        )

        duration_ms = self._elapsed_ms(start)
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        model_info = get_model_info(model)

        # Claude 定价原始是 USD，registry 中已转为 RMB（汇率 7.0）
        cost_rmb = (
            input_tokens / 1_000_000 * model_info.pricing.input_rmb_per_million
            + output_tokens / 1_000_000 * model_info.pricing.output_rmb_per_million
        )

        text = response.content[0].text if response.content else ""
        finish_reason = response.stop_reason or "stop"

        logger.info(
            "anthropic_complete_success",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_rmb=round(cost_rmb, 6),
            duration_ms=duration_ms,
            request_id=request_id,
        )

        return LLMResponse(
            text=text,
            provider=ProviderName.ANTHROPIC,
            model_id=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_rmb=round(cost_rmb, 6),
            duration_ms=duration_ms,
            request_id=request_id,
            raw_response=response,
            finish_reason=finish_reason,
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        tools: Optional[list[dict]] = None,
    ) -> AsyncGenerator[str, None]:
        """流式调用 Anthropic Messages API。"""
        client = self._ensure_client()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        try:
            async with client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text
        except (OSError, RuntimeError) as exc:  # noqa: BLE001 — stream 最外层兜底
            logger.error("anthropic_stream_failed", model=model, error=str(exc), exc_info=True)
            return

    async def health_check(self) -> ProviderHealth:
        """检查 Anthropic API 连通性。"""
        start = time.monotonic()
        try:
            client = self._ensure_client()
            await client.messages.create(
                model="claude-haiku-4-5-20251001",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            return ProviderHealth(
                provider=ProviderName.ANTHROPIC,
                is_available=True,
                latency_ms=self._elapsed_ms(start),
            )
        except (OSError, RuntimeError, ValueError) as exc:  # noqa: BLE001 — 健康检查兜底，含网络/配置错误
            return ProviderHealth(
                provider=ProviderName.ANTHROPIC,
                is_available=False,
                latency_ms=self._elapsed_ms(start),
                last_error=str(exc),
            )

    def get_pricing(self, model: str) -> ModelPricing:
        return get_model_info(model).pricing
