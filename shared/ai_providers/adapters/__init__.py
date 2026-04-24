"""Provider 适配器集合。

每个适配器封装一个模型提供商的 API 调用逻辑，对外暴露统一的 ProviderAdapter 接口。
"""

from .anthropic_adapter import AnthropicAdapter
from .base import BaseProviderAdapter
from .deepseek_adapter import DeepSeekAdapter
from .ernie_adapter import ERNIEAdapter
from .glm_adapter import GLMAdapter
from .kimi_adapter import KimiAdapter
from .qwen_adapter import QwenAdapter

__all__ = [
    "BaseProviderAdapter",
    "AnthropicAdapter",
    "DeepSeekAdapter",
    "ERNIEAdapter",
    "GLMAdapter",
    "KimiAdapter",
    "QwenAdapter",
]
