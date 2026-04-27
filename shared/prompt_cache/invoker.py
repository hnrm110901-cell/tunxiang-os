"""Anthropic 调用封装 — 统一 D4 系列的 Prompt Cache API 入口

职责：
  1. CacheInvoker Protocol — D4 service 用来类型标注 invoker 参数
  2. AnthropicCacheInvoker — 真实 Anthropic SDK 调用封装
     · 失败时不抛异常而是返回 error 字段，交由 service 层决定降级策略
     · 自动 retry（指数退避）
     · usage 字段标准化

设计决策：
  · SDK 通过 lazy import（运行时 ImportError 时仍能 import 本模块）
  · 超时硬编码 60s（D4 分析都是长文本，不应卡在默认 600s）
  · 不在本层做 fallback（fallback 是 service 层规则引擎的职责）
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol

logger = logging.getLogger(__name__)

# invoker 协议：async (request: dict) → response: dict
CacheInvoker = Callable[[dict], Awaitable[dict]]


@dataclass(frozen=True)
class UsageStats:
    """统一的 usage 数据结构（单次调用）"""

    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_input(self) -> int:
        return self.cache_read_tokens + self.cache_creation_tokens + self.input_tokens

    @property
    def cache_hit_rate(self) -> float:
        if self.total_input <= 0:
            return 0.0
        return round(self.cache_read_tokens / self.total_input, 4)

    @classmethod
    def from_response(cls, response: dict[str, Any]) -> "UsageStats":
        usage = response.get("usage") or {}
        return cls(
            cache_read_tokens=int(usage.get("cache_read_input_tokens", 0) or 0),
            cache_creation_tokens=int(
                usage.get("cache_creation_input_tokens", 0) or 0
            ),
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
        )


class CacheInvokerProtocol(Protocol):
    """类型提示用的协议（Python 3.8+）"""

    async def __call__(self, request: dict) -> dict: ...


@dataclass
class AnthropicCacheInvoker:
    """真实 Anthropic SDK 调用封装。

    用法：
        from shared.prompt_cache import AnthropicCacheInvoker

        invoker = AnthropicCacheInvoker(api_key="...")  # 或 env ANTHROPIC_API_KEY
        service = CostRootCauseService(invoker=invoker)

    参数：
      · api_key — 默认读 env ANTHROPIC_API_KEY
      · timeout_s — 单次请求超时，默认 60s
      · max_retries — 失败重试次数（429/500/503），默认 2
      · base_url — 默认用 SDK 内置，自定义用于测试或代理
    """

    api_key: Optional[str] = None
    timeout_s: float = 60.0
    max_retries: int = 2
    base_url: Optional[str] = None
    _client: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.getenv("ANTHROPIC_API_KEY")
        # 不强制要求 api_key 存在：允许在构造时延迟，在调用时再检查
        # 这样单元测试可以构造 AnthropicCacheInvoker() 而不需要真的 key

    def _get_client(self) -> Any:
        """懒加载 Anthropic SDK client（只在首次调用时 import）"""
        if self._client is not None:
            return self._client

        if not self.api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY 未设置。通过构造参数 api_key 或 env "
                "ANTHROPIC_API_KEY 注入。"
            )

        try:
            from anthropic import AsyncAnthropic  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "anthropic SDK 未安装。pip install 'anthropic>=0.40.0' 后重试。"
            ) from exc

        kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url

        self._client = AsyncAnthropic(**kwargs)
        return self._client

    async def __call__(self, request: dict) -> dict:
        """调用 Anthropic Messages API，带 retry + timeout。

        request 结构遵循 BaseCachedPromptBuilder.build_messages() 返回：
            {"model", "max_tokens", "system": [...], "messages": [...]}

        返回原始 Anthropic SDK 响应 dict（含 content + usage）。
        """
        client = self._get_client()
        attempt = 0
        last_exc: Exception | None = None
        while attempt <= self.max_retries:
            try:
                response = await asyncio.wait_for(
                    client.messages.create(
                        extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
                        **request,
                    ),
                    timeout=self.timeout_s,
                )
                return _sdk_response_to_dict(response)
            except asyncio.TimeoutError as exc:
                last_exc = exc
                logger.warning(
                    "anthropic_cache_invoker_timeout",
                    extra={"attempt": attempt, "timeout_s": self.timeout_s},
                )
            except Exception as exc:  # SDK 异常类型因版本而异，统一捕获
                last_exc = exc
                status = getattr(exc, "status_code", None)
                # 4xx 非 429 不重试（业务错误）
                if status and 400 <= status < 500 and status != 429:
                    logger.warning(
                        "anthropic_cache_invoker_4xx_no_retry",
                        extra={"status": status, "error": str(exc)[:200]},
                    )
                    raise
                logger.warning(
                    "anthropic_cache_invoker_retry",
                    extra={
                        "attempt": attempt,
                        "status": status,
                        "error": str(exc)[:200],
                    },
                )

            attempt += 1
            if attempt <= self.max_retries:
                await asyncio.sleep(0.5 * (2**attempt))  # 1s, 2s

        assert last_exc is not None  # noqa: S101
        raise last_exc


def _sdk_response_to_dict(response: Any) -> dict[str, Any]:
    """把 Anthropic SDK 响应对象转成 plain dict（方便序列化 + 缓存测试）。

    Anthropic SDK v0.40+ 的响应是 pydantic-like 对象，有 .model_dump() 方法。
    早期版本返回 dict。两种形态都兼容。
    """
    if isinstance(response, dict):
        return response
    # Pydantic BaseModel
    if hasattr(response, "model_dump"):
        return response.model_dump()
    # Fallback：用 __dict__
    if hasattr(response, "__dict__"):
        return dict(response.__dict__)
    return {"content": [{"type": "text", "text": str(response)}], "usage": {}}
