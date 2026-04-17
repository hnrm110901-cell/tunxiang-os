"""
LLMProvider 抽象基类 + 异常定义

每个 provider 只需实现 `chat(messages, **kwargs)`，返回标准化 dict：
  {
    "text": str,           # 模型返回的文本
    "tokens_in": int,      # 输入 token 数
    "tokens_out": int,     # 输出 token 数
    "model": str,          # 实际使用的模型 ID
    "provider": str,       # provider 名（claude/deepseek/openai）
  }
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class LLMProviderError(Exception):
    """单个 LLM provider 调用失败（允许降级重试）"""

    def __init__(self, provider: str, message: str, original: Optional[Exception] = None):
        self.provider = provider
        self.original = original
        super().__init__(f"[{provider}] {message}")


class LLMAllProvidersFailedError(Exception):
    """降级链中所有 provider 都失败（终极熔断）"""

    def __init__(self, errors: Dict[str, str]):
        self.errors = errors
        detail = "; ".join(f"{k}: {v}" for k, v in errors.items())
        super().__init__(f"All LLM providers failed — {detail}")


class LLMProvider(ABC):
    """所有 LLM provider 的统一接口"""

    # 子类必须覆盖
    name: str = "base"
    default_model: str = ""

    def __init__(self, api_key: str, model: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key
        self.model = model or self.default_model
        self.base_url = base_url

    @abstractmethod
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
        """
        统一对话接口

        Args:
            messages: OpenAI 风格消息列表 [{"role": "user"|"assistant", "content": "..."}]
            system:   系统提示（可选）
            timeout:  单次请求超时时间（秒）

        Returns:
            标准化响应 dict（见模块 docstring）

        Raises:
            LLMProviderError: provider 调用失败（可降级）
        """
        raise NotImplementedError

    def is_available(self) -> bool:
        """检查 provider 是否有效配置（有 api_key）"""
        return bool(self.api_key)
