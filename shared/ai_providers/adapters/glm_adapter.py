"""智谱 GLM Provider 适配器。

智谱 BigModel API 兼容 OpenAI 格式。
支持 GLM-4-Plus / GLM-4-Flash。

环境变量：
  ZHIPUAI_API_KEY    — 智谱 API 密钥
  ZHIPUAI_BASE_URL   — 自定义端点，默认 https://open.bigmodel.cn/api/paas/v4
"""
from __future__ import annotations

import time
from typing import Any, AsyncGenerator, Optional

import structlog

from ..types import LLMResponse, ModelInfo, ModelPricing, ProviderHealth, ProviderName
from ..registry import get_models_by_provider, get_model_info
from .base import BaseProviderAdapter

logger = structlog.get_logger()

_DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"


class GLMAdapter(BaseProviderAdapter):
    """智谱 GLM-4 系列模型适配器。

    支持模型：
      - glm-4-plus    ¥50/百万token (标准，Agent能力强)
      - glm-4-flash   ¥0.1/百万token (轻量，免费额度大)

    特点：
      - 兼容 OpenAI SDK 格式
      - Agent / function calling 支持良好
      - 中文学术和专业领域表现优秀
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_s: int = 30,
        max_retries: int = 3,
    ):
        import os
        resolved_key = api_key or os.environ.get("ZHIPUAI_API_KEY")
        resolved_url = base_url or os.environ.get("ZHIPUAI_BASE_URL", _DEFAULT_BASE_URL)
        super().__init__(resolved_key, resolved_url, timeout_s, max_retries)
        self._client: Any = None

    def _ensure_client(self) -> Any:
        """懒加载 OpenAI 兼容客户端。"""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise ImportError("GLM 适配器需要 openai SDK: pip install openai>=1.0") from exc
            if not self._api_key:
                raise ValueError("ZHIPUAI_API_KEY 未配置")
            self._client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._client

    @property
    def name(self) -> ProviderName:
        return ProviderName.GLM

    @property
    def available_models(self) -> list[ModelInfo]:
        return get_models_by_provider(ProviderName.GLM)

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
        """调用 GLM API，返回统一响应格式。"""
        client = self._ensure_client()
        request_id = self._generate_request_id()
        start = time.monotonic()

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
            "glm_complete_success",
            model=model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cost_rmb=round(cost_rmb, 6),
            duration_ms=duration_ms,
            request_id=request_id,
        )

        return LLMResponse(
            text=text,
            provider=ProviderName.GLM,
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
        """流式调用 GLM。"""
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
            logger.error("glm_stream_failed", model=model, error=str(exc), exc_info=True)
            return

    async def health_check(self) -> ProviderHealth:
        """检查 GLM API 连通性。"""
        start = time.monotonic()
        try:
            client = self._ensure_client()
            await client.chat.completions.create(
                model="glm-4-flash",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            return ProviderHealth(
                provider=ProviderName.GLM,
                is_available=True,
                latency_ms=self._elapsed_ms(start),
            )
        except (OSError, RuntimeError, ValueError) as exc:  # noqa: BLE001 — 健康检查兜底，含网络/配置错误
            return ProviderHealth(
                provider=ProviderName.GLM,
                is_available=False,
                latency_ms=self._elapsed_ms(start),
                last_error=str(exc),
            )

    def get_pricing(self, model: str) -> ModelPricing:
        return get_model_info(model).pricing
