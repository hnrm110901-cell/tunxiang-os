"""月之暗面 Kimi Provider 适配器。

Kimi API 兼容 OpenAI 格式，使用 openai SDK 调用。
支持 moonshot-v1-128k (长上下文) 和 moonshot-v1-32k (标准)。

环境变量：
  MOONSHOT_API_KEY   — Kimi API 密钥
  MOONSHOT_BASE_URL  — 自定义端点，默认 https://api.moonshot.cn/v1
"""
from __future__ import annotations

import time
from typing import Any, AsyncGenerator, Optional

import structlog

from ..types import (
    LLMResponse,
    ModelInfo,
    ModelPricing,
    ProviderHealth,
    ProviderName,
)
from ..registry import get_models_by_provider, get_model_info
from .base import BaseProviderAdapter

logger = structlog.get_logger()

# Kimi 默认 API 端点
_DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"


class KimiAdapter(BaseProviderAdapter):
    """月之暗面 Kimi API 适配器（兼容 OpenAI SDK 格式）。

    支持模型：
      - moonshot-v1-128k  (长上下文)  — ¥60/百万输入 + ¥60/百万输出
      - moonshot-v1-32k   (标准)      — ¥24/百万输入 + ¥24/百万输出

    特点：
      - 与 OpenAI SDK 兼容，仅需更换 base_url
      - 境内部署，数据不出境
      - 128K 长上下文能力突出，适合文档分析/合同审查
      - 支持 function calling
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_s: int = 30,
        max_retries: int = 3,
    ):
        import os
        resolved_key = api_key or os.environ.get("MOONSHOT_API_KEY")
        resolved_url = base_url or os.environ.get("MOONSHOT_BASE_URL", _DEFAULT_BASE_URL)
        super().__init__(resolved_key, resolved_url, timeout_s, max_retries)

        self._client: Any = None  # 懒加载 openai.AsyncOpenAI

    def _ensure_client(self) -> Any:
        """懒加载 OpenAI 兼容客户端。"""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise ImportError(
                    "Kimi 适配器需要 openai SDK。请安装: pip install openai>=1.0"
                ) from exc
            if not self._api_key:
                raise ValueError("MOONSHOT_API_KEY 未配置")
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
            )
        return self._client

    @property
    def name(self) -> ProviderName:
        return ProviderName.KIMI

    @property
    def available_models(self) -> list[ModelInfo]:
        return get_models_by_provider(ProviderName.KIMI)

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
        """调用 Kimi API，返回统一响应格式。"""
        client = self._ensure_client()
        request_id = self._generate_request_id()
        start = time.monotonic()

        # 构建消息列表（OpenAI 格式，system 作为第一条消息）
        api_messages = []
        if system:
            api_messages.append({"role": "system", "content": system})
        api_messages.extend(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools

        async def _do_call():
            return await client.chat.completions.create(**kwargs)

        from openai import APIConnectionError, APITimeoutError, APIStatusError
        response = await self._retry_with_backoff(
            _do_call,
            retryable_exceptions=(APIConnectionError, APITimeoutError, APIStatusError),
        )

        duration_ms = self._elapsed_ms(start)
        usage = response.usage
        model_info = get_model_info(model)
        cost_rmb = (
            usage.prompt_tokens / 1_000_000 * model_info.pricing.input_rmb_per_million
            + usage.completion_tokens / 1_000_000 * model_info.pricing.output_rmb_per_million
        )

        text = response.choices[0].message.content or ""
        finish_reason = response.choices[0].finish_reason or "stop"

        logger.info(
            "kimi_complete_success",
            model=model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cost_rmb=round(cost_rmb, 6),
            duration_ms=duration_ms,
            request_id=request_id,
        )

        return LLMResponse(
            text=text,
            provider=ProviderName.KIMI,
            model_id=model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
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
        """流式调用 Kimi。"""
        client = self._ensure_client()

        api_messages = []
        if system:
            api_messages.append({"role": "system", "content": system})
        api_messages.extend(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            response = await client.chat.completions.create(**kwargs)
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except (OSError, RuntimeError) as exc:  # noqa: BLE001 — stream 最外层兜底，含网络/运行时错误
            logger.error("kimi_stream_failed", model=model, error=str(exc), exc_info=True)
            return

    async def health_check(self) -> ProviderHealth:
        """检查 Kimi API 连通性（使用 moonshot-v1-32k）。"""
        start = time.monotonic()
        try:
            client = self._ensure_client()
            response = await client.chat.completions.create(
                model="moonshot-v1-32k",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            return ProviderHealth(
                provider=ProviderName.KIMI,
                is_available=True,
                latency_ms=self._elapsed_ms(start),
            )
        except (OSError, RuntimeError, ValueError) as exc:  # noqa: BLE001 — 健康检查兜底，含网络/配置错误
            return ProviderHealth(
                provider=ProviderName.KIMI,
                is_available=False,
                latency_ms=self._elapsed_ms(start),
                last_error=str(exc),
            )

    def get_pricing(self, model: str) -> ModelPricing:
        return get_model_info(model).pricing
