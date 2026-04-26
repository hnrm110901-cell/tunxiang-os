"""ToxiproxyClient — async wrapper for the toxiproxy 2.x admin API.

Sprint F2 — Phase 1（仅设施）：
    - 不接入任何 Tier 1 测试套件
    - 仅供未来 §19 二次审查后的故障注入测试使用

预置代理（参见 infra/docker/toxiproxy/proxies.json）：
    pg_proxy      → postgres:5432   (listen :9001)
    redis_proxy   → redis:6379      (listen :9002)
    coreml_proxy  → host.docker.internal:8100 (listen :9003)

参考：https://github.com/Shopify/toxiproxy#http-api
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ToxiproxyError(RuntimeError):
    """Toxiproxy admin API call failed."""


class ToxiproxyClient:
    """Async wrapper for toxiproxy admin API (port 8474 by default).

    Usage:
        async with ToxiproxyClient() as tp:
            await tp.add_latency("pg_proxy", ms=500, jitter_ms=50)
            try:
                # run flaky scenario
                ...
            finally:
                await tp.reset()  # 清理本 client 期间注入的 toxics
    """

    DEFAULT_BASE_URL = "http://localhost:8474"
    DEFAULT_TIMEOUT_S = 5.0

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._client: httpx.AsyncClient | None = None

    # ── lifecycle ──────────────────────────────────────────────────────
    async def __aenter__(self) -> "ToxiproxyClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_s,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise ToxiproxyError(
                "ToxiproxyClient not entered — use `async with ToxiproxyClient() as tp:`"
            )
        return self._client

    # ── high-level toxics ──────────────────────────────────────────────
    async def add_latency(
        self,
        proxy_name: str,
        ms: int,
        jitter_ms: int = 0,
        toxicity: float = 1.0,
        direction: str = "downstream",
    ) -> dict[str, Any]:
        """注入固定延迟（latency toxic）。

        ms / jitter_ms 单位毫秒。toxicity 0.0-1.0 表示按比例命中。
        direction: downstream（响应方向）/ upstream（请求方向）
        """
        return await self._add_toxic(
            proxy_name,
            type_="latency",
            attributes={"latency": ms, "jitter": jitter_ms},
            toxicity=toxicity,
            stream=direction,
        )

    async def add_packet_loss(
        self,
        proxy_name: str,
        percent: float,
        direction: str = "downstream",
    ) -> dict[str, Any]:
        """模拟丢包：用 toxiproxy 的 timeout toxic 实现高丢包率。

        toxiproxy 没有原生 packet_loss，标准做法是 timeout toxic + toxicity:
            toxicity=percent/100 时，对应比例的连接被立即断开。
        """
        if not 0.0 <= percent <= 100.0:
            raise ValueError("percent must be 0-100")
        return await self._add_toxic(
            proxy_name,
            type_="timeout",
            attributes={"timeout": 0},  # 立即超时 = 断开
            toxicity=percent / 100.0,
            stream=direction,
        )

    async def add_bandwidth_limit(
        self,
        proxy_name: str,
        kbps: int,
        direction: str = "downstream",
    ) -> dict[str, Any]:
        """限制带宽（bandwidth toxic）。"""
        return await self._add_toxic(
            proxy_name,
            type_="bandwidth",
            attributes={"rate": kbps},
            stream=direction,
        )

    async def disable(self, proxy_name: str) -> None:
        """完全禁用代理（模拟整链路断网）。"""
        resp = await self._http().post(
            f"/proxies/{proxy_name}",
            json={"enabled": False},
        )
        self._raise_for_status(resp, f"disable {proxy_name}")

    async def enable(self, proxy_name: str) -> None:
        """重新启用代理。"""
        resp = await self._http().post(
            f"/proxies/{proxy_name}",
            json={"enabled": True},
        )
        self._raise_for_status(resp, f"enable {proxy_name}")

    async def list_proxies(self) -> dict[str, Any]:
        """列出所有代理（含其上挂载的 toxics）。"""
        resp = await self._http().get("/proxies")
        self._raise_for_status(resp, "list_proxies")
        return resp.json()

    async def list_toxics(self, proxy_name: str) -> list[dict[str, Any]]:
        resp = await self._http().get(f"/proxies/{proxy_name}/toxics")
        self._raise_for_status(resp, f"list_toxics {proxy_name}")
        return resp.json()

    async def remove_toxic(self, proxy_name: str, toxic_name: str) -> None:
        resp = await self._http().delete(f"/proxies/{proxy_name}/toxics/{toxic_name}")
        self._raise_for_status(resp, f"remove_toxic {proxy_name}/{toxic_name}")

    async def reset(self) -> None:
        """重置：清空所有代理上的所有 toxics（不影响 enabled 状态）。

        toxiproxy admin POST /reset 会把所有 enabled=false 的代理重新启用，
        并清掉所有 toxics。这是测试结束时的标准清理。
        """
        resp = await self._http().post("/reset")
        self._raise_for_status(resp, "reset")

    async def health(self) -> bool:
        """探活：toxiproxy admin 是否可达。"""
        try:
            resp = await self._http().get("/version")
            return resp.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("toxiproxy health check failed: %s", exc)
            return False

    # ── internals ──────────────────────────────────────────────────────
    async def _add_toxic(
        self,
        proxy_name: str,
        type_: str,
        attributes: dict[str, Any],
        toxicity: float = 1.0,
        stream: str = "downstream",
        name: str | None = None,
    ) -> dict[str, Any]:
        # toxic name 自动派生，便于按名删除
        toxic_name = name or f"{type_}_{stream}"
        body = {
            "name": toxic_name,
            "type": type_,
            "stream": stream,
            "toxicity": toxicity,
            "attributes": attributes,
        }
        resp = await self._http().post(f"/proxies/{proxy_name}/toxics", json=body)
        self._raise_for_status(resp, f"add_toxic {proxy_name}/{toxic_name}")
        return resp.json()

    @staticmethod
    def _raise_for_status(resp: httpx.Response, action: str) -> None:
        if resp.status_code >= 400:
            raise ToxiproxyError(
                f"toxiproxy {action} failed: HTTP {resp.status_code} — {resp.text}"
            )
