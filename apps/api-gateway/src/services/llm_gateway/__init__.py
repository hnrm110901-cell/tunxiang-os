"""
LLM Gateway 包 — D6 AI 决策层治理核心

提供能力：
  1. 降级链：Claude → DeepSeek → OpenAI，任一家挂掉自动 fallback，整层不停摆
  2. 安全网关：prompt injection 过滤、PII 脱敏、输出敏感词过滤、全链审计
  3. 单例工厂：config 驱动的全局 gateway 实例
"""

from .base import LLMAllProvidersFailedError, LLMProvider, LLMProviderError
from .factory import get_llm_gateway
from .gateway import LLMGateway

__all__ = [
    "LLMProvider",
    "LLMProviderError",
    "LLMAllProvidersFailedError",
    "LLMGateway",
    "get_llm_gateway",
]
