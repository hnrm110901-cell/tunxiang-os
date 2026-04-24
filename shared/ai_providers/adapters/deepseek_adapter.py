"""DeepSeek Provider 适配器。

DeepSeek API 完全兼容 OpenAI 格式，使用 openai SDK 调用。
支持 DeepSeek-V3 (deepseek-chat) 和 DeepSeek-R1 (deepseek-reasoner)。

环境变量：
  DEEPSEEK_API_KEY   — DeepSeek API 密钥
  DEEPSEEK_BASE_URL  — 自定义端点，默认 https://api.deepseek.com
"""

from __future__ import annotations

import time
from typing import Any, AsyncGenerator, Optional

import structlog

from ..registry import get_model_info, get_models_by_provider
from ..types import (
    LLMResponse,
    ModelInfo,
    ModelPricing,
    ProviderHealth,
    ProviderName,
)
from .base import BaseProviderAdapter

logger = structlog.get_logger()

# DeepSeek 默认 API 端点
_DEFAULT_BASE_URL = "https://api.deepseek.com"


class DeepSeekAdapter(BaseProviderAdapter):
    """DeepSeek API 适配器（兼容 OpenAI SDK 格式）。

    支持模型：
      - deepseek-chat     (DeepSeek-V3)  — ¥1/百万输入 + ¥2/百万输出
      - deepseek-reasoner (DeepSeek-R1)  — ¥4/百万输入 + ¥16/百万输出

    特点：
      - 与 OpenAI SDK 100% 兼容，仅需更换 base_url
      - 境内部署，数据不出境
      - V3 性价比极高（比 Claude Sonnet 便宜 20 倍）
      - R1 推理链质量接近 Claude Opus，价格仅 1/7
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_s: int = 30,
        max_retries: int = 3,
    ):
        import os

        resolved_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        resolved_url = base_url or os.environ.get("DEEPSEEK_BASE_URL", _DEFAULT_BASE_URL)
        super().__init__(resolved_key, resolved_url, timeout_s, max_retries)

        self._client: Any = None  # 懒加载 openai.AsyncOpenAI

    def _ensure_client(self) -> Any:
        """懒加载 OpenAI 兼容客户端。"""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise ImportError("DeepSeek 适配器需要 openai SDK。请安装: pip install openai>=1.0") from exc
            if not self._api_key:
                raise ValueError("DEEPSEEK_API_KEY 未配置")
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
            )
        return self._client

    @property
    def name(self) -> ProviderName:
        return ProviderName.DEEPSEEK

    @property
    def available_models(self) -> list[ModelInfo]:
        return get_models_by_provider(ProviderName.DEEPSEEK)

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
        """调用 DeepSeek API，返回统一响应格式。"""
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
        if tools and model != "deepseek-reasoner":
            # R1 不支持 function calling
            kwargs["tools"] = tools

        async def _do_call():
            return await client.chat.completions.create(**kwargs)

        from openai import APIConnectionError, APIStatusError, APITimeoutError

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
            "deepseek_complete_success",
            model=model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cost_rmb=round(cost_rmb, 6),
            duration_ms=duration_ms,
            request_id=request_id,
        )

        return LLMResponse(
            text=text,
            provider=ProviderName.DEEPSEEK,
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
        """流式调用 DeepSeek。"""
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
        if tools and model != "deepseek-reasoner":
            kwargs["tools"] = tools

        try:
            response = await client.chat.completions.create(**kwargs)
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except (OSError, RuntimeError) as exc:  # noqa: BLE001 — stream 最外层兜底，含网络/运行时错误
            logger.error("deepseek_stream_failed", model=model, error=str(exc), exc_info=True)
            return

    async def health_check(self) -> ProviderHealth:
        """检查 DeepSeek API 连通性。"""
        start = time.monotonic()
        try:
            client = self._ensure_client()
            response = await client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            return ProviderHealth(
                provider=ProviderName.DEEPSEEK,
                is_available=True,
                latency_ms=self._elapsed_ms(start),
            )
        except (OSError, RuntimeError, ValueError) as exc:  # noqa: BLE001 — 健康检查兜底，含网络/配置错误
            return ProviderHealth(
                provider=ProviderName.DEEPSEEK,
                is_available=False,
                latency_ms=self._elapsed_ms(start),
                last_error=str(exc),
            )

    def get_pricing(self, model: str) -> ModelPricing:
        return get_model_info(model).pricing
