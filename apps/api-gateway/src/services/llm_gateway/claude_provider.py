"""
Claude Provider — 基于 Anthropic 官方 SDK 的异步封装
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import structlog

from .base import LLMProvider, LLMProviderError

logger = structlog.get_logger()


class ClaudeProvider(LLMProvider):
    """Anthropic Claude 提供商"""

    name = "claude"
    default_model = "claude-sonnet-4-6"

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
            raise LLMProviderError(self.name, "ANTHROPIC_API_KEY 未配置")

        try:
            from anthropic import AsyncAnthropic
        except ImportError as e:  # pragma: no cover
            raise LLMProviderError(self.name, "anthropic SDK 未安装", e)

        try:
            client = AsyncAnthropic(api_key=self.api_key)
            # Anthropic 要求 system 单独传，messages 中只能有 user/assistant
            call = client.messages.create(
                model=self.model,
                messages=messages,
                system=system or "",
                temperature=temperature,
                max_tokens=max_tokens,
            )
            response = await asyncio.wait_for(call, timeout=timeout)
        except asyncio.TimeoutError as e:
            raise LLMProviderError(self.name, f"timeout after {timeout}s", e)
        except Exception as e:
            raise LLMProviderError(self.name, f"API 调用失败: {e}", e)

        # 提取文本
        text_parts = []
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        text = "".join(text_parts)

        usage = getattr(response, "usage", None)
        return {
            "text": text,
            "tokens_in": getattr(usage, "input_tokens", 0) if usage else 0,
            "tokens_out": getattr(usage, "output_tokens", 0) if usage else 0,
            "model": self.model,
            "provider": self.name,
        }
