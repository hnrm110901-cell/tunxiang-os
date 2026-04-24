"""Provider 适配器公共基类。

提取各适配器共用的重试、超时、错误处理逻辑。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC
from typing import Optional

import structlog

logger = structlog.get_logger()


class BaseProviderAdapter(ABC):  # noqa: B024  # 基类暂无抽象方法，留作子类扩展
    """适配器基类，包含公共重试和超时逻辑。"""

    RETRY_DELAYS = [1, 2, 4]  # 指数退避

    def __init__(self, api_key: Optional[str], base_url: Optional[str], timeout_s: int = 30, max_retries: int = 3):
        self._api_key = api_key
        self._base_url = base_url
        self._timeout_s = timeout_s
        self._max_retries = max_retries

    async def _retry_with_backoff(self, coro_factory, *, retryable_exceptions: tuple = (Exception,)):
        """通用重试逻辑。coro_factory 是无参可调用对象，每次调用返回新协程。"""
        last_exc = None
        for attempt in range(self._max_retries):
            if attempt > 0:
                delay = self.RETRY_DELAYS[min(attempt - 1, len(self.RETRY_DELAYS) - 1)]
                await asyncio.sleep(delay)
            try:
                return await asyncio.wait_for(coro_factory(), timeout=self._timeout_s)
            except retryable_exceptions as exc:
                last_exc = exc
                logger.warning(
                    "provider_retry",
                    provider=self.name.value if hasattr(self, "name") else "unknown",
                    attempt=attempt + 1,
                    error=str(exc),
                )
        raise last_exc

    @staticmethod
    def _generate_request_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.monotonic() - start) * 1000)
