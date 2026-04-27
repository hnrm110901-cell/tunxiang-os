"""单元测试：ToxiproxyClient 不依赖真 toxiproxy 容器。

通过 httpx mock_transport 注入假响应。
"""

from __future__ import annotations

import json

import httpx
import pytest

from shared.test_infra.toxiproxy_client import ToxiproxyClient, ToxiproxyError


def _make_client(handler) -> ToxiproxyClient:
    """构造一个用 MockTransport 替换底层 client 的 ToxiproxyClient。"""
    transport = httpx.MockTransport(handler)
    client = ToxiproxyClient(base_url="http://toxiproxy.test")
    client._client = httpx.AsyncClient(  # noqa: SLF001 — 测试注入
        base_url="http://toxiproxy.test",
        transport=transport,
        timeout=2.0,
    )
    return client


@pytest.mark.asyncio
async def test_add_latency_posts_correct_payload():
    received = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["url"] = str(request.url)
        received["body"] = json.loads(request.content)
        return httpx.Response(200, json={"name": "latency_downstream", "type": "latency"})

    client = _make_client(handler)
    try:
        result = await client.add_latency("pg_proxy", ms=500, jitter_ms=50)
    finally:
        await client._client.aclose()  # noqa: SLF001

    assert received["url"].endswith("/proxies/pg_proxy/toxics")
    assert received["body"]["type"] == "latency"
    assert received["body"]["attributes"] == {"latency": 500, "jitter": 50}
    assert received["body"]["toxicity"] == 1.0
    assert received["body"]["stream"] == "downstream"
    assert result["type"] == "latency"


@pytest.mark.asyncio
async def test_add_packet_loss_uses_timeout_with_toxicity():
    received = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    client = _make_client(handler)
    try:
        await client.add_packet_loss("redis_proxy", percent=30)
    finally:
        await client._client.aclose()  # noqa: SLF001

    assert received["body"]["type"] == "timeout"
    assert received["body"]["attributes"] == {"timeout": 0}
    assert received["body"]["toxicity"] == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_add_packet_loss_validates_range():
    client = _make_client(lambda r: httpx.Response(200, json={}))
    try:
        with pytest.raises(ValueError):
            await client.add_packet_loss("pg_proxy", percent=150)
    finally:
        await client._client.aclose()  # noqa: SLF001


@pytest.mark.asyncio
async def test_disable_and_enable_post_correct_flag():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={})

    client = _make_client(handler)
    try:
        await client.disable("pg_proxy")
        await client.enable("pg_proxy")
    finally:
        await client._client.aclose()  # noqa: SLF001

    assert seen == [{"enabled": False}, {"enabled": True}]


@pytest.mark.asyncio
async def test_reset_calls_global_reset_endpoint():
    seen_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(204)

    client = _make_client(handler)
    try:
        await client.reset()
    finally:
        await client._client.aclose()  # noqa: SLF001

    assert seen_paths == ["/reset"]


@pytest.mark.asyncio
async def test_http_error_raises_toxiproxyerror():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, text="proxy busy")

    client = _make_client(handler)
    try:
        with pytest.raises(ToxiproxyError) as exc:
            await client.disable("pg_proxy")
    finally:
        await client._client.aclose()  # noqa: SLF001

    assert "409" in str(exc.value)


@pytest.mark.asyncio
async def test_not_entered_raises_clear_error():
    client = ToxiproxyClient()  # 没进入 async with
    with pytest.raises(ToxiproxyError, match="not entered"):
        await client.disable("pg_proxy")


@pytest.mark.asyncio
async def test_health_returns_false_on_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    client = _make_client(handler)
    try:
        assert await client.health() is False
    finally:
        await client._client.aclose()  # noqa: SLF001
