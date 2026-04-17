"""
Gateway 单例工厂 — 从 config 构建 LLMGateway
"""

from __future__ import annotations

from threading import Lock
from typing import List, Optional

from ...core.config import settings
from .base import LLMProvider
from .claude_provider import ClaudeProvider
from .deepseek_provider import DeepSeekProvider
from .gateway import LLMGateway
from .openai_provider import OpenAIProvider

_gateway: Optional[LLMGateway] = None
_lock = Lock()


def _build_providers(priority_str: str) -> List[LLMProvider]:
    """按配置中的 priority 顺序实例化 provider 列表"""
    providers: List[LLMProvider] = []
    for name in [p.strip().lower() for p in priority_str.split(",") if p.strip()]:
        if name == "claude":
            providers.append(
                ClaudeProvider(
                    api_key=settings.ANTHROPIC_API_KEY,
                    model="claude-sonnet-4-6",
                )
            )
        elif name == "deepseek":
            providers.append(
                DeepSeekProvider(
                    # 若主 LLM_PROVIDER 就是 deepseek，复用 LLM_API_KEY
                    api_key=settings.LLM_API_KEY if settings.LLM_PROVIDER == "deepseek" else "",
                    model="deepseek-chat",
                    base_url="https://api.deepseek.com",
                )
            )
        elif name == "openai":
            providers.append(
                OpenAIProvider(
                    api_key=settings.OPENAI_API_KEY,
                    model=settings.MODEL_NAME or "gpt-4-turbo-preview",
                    base_url=settings.OPENAI_API_BASE or "https://api.openai.com/v1",
                )
            )
    return providers


def get_llm_gateway() -> LLMGateway:
    """返回全局单例 LLMGateway"""
    global _gateway
    if _gateway is None:
        with _lock:
            if _gateway is None:
                priority = getattr(settings, "LLM_PROVIDER_PRIORITY", "claude,deepseek,openai")
                timeout = float(getattr(settings, "LLM_TIMEOUT_SEC", 5.0))
                fallback_enabled = bool(getattr(settings, "LLM_FALLBACK_ENABLED", True))
                providers = _build_providers(priority)
                _gateway = LLMGateway(
                    providers=providers,
                    timeout=timeout,
                    fallback_enabled=fallback_enabled,
                    security_enabled=True,
                )
    return _gateway


def reset_gateway() -> None:
    """测试/配置重载用：清空单例"""
    global _gateway
    with _lock:
        _gateway = None
