"""
DeepSeek Provider — 使用 OpenAI 兼容 SDK，指向 https://api.deepseek.com
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import structlog

from .base import LLMProvider, LLMProviderError

logger = structlog.get_logger()


class DeepSeekProvider(LLMProvider):
    """DeepSeek 提供商（OpenAI 兼容接口）"""

    name = "deepseek"
    default_model = "deepseek-chat"

    def __init__(self, api_key: str, model: Optional[str] = None, base_url: Optional[str] = None):
        super().__init__(api_key=api_key, model=model, base_url=base_url or "https://api.deepseek.com")

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        timeout: float = 5.0,
        **kwargs,
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise LLMProviderError(self.name, "DEEPSEEK API Key 未配置")

        try:
            from openai import AsyncOpenAI
        except ImportError as e:  # pragma: no cover
            raise LLMProviderError(self.name, "openai SDK 未安装", e)

        # 拼上 system 消息（OpenAI 风格）
        full_messages: List[Dict[str, Any]] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        try:
            client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
            call = client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            response = await asyncio.wait_for(call, timeout=timeout)
        except asyncio.TimeoutError as e:
            raise LLMProviderError(self.name, f"timeout after {timeout}s", e)
        except Exception as e:
            raise LLMProviderError(self.name, f"API 调用失败: {e}", e)

        choice = response.choices[0] if response.choices else None
        text = (choice.message.content or "") if choice else ""
        usage = getattr(response, "usage", None)
        return {
            "text": text,
            "tokens_in": getattr(usage, "prompt_tokens", 0) if usage else 0,
            "tokens_out": getattr(usage, "completion_tokens", 0) if usage else 0,
            "model": self.model,
            "provider": self.name,
        }
