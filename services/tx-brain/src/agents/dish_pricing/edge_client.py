"""D3c — coreml-bridge HTTP client for /predict/dish-price.

短超时（200ms），失败立即抛 EdgeUnavailableError 让上层走 cloud fallback。
不缓存健康状态——D3c 是 Tier 2 路径，每个请求都重试边缘（fail fast 即可）。
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

from .schemas import DishPricingRequest

logger = structlog.get_logger(__name__)

_DEFAULT_BRIDGE_URL = "http://localhost:8100"
_TIMEOUT_SECONDS = 0.2  # 200ms — Tier 2 优先级，超时立即降级


class EdgeUnavailableError(Exception):
    """coreml-bridge 不可达（超时 / 连接拒绝 / 5xx）—— 触发 cloud fallback"""


class DishPricingEdgeClient:
    """对 coreml-bridge POST /predict/dish-price 的薄封装"""

    def __init__(self, base_url: str | None = None, timeout_seconds: float | None = None) -> None:
        self.base_url = (base_url or os.environ.get("COREML_BRIDGE_URL", _DEFAULT_BRIDGE_URL)).rstrip("/")
        self.timeout = timeout_seconds if timeout_seconds is not None else _TIMEOUT_SECONDS

    async def predict(self, req: DishPricingRequest) -> dict[str, Any]:
        """调用边缘 /predict/dish-price。

        Returns:
            原始 dict（与 Swift DishPriceResponse 字段一致）。

        Raises:
            EdgeUnavailableError: 超时、连接拒绝或非 2xx 响应。
        """
        payload = {
            "dish_id": req.dish_id,
            "store_id": req.store_id,
            "tenant_id": req.tenant_id,
            "base_price_fen": req.base_price_fen,
            "cost_fen": req.cost_fen,
            "time_of_day": req.time_of_day,
            "traffic_forecast": req.traffic_forecast,
            "inventory_status": req.inventory_status,
        }

        url = f"{self.base_url}/predict/dish-price"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            logger.warning(
                "dish_pricing_edge_timeout",
                dish_id=req.dish_id,
                store_id=req.store_id,
                timeout_s=self.timeout,
            )
            raise EdgeUnavailableError(f"edge timeout after {self.timeout}s") from exc
        except httpx.ConnectError as exc:
            logger.warning(
                "dish_pricing_edge_connect_error",
                dish_id=req.dish_id,
                store_id=req.store_id,
                error=str(exc),
            )
            raise EdgeUnavailableError(f"edge connect failed: {exc}") from exc
        except httpx.HTTPError as exc:
            # 包括 ReadError / RemoteProtocolError 等
            logger.warning(
                "dish_pricing_edge_http_error",
                dish_id=req.dish_id,
                error=str(exc),
            )
            raise EdgeUnavailableError(f"edge http error: {exc}") from exc

        if resp.status_code >= 500:
            raise EdgeUnavailableError(f"edge 5xx: {resp.status_code}")
        if resp.status_code >= 400:
            # 4xx 是输入问题，不属于边缘故障，向上传播
            raise ValueError(f"edge rejected request: {resp.status_code} {resp.text[:200]}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise EdgeUnavailableError(f"edge returned non-json: {exc}") from exc

        return data
